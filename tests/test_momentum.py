"""Unit tests for the 飆股 pure-momentum scoring."""
import numpy as np
import pandas as pd

from analysis.momentum import consecutive_up_days, is_limit_up, score_momentum


def _df(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def test_consecutive_up_days_counts_trailing_streak():
    assert consecutive_up_days(_df([10, 9, 10, 11, 12])) == 3
    assert consecutive_up_days(_df([10, 11, 12, 11])) == 0   # last day is down
    assert consecutive_up_days(_df([5])) == 0                # too short


def test_consecutive_up_days_capped_by_lookback():
    closes = list(range(1, 30))  # strictly increasing
    assert consecutive_up_days(_df(closes), max_lookback=10) == 10


def test_is_limit_up():
    assert is_limit_up(9.9) is True
    assert is_limit_up(9.0) is True
    assert is_limit_up(8.9) is False
    assert is_limit_up(None) is False


def test_limit_up_runner_scores_high():
    ind = {"vol_ratio": 3.5, "ma_structure": "多頭排列", "bb_pct": 0.95}
    rs = {"rs20": 20}
    score, signals = score_momentum(ind, rs, change_pct=9.9, up_days=4)
    assert score >= 80
    assert any("漲停" in s for s in signals)
    assert any("爆量" in s for s in signals)
    assert any("連4紅" in s for s in signals)


def test_overbought_is_not_penalised():
    """A 飆股 screen must NOT dock points for overbought/extended, unlike score_stock."""
    ind = {"vol_ratio": 2.0, "ma_structure": "多頭排列", "bb_pct": 0.99, "rsi": 85, "bias20": 25}
    rs = {"rs20": 12}
    score, _ = score_momentum(ind, rs, change_pct=6.0, up_days=2)
    # High RSI / high 乖離 / upper-band are present but score stays strongly positive.
    assert score >= 40


def test_weak_stock_scores_low():
    ind = {"vol_ratio": 0.5, "ma_structure": "整理", "bb_pct": 0.3}
    score, _ = score_momentum(ind, {"rs20": -5}, change_pct=-1.0, up_days=0)
    assert score == 0


def test_none_rs_does_not_crash():
    ind = {"vol_ratio": 1.0, "ma_structure": "整理", "bb_pct": 0.5}
    score, _ = score_momentum(ind, None, change_pct=1.0, up_days=1)
    assert isinstance(score, int)
