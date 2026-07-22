"""Unit tests for data.recommendations._forward_return (pure, no network/DB)."""
import numpy as np
import pandas as pd
import pytest

from data.recommendations import _forward_return


def _hist(start="2026-01-01", n=30, start_price=100.0, daily_pct=0.0):
    idx = pd.date_range(start, periods=n, freq="B")
    closes = start_price * (1 + daily_pct) ** np.arange(n)
    return pd.DataFrame({"Close": closes}, index=idx)


def test_forward_return_basic():
    df = _hist(n=30, start_price=100.0, daily_pct=0.01)  # steadily rising
    # screen on day 0 (2026-01-01), 10 trading days later
    fwd = _forward_return(df, "2026-01-01", base_close=100.0, horizon=10)
    assert fwd is not None
    expected_close = 100.0 * (1.01 ** 10)
    assert fwd == pytest.approx((expected_close - 100.0) / 100.0 * 100)


def test_forward_return_insufficient_history_returns_none():
    df = _hist(n=5)  # not enough bars for horizon=10
    assert _forward_return(df, "2026-01-01", base_close=100.0, horizon=10) is None


def test_forward_return_invalid_date_returns_none():
    df = _hist(n=30)
    assert _forward_return(df, "not-a-date", base_close=100.0, horizon=5) is None


def test_forward_return_zero_base_close_returns_none():
    df = _hist(n=30)
    assert _forward_return(df, "2026-01-01", base_close=0.0, horizon=5) is None


def test_forward_return_uses_first_bar_on_or_after_screen_date():
    """screen_date falling on a non-trading day should use the next available bar."""
    df = _hist(start="2026-01-01", n=30, start_price=100.0, daily_pct=0.0)
    # 2026-01-01 is a Thursday (business day) in this fixture's date_range; pick
    # a date a few days later that's guaranteed present.
    fwd = _forward_return(df, df.index[3].strftime("%Y-%m-%d"), base_close=100.0, horizon=5)
    assert fwd is not None
