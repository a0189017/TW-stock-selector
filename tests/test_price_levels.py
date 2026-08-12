"""Tests for analysis/price_levels.py::compute_price_levels — the shared
entry/take-profit/stop-loss calculator used by both portfolio.py (持股健檢)
and analysis/screener.py::stage3_technical (候選股 建議價位).
"""
from analysis.price_levels import compute_price_levels


def test_missing_close_returns_empty():
    assert compute_price_levels(close=0, ma5=10, ma20=10, ma60=10, atr=1, bias20=0) == {}
    assert compute_price_levels(close=None, ma5=10, ma20=10, ma60=10, atr=1, bias20=0) == {}


def test_healthy_stock_uses_ma20_support_and_no_chase_warning():
    result = compute_price_levels(close=100, ma5=99, ma20=97, ma60=90, atr=2, bias20=3.0)
    assert result["建議買入區間"][0] <= 100 <= result["建議買入區間"][1] or result["建議買入區間"][1] == 100
    assert result["停損"] < 100
    assert result["停利目標"] > 100
    assert "追高" not in result["依據"]


def test_extended_stock_switches_to_ma5_support_and_wait_advice():
    """乖離 > BIAS_EXTENDED_PCT (15%) should lean on MA5, not MA20/60, and
    advise waiting for a pullback instead of a chase-buy range."""
    result = compute_price_levels(close=120, ma5=115, ma20=100, ma60=95, atr=3, bias20=20.0)
    assert "等回測" in result["依據"]
    # entry band anchored near MA5 (115), not MA20 (100)
    assert 110 <= result["建議買入區間"][1] <= 118


def test_stop_loss_never_placed_above_current_price():
    # A tiny ATR combined with a support MA just barely below price shouldn't
    # push the stop above the current close.
    result = compute_price_levels(close=50, ma5=49.9, ma20=49.8, ma60=49.5, atr=0.01, bias20=1.0)
    assert result["停損"] <= 50


def test_missing_atr_falls_back_to_pct_of_close():
    with_atr = compute_price_levels(close=100, ma5=98, ma20=95, ma60=90, atr=2.0, bias20=2.0)
    without_atr = compute_price_levels(close=100, ma5=98, ma20=95, ma60=90, atr=None, bias20=2.0)
    assert without_atr != {}
    assert without_atr["停利目標"] > 100


def test_missing_ma60_falls_back_to_ma20_then_close():
    # No MA20/60 at all — support anchor degrades to an approximate value,
    # must not crash and must still return a usable band.
    result = compute_price_levels(close=80, ma5=0, ma20=0, ma60=0, atr=1.5, bias20=0)
    assert result["建議買入區間"][0] > 0
    assert result["停損"] < 80


def test_overbought_trims_target_and_notes_risk():
    result = compute_price_levels(close=100, ma5=98, ma20=96, ma60=90, atr=2.0, bias20=4.0, rsi=75)
    baseline = compute_price_levels(close=100, ma5=98, ma20=96, ma60=90, atr=2.0, bias20=4.0, rsi=50)
    assert result["停利目標"] < baseline["停利目標"]
    assert "超買" in result["依據"]
