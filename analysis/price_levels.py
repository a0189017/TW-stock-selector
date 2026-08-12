"""
Shared entry/take-profit/stop-loss price-level calculator.

Replaces the old flat `stop_ref = ma60 if ma60 > 0 else cost_price * 0.92`
(portfolio.py) with an ATR-based band that (a) scales with each stock's own
volatility instead of one fixed %, and (b) tightens the support anchor when
the stock is already extended (乖離過大) so the stop isn't left miles away.

Used by both:
  - portfolio.py (持股健檢 — reference stop-loss for an existing position)
  - analysis/screener.py::stage3_technical (候選股 — 建議買入/停利/停損 for a
    fresh recommendation), so every candidate carries these prices without
    Claude having to eyeball MA5/MA20 by hand each time.

Multiplier choices (2x ATR stop, 2.5x ATR target) mirror the ~10-trading-day
holding horizon backtest.py validated for score_stock (ai/prompt_builder.py's
"score is best calibrated for ~10 trading days" finding) — they are a
starting point, not backtested themselves; see docs/factor_analysis_findings.md
for the empirical basis used to pick them.
"""

# 乖離率超過此值視為「已經漲多」，沿用 score_stock 的乖離過大門檻 (indicators.py)。
BIAS_EXTENDED_PCT = 15.0
STOP_ATR_MULT = 2.0
TARGET_ATR_MULT = 2.5
TARGET_ATR_MULT_OVERBOUGHT = 1.5
# When true ATR is missing/zero (short history), fall back to this % of price
# as a synthetic ATR so the formula still produces a sane, non-zero band.
ATR_FALLBACK_PCT = 0.03


def compute_price_levels(close: float, ma5: float, ma20: float, ma60: float,
                         atr: float | None, bias20: float | None,
                         rsi: float | None = None,
                         bb_pct: float | None = None) -> dict:
    """
    Return {"建議買入區間": [lo, hi], "停損": price, "停利目標": price, "依據": str}.

    close/ma5/ma20/ma60 are prices (0 or missing → treated as unavailable).
    atr: analysis/indicators.py::compute_atr's latest value (may be None/0/NaN
         when history is too short — falls back to ATR_FALLBACK_PCT of close).
    bias20: 乖離_MA20_% (see analysis/indicators.py Bias20). Used to detect an
            already-extended stock, in which case the recommendation leans
            toward "wait for a pullback" instead of a chase-buy range.
    rsi / bb_pct: optional overbought signals (RSI>70 / Bollinger %B>1) that
                  trim the take-profit target and note the chase-risk.
    """
    close = float(close or 0)
    if close <= 0:
        return {}

    atr = float(atr) if atr and atr > 0 else close * ATR_FALLBACK_PCT
    bias20 = float(bias20) if bias20 is not None else 0.0
    extended = bias20 > BIAS_EXTENDED_PCT
    overbought = extended or (rsi is not None and rsi > 70) or (bb_pct is not None and bb_pct > 1.0)

    # Support anchor: the nearest MA the stock hasn't already broken far above.
    # Extended stocks lean on MA5 (closer, tighter) instead of MA20/60 (which
    # would leave the stop far below current price after a big run-up).
    ma5 = float(ma5 or 0)
    ma20 = float(ma20 or 0)
    ma60 = float(ma60 or 0)
    if extended and ma5 > 0:
        support = ma5
        support_label = "MA5"
    elif ma20 > 0:
        support = ma20
        support_label = "MA20"
    elif ma60 > 0:
        support = ma60
        support_label = "MA60"
    else:
        support = close * (1 - ATR_FALLBACK_PCT)
        support_label = "近似值(無均線資料)"

    # Stop-loss: whichever is tighter (closer to price) of a volatility-based
    # band and a small buffer below the support MA — avoids a stop so far
    # away that a single ATR spike blows past it, per the plan's "max()" rule.
    stop_loss = max(close - STOP_ATR_MULT * atr, support * 0.995)
    stop_loss = min(stop_loss, close * 0.995)  # never place the stop above price

    if extended:
        # Already run up a lot — don't chase; suggest waiting for a pullback
        # toward the support anchor rather than buying at the current price.
        entry_lo, entry_hi = support * 0.98, support * 1.02
        advice = f"乖離過大(+{bias20:.1f}%)，建議等回測{support_label}附近再進場，不追高"
    else:
        entry_lo, entry_hi = support, close
        advice = f"可於現價至{support_label}支撐區間分批進場"

    target_mult = TARGET_ATR_MULT_OVERBOUGHT if overbought else TARGET_ATR_MULT
    target = close + target_mult * atr
    if overbought and not extended:
        advice += "；RSI/布林偏超買，目標保守看待"

    return {
        "建議買入區間": [round(min(entry_lo, entry_hi), 2), round(max(entry_lo, entry_hi), 2)],
        "停損": round(stop_loss, 2),
        "停利目標": round(target, 2),
        "依據": advice,
    }
