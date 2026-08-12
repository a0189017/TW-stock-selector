"""
當日線型 (today's intraday candle shape) — pure arithmetic on the O/H/L/current
quote MIS provides (data/fetcher_snapshot.py), classifying patterns that daily-
bar technical indicators can't see: gap up/down, box-range (narrow) days, and
開高走低/開低走高 (opened-strong-faded vs opened-weak-recovered).

This exists because intraday screening only ever patches price/change% from
MIS while every technical indicator (KD/乖離/量比/RS) still runs on YESTERDAY's
daily bar — today's own candle shape was invisible. Mirrors the (score, signals)
convention used by score_stock / score_momentum.
"""
from config import INTRADAY_GAP_PCT, INTRADAY_BOX_RANGE_PCT, INTRADAY_EXTREME_POS


def classify_intraday_shape(o: float | None, h: float | None, l: float | None,
                            price: float | None, prev_close: float | None
                            ) -> tuple[list[str], int, dict]:
    """
    Classify today's O/H/L/current shape. Returns (signals, score_adj, metrics).

    score_adj is a small additive adjustment (same scale as other signal points
    elsewhere in the codebase, roughly -8..+8) meant to be folded into an
    existing score, not a standalone 0-100 score.

    Any missing input (common before the day's first print establishes O/H/L)
    → ([], 0, {}) rather than guessing.
    """
    if None in (o, h, l, price, prev_close) or prev_close <= 0 or h < l:
        return [], 0, {}

    signals: list[str] = []
    score_adj = 0

    gap_pct = round((o - prev_close) / prev_close * 100, 2)
    range_pct = round((h - l) / prev_close * 100, 2)
    # Position of open/current within today's [low, high] range, 0=low, 1=high.
    span = h - l
    open_pos = (o - l) / span if span > 0 else 0.5
    close_pos = (price - l) / span if span > 0 else 0.5

    metrics = {
        "跳空_%": gap_pct,
        "當日振幅_%": range_pct,
        "開盤位置": round(open_pos, 2),
        "收盤位置": round(close_pos, 2),
    }

    if gap_pct >= INTRADAY_GAP_PCT:
        signals.append(f"跳空高開(+{gap_pct:.1f}%)")
        score_adj += 5
    elif gap_pct <= -INTRADAY_GAP_PCT:
        signals.append(f"跳空低開({gap_pct:.1f}%)")
        score_adj -= 5

    if range_pct <= INTRADAY_BOX_RANGE_PCT:
        signals.append(f"箱型整理(振幅{range_pct:.1f}%)")

    # 開高走低 / 開低走高: opened near one extreme, currently near the other.
    if open_pos >= INTRADAY_EXTREME_POS and close_pos <= 1 - INTRADAY_EXTREME_POS:
        signals.append("開高走低(當日轉弱)")
        score_adj -= 8
    elif open_pos <= 1 - INTRADAY_EXTREME_POS and close_pos >= INTRADAY_EXTREME_POS:
        signals.append("開低走高(當日轉強)")
        score_adj += 8

    if close_pos >= INTRADAY_EXTREME_POS:
        signals.append("收在當日高檔")
        score_adj += 5
    elif close_pos <= 1 - INTRADAY_EXTREME_POS:
        signals.append("收在當日低檔")
        score_adj -= 5

    return signals, score_adj, metrics


def is_bad_shape(signals: list[str]) -> bool:
    """
    True when today's shape reads as a same-day reversal-down (開高走低 and/or
    收在當日低檔) — the pattern an `exclude_bad_shape` filter should drop.
    """
    return any(s.startswith("開高走低") or s == "收在當日低檔" for s in signals)
