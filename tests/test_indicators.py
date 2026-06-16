"""Unit tests for technical indicators and scoring."""
import numpy as np
import pandas as pd
import pytest

from analysis.indicators import (
    compute_kd, compute_macd, compute_mas, compute_rsi, compute_bollinger,
    compute_bias, compute_volume_ratio, add_all_indicators,
    compute_relative_strength, score_stock,
)


def _ohlcv(closes, volumes=None):
    """Build an OHLCV DataFrame from a close-price array."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    vol = np.full(n, 1000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame({
        "Open": closes,
        "High": closes * 1.01,
        "Low": closes * 0.99,
        "Close": closes,
        "Volume": vol,
    }, index=idx)


def test_compute_mas_matches_rolling_mean():
    df = _ohlcv(np.arange(1, 101))
    df = compute_mas(df)
    assert df["MA5"].iloc[-1] == pytest.approx(np.mean(np.arange(96, 101)))
    # not enough data → NaN
    assert np.isnan(df["MA240"].iloc[-1])


def test_compute_rsi_uptrend_is_high():
    # Mostly-up with small pullbacks (a strictly monotonic series has zero losses
    # → RSI is NaN by definition, which isn't a realistic price path).
    rng = np.random.default_rng(7)
    closes = 10 + np.cumsum(np.abs(rng.normal(0.5, 0.3, 100)) + rng.normal(0, 0.1, 100))
    rsi = compute_rsi(_ohlcv(closes))
    assert rsi.iloc[-1] > 60


def test_compute_rsi_downtrend_is_low():
    df = _ohlcv(np.linspace(50, 10, 100))
    rsi = compute_rsi(df)
    assert rsi.iloc[-1] < 5


def test_compute_kd_bounded_0_100():
    rng = np.random.default_rng(0)
    closes = 50 + np.cumsum(rng.normal(0, 1, 200))
    df = _ohlcv(np.abs(closes) + 10)
    k, d = compute_kd(df)
    valid = k.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_compute_macd_hist_is_macd_minus_signal():
    df = _ohlcv(np.linspace(10, 60, 120))
    macd, sig, hist = compute_macd(df)
    assert hist.iloc[-1] == pytest.approx((macd - sig).iloc[-1])


def test_bollinger_mid_is_sma_and_pct_b_in_range():
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(rng.normal(0, 0.5, 120))
    df = _ohlcv(closes)
    df = compute_bollinger(df)
    assert df["BB_mid"].iloc[-1] == pytest.approx(df["Close"].rolling(20).mean().iloc[-1])
    # %B usually in [0,1] for normal data; allow small overshoot
    assert -0.5 < df["BB_pct"].iloc[-1] < 1.5


def test_bias_zero_on_flat_series():
    df = _ohlcv(np.full(100, 25.0))
    df = compute_mas(df)
    df = compute_bias(df)
    assert df["Bias20"].iloc[-1] == pytest.approx(0.0)


def test_volume_ratio_detects_surge():
    vols = np.concatenate([np.full(50, 1000.0), [5000.0]])
    df = _ohlcv(np.full(51, 30.0), volumes=vols)
    df = compute_volume_ratio(df)
    assert df["VolRatio"].iloc[-1] == pytest.approx(5.0)


def test_relative_strength_positive_when_outperforming():
    n = 120
    stock = _ohlcv(np.linspace(10, 20, n))      # +100%
    bench = _ohlcv(np.linspace(10, 11, n))      # +10%
    rs = compute_relative_strength(stock, bench, windows=(20, 60))
    assert rs["rs20"] > 0
    assert "強" in rs["rs_label"]


def test_relative_strength_empty_without_benchmark():
    stock = _ohlcv(np.linspace(10, 20, 120))
    assert compute_relative_strength(stock, None) == {}


def _ind_frame(last: dict, prev: dict | None = None):
    """Build a >=20-row indicator DataFrame with explicit last/prev values.

    Tests the scoring rules directly instead of via fragile synthetic price paths.
    """
    cols = ["Close", "K", "D", "MACD_hist", "MA5", "MA10", "MA20", "MA60",
            "MA120", "MA240", "Bias20", "VolRatio", "RSI", "BB_pct", "BB_width"]
    df = pd.DataFrame(np.nan, index=range(25), columns=cols)
    for c, v in (prev or {}).items():
        df.loc[23, c] = v
    for c, v in last.items():
        df.loc[24, c] = v
    return df


def test_score_stock_rewards_oversold_golden_cross():
    # KD deep-oversold + golden cross is the scorer's strongest reversal signal.
    oversold = _ind_frame(
        last={"K": 18, "D": 16, "Close": 20},
        prev={"K": 12, "D": 17},   # prev K<D, now K>=D → golden cross
    )
    neutral = _ind_frame(last={"K": 50, "D": 50, "Close": 20}, prev={"K": 50, "D": 50})
    os_score, os_signals = score_stock(oversold)
    nt_score, _ = score_stock(neutral)
    assert os_score > nt_score
    assert any("黃金交叉" in s for s in os_signals)


def test_score_stock_penalizes_overbought():
    overbought = _ind_frame(last={"RSI": 80, "Bias20": 20, "BB_pct": 0.95, "Close": 20})
    score, signals = score_stock(overbought)
    # RSI>70 (-8) + bias>15 (-10) + BB upper (-5) → clamped at 0
    assert score == 0
    assert any("乖離過大" in s for s in signals)


def test_score_stock_short_series_returns_zero():
    df = add_all_indicators(_ohlcv(np.arange(1, 11)))
    assert score_stock(df) == (0, [])


def test_score_stock_revenue_growth_adds_points():
    df = add_all_indicators(_ohlcv(np.linspace(10, 20, 120)))
    base, _ = score_stock(df)
    boosted, signals = score_stock(df, fundamental={"rev_yoy": 50})
    assert boosted > base
    assert any("營收" in s for s in signals)
