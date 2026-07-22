"""
飆股 (pure-momentum) scoring — the deliberate opposite of analysis.indicators.score_stock.

score_stock is a balanced / mean-reversion-leaning score: it rewards oversold
pullbacks and PENALISES overbought RSI, high 乖離, and riding the upper Bollinger
band. A 飆股 (explosive runner) screen wants exactly those "penalised" traits, so
this module defines its own momentum-only ranking that never docks points for
being extended.
"""
import pandas as pd

from config import LIMIT_UP_PCT


def consecutive_up_days(df: pd.DataFrame, max_lookback: int = 10) -> int:
    """Count trailing consecutive up-close days (Close > previous Close)."""
    close = df["Close"].dropna()
    if len(close) < 2:
        return 0
    streak = 0
    for i in range(len(close) - 1, 0, -1):
        if close.iloc[i] > close.iloc[i - 1]:
            streak += 1
        else:
            break
        if streak >= max_lookback:
            break
    return streak


def is_limit_up(change_pct: float) -> bool:
    """(near-)漲停: today's %change at or above the limit threshold."""
    return float(change_pct or 0) >= LIMIT_UP_PCT


def score_momentum(ind: dict, rs: dict | None, change_pct: float,
                   up_days: int = 0) -> tuple[int, list[str]]:
    """
    Return (score, signals) for a pure-momentum 飆股 screen (0-100 scale).

    ind:         extract_indicators() dict (vol_ratio, bb_pct, ma_structure…).
    rs:          compute_relative_strength() dict (rs20). May be None/empty.
    change_pct:  today's (or intraday) percent change.
    up_days:     consecutive_up_days().

    Deliberately contains NO overbought / high-乖離 penalties.
    """
    rs = rs or {}
    score = 0
    signals: list[str] = []

    # --- Price thrust / limit-up (max 30) ---
    cp = float(change_pct or 0)
    if cp >= LIMIT_UP_PCT:
        score += 30
        signals.append(f"漲停/近漲停(+{cp:.1f}%)")
    elif cp >= 5:
        score += 20
        signals.append(f"強勢大漲(+{cp:.1f}%)")
    elif cp >= 3:
        score += 12
        signals.append(f"上漲(+{cp:.1f}%)")
    elif cp > 0:
        score += 5

    # --- Volume surge 量比 (max 20) ---
    vr = float(ind.get("vol_ratio", 0) or 0)
    if vr >= 3:
        score += 20
        signals.append(f"爆量({vr:.1f}倍)")
    elif vr >= 2:
        score += 14
        signals.append(f"大量({vr:.1f}倍)")
    elif vr >= 1.5:
        score += 8
        signals.append(f"放量({vr:.1f}倍)")

    # --- Relative strength vs TAIEX (max 18) ---
    rs20 = float(rs.get("rs20", 0) or 0)
    if rs20 >= 15:
        score += 18
        signals.append(f"極強於大盤(RS+{rs20:.0f})")
    elif rs20 >= 8:
        score += 12
        signals.append(f"明顯強於大盤(RS+{rs20:.0f})")
    elif rs20 >= 2:
        score += 6

    # --- Trend structure / breakout (max 20) ---
    if ind.get("ma_structure") == "多頭排列":
        score += 12
        signals.append("均線多頭排列")
    bb = float(ind.get("bb_pct", 0.5) or 0.5)
    if bb > 0.9:
        score += 8
        signals.append("站上布林上軌(強勢突破)")

    # --- Consecutive up days (max 12) ---
    if up_days >= 4:
        score += 12
        signals.append(f"連{up_days}紅")
    elif up_days >= 3:
        score += 8
        signals.append(f"連{up_days}紅")
    elif up_days >= 2:
        score += 4

    # Component maxima sum to exactly 100 today; clamp so a future weight tweak
    # (or an unexpectedly extreme input) can't silently push the score past the
    # documented 0-100 scale.
    return min(score, 100), signals
