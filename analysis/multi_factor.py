"""
盤後多因子評分 — folds signals that stage2_chip only used as a binary pass/fail
gate (and several fetched-but-never-scored factors) into the actual ranking.

`score_stock` (analysis/indicators.py) stays untouched — it remains the pure
price/volume technical score used by fetch_backtest_picks and backtest.py.
This module adds four independent, magnitude-aware components on top of it:

  chip_score        外資/投信/三大法人 magnitude + 外資連買天數 + 融資/融券 change
                    (stage2_chip's chip_signals only counted +1 per boolean;
                    this scales the same fields by size/duration instead)
  fundamental_score 月營收 YoY (same thresholds score_stock already uses) + MoM
                    (fetched by fetcher_fundamental but never scored before)
  sector_score      today's industry strength (market_hot.compute_sector_score_map),
                    never folded into per-stock ranking before
  rs60_score        60-day relative strength (only RS20 was ever scored)

combine_scores() blends tech_score with these four via a `strategy` weight
preset (balanced/trend/reversal) into one ranking score. Because score_stock
itself isn't decomposed, strategy differentiation here reweights the NEW
components against the (unchanged) blended tech_score baseline — it does not
separate score_stock's own internal trend-vs-reversal signal mix.
"""
import math

# Weight multipliers applied to each already-scored component before summing.
# tech_score's own scale (score_stock, ~0-150) is left at weight 1.0 in every
# preset; the four new components are reweighted per strategy.
STRATEGY_WEIGHTS = {
    "balanced": {"tech": 1.0, "chip": 1.0, "fundamental": 0.8, "sector": 0.6, "rs60": 0.6},
    "trend":    {"tech": 1.0, "chip": 1.2, "fundamental": 0.6, "sector": 1.0, "rs60": 1.2},
    "reversal": {"tech": 1.0, "chip": 0.7, "fundamental": 0.5, "sector": 0.3, "rs60": 0.2},
}


def compute_chip_score(chip_row: dict) -> tuple[int, list[str]]:
    """
    Magnitude/duration-aware chip score (max ~35, min ~-10) from the same
    fields stage2_chip.chip_signals only booleaned. chip_row keys match
    stage2_chip's attached columns (foreign_net_today, trust_net_today,
    big3_net_today, foreign_net_5d, foreign_consec_buy, margin_change_pct,
    short_change_pct) — any missing/None field contributes 0, not an error.

    TPEX-vs-TWSE normalization: TPEX genuinely has no 5-day 外資淨買 figure
    and no margin day-over-day comparison (data/fetcher_chip.py leaves those
    NaN, not a fake 0), so TPEX stocks structurally can't earn the +3
    (foreign_net_5d>0) or +2/+4 (margin_change_pct<0) bonuses TWSE stocks
    can. Left alone this compresses TPEX's chip_score distribution toward
    zero even when its available signals are all strongly positive
    (mcp_server.py's per-exchange quota sampling only masks the ranking-side
    symptom, not this root cause). Fix: track how many of the 4 "bonus-
    eligible" fields are actually available (non-NaN) for this stock, and
    rescale the *positive* portion of the score by (4 / available) so a
    TPEX stock that fires on 2 of 2 available signals scores comparably to
    a TWSE stock firing on 2 of 4. Negative contributions are never
    rescaled — a real 三大法人賣超/融券大增 shouldn't be softened just
    because other fields were unavailable.
    """
    def g(key):
        v = chip_row.get(key)
        return float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else 0.0

    def available(key):
        v = chip_row.get(key)
        return v is not None and not (isinstance(v, float) and math.isnan(v))

    # The 4 fields that can each independently swing the score positive but
    # aren't always fetchable (see docstring): foreign_net_5d, margin_change_pct
    # (both TPEX-NaN), plus foreign_consec_buy/big3_net_today which are always
    # available on both exchanges and so always count.
    bonus_fields = ("foreign_consec_buy", "big3_net_today", "foreign_net_5d", "margin_change_pct")
    n_available = sum(1 for f in bonus_fields if available(f))
    positive_scale = (len(bonus_fields) / n_available) if n_available > 0 else 1.0

    pos_score = 0
    neg_score = 0
    signals: list[str] = []

    consec = g("foreign_consec_buy")
    if consec >= 5:
        pos_score += 10
        signals.append(f"外資連續買超{consec:.0f}日")
    elif consec >= 3:
        pos_score += 6
        signals.append(f"外資連續買超{consec:.0f}日")
    elif consec >= 2:
        pos_score += 3

    big3 = g("big3_net_today")
    if big3 > 10000:
        pos_score += 10
        signals.append(f"三大法人大幅買超({big3:+,.0f}張)")
    elif big3 > 3000:
        pos_score += 6
        signals.append(f"三大法人買超({big3:+,.0f}張)")
    elif big3 > 0:
        pos_score += 2
    elif big3 < -3000:
        neg_score -= 6
        signals.append(f"三大法人大幅賣超({big3:+,.0f}張)")
    elif big3 < 0:
        neg_score -= 2

    trust = g("trust_net_today")
    if trust > 1000:
        pos_score += 8
        signals.append(f"投信大幅買超({trust:+,.0f}張)")
    elif trust > 300:
        pos_score += 4
        signals.append(f"投信買超({trust:+,.0f}張)")
    elif trust > 0:
        pos_score += 2
    elif trust < 0:
        neg_score -= 2

    if available("foreign_net_5d") and g("foreign_net_5d") > 0:
        pos_score += 3

    margin_chg = g("margin_change_pct")
    if available("margin_change_pct"):
        if margin_chg < -3:
            pos_score += 4
            signals.append("融資大幅減少(籌碼健康)")
        elif margin_chg < 0:
            pos_score += 2
        elif margin_chg > 5:
            neg_score -= 4
            signals.append("融資大幅增加(追高風險)")

    short_chg = g("short_change_pct")
    if short_chg > 5:
        neg_score -= 3
        signals.append("融券大增(空方壓力)")

    score = round(pos_score * positive_scale) + neg_score
    if n_available < len(bonus_fields):
        signals.append(f"籌碼資料不完整({n_available}/{len(bonus_fields)}項可用，已正規化)")
    return score, signals


def compute_fundamental_score(fundamental: dict) -> tuple[int, list[str]]:
    """
    月營收 YoY (thresholds mirror score_stock's existing ones) + MoM (new —
    fetched by fetcher_fundamental but never scored anywhere before). Max ~18.
    """
    if not fundamental:
        return 0, []

    score = 0
    signals: list[str] = []

    yoy = fundamental.get("rev_yoy")
    if yoy is not None:
        if yoy >= 30:
            score += 12
            signals.append(f"月營收YoY大增({yoy:+.0f}%)")
        elif yoy >= 10:
            score += 7
            signals.append(f"月營收YoY成長({yoy:+.0f}%)")
        elif yoy <= -20:
            score -= 8
            signals.append(f"月營收YoY衰退({yoy:+.0f}%)")

    mom = fundamental.get("rev_mom")
    if mom is not None:
        if mom >= 15:
            score += 6
            signals.append(f"月營收MoM大增({mom:+.0f}%)")
        elif mom >= 5:
            score += 3
        elif mom <= -10:
            score -= 4
            signals.append(f"月營收MoM衰退({mom:+.0f}%)")

    return score, signals


def compute_sector_score(industry: str, sector_score_map: dict) -> tuple[int, str | None]:
    """
    Today's industry strength as a per-stock factor (market_hot.compute_sector_score_map
    covers every industry, not just the top-5 compute_hot_sectors displays).
    Returns (score, signal) — signal is None when the industry has no data
    (too thin, blank, or 其他) or isn't notably strong/weak.
    """
    raw = sector_score_map.get(industry)
    if raw is None:
        return 0, None
    if raw >= 4:
        return 8, f"所屬產業強勢({industry})"
    if raw >= 2:
        return 4, f"所屬產業偏強({industry})"
    if raw <= -1:
        return -4, f"所屬產業偏弱({industry})"
    return 0, None


def compute_rs60_score(rs60: float | None) -> tuple[int, str | None]:
    """60-day relative strength vs TAIEX — only RS20 was ever scored before."""
    if rs60 is None:
        return 0, None
    if rs60 >= 15:
        return 8, f"60日大幅強於大盤({rs60:+.1f}%)"
    if rs60 >= 5:
        return 4, f"60日強於大盤({rs60:+.1f}%)"
    if rs60 <= -15:
        return -6, f"60日明顯落後大盤({rs60:+.1f}%)"
    return 0, None


def combine_scores(tech_score: int, chip_score: int, fundamental_score: int,
                   sector_score: int, rs60_score: int,
                   tech_signals: list[str], chip_signals: list[str],
                   fundamental_signals: list[str], sector_signal: str | None,
                   rs60_signal: str | None,
                   strategy: str = "balanced") -> tuple[int, list[str], dict]:
    """
    Blend the five components per strategy weight preset into one ranking
    score. Returns (total_score, merged_signals, breakdown) — breakdown keeps
    every raw component score visible (same "raw values + transparent
    breakdown" convention as the rest of this project's output).
    """
    weights = STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["balanced"])

    total = (
        tech_score * weights["tech"]
        + chip_score * weights["chip"]
        + fundamental_score * weights["fundamental"]
        + sector_score * weights["sector"]
        + rs60_score * weights["rs60"]
    )
    total = max(0, round(total))

    signals = list(tech_signals) + list(chip_signals) + list(fundamental_signals)
    if sector_signal:
        signals.append(sector_signal)
    if rs60_signal:
        signals.append(rs60_signal)

    breakdown = {
        "技術面": tech_score,
        "籌碼面": chip_score,
        "基本面": fundamental_score,
        "族群強度": sector_score,
        "RS60": rs60_score,
        "策略": strategy,
    }
    return total, signals, breakdown
