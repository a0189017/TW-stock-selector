"""Unit tests for analysis.market_hot ranking (pure DataFrame in/out)."""
import pandas as pd

from analysis.market_hot import compute_hot_sectors, compute_hot_stocks
from config import HOT_STOCK_MIN_TRADE_VALUE


def _universe_for_sectors():
    return pd.DataFrame({
        "code":        ["2330", "2331", "2332", "2600", "2601", "0050", "9999"],
        "name":        ["台積電", "測試2", "測試3", "長榮", "陽明", "元大台灣50", "怪股"],
        "industry":    ["半導體業", "半導體業", "半導體業", "航運業", "航運業", "半導體業", "其他"],
        "close":       [1000.0, 100.0, 50.0, 200.0, 60.0, 100.0, 20.0],
        "change":      [5.0, 2.0, -1.0, 3.0, 1.0, 5.0, 1.0],
        "change_pct":  [5.0, 2.0, -1.0, 3.0, 1.0, 5.0, 5.0],
        "trade_value": [1e9, 1e8, 1e8, 1e8, 1e8, 1e8, 1e8],
    })


def test_compute_hot_sectors_excludes_thin_and_other_and_etf():
    result = compute_hot_sectors(_universe_for_sectors(), pd.DataFrame(), top_n=5)
    sectors = {r["產業"] for r in result}
    # 航運業 has only 2 stocks (< 3) -> excluded; 其他 always excluded; ETF (0050) dropped
    # before grouping so it can't inflate 半導體業's count.
    assert "航運業" not in sectors
    assert "其他" not in sectors
    assert "半導體業" in sectors
    sector = next(r for r in result if r["產業"] == "半導體業")
    assert sector["成分股數"] == 3   # 2330/2331/2332 only — 0050 excluded as ETF
    assert sector["上漲家數"] == 2
    assert sector["下跌家數"] == 1


def test_compute_hot_sectors_empty_inputs():
    assert compute_hot_sectors(pd.DataFrame(), pd.DataFrame()) == []


def test_compute_hot_sectors_chip_bonus_affects_score():
    universe = _universe_for_sectors()
    chip_bullish = pd.DataFrame({
        "code": ["2330", "2331", "2332"],
        "foreign_net_today": [100, 100, 100],
        "trust_net_today": [0, 0, 0],
        "big3_net_today": [100, 100, 100],
    })
    with_chip = compute_hot_sectors(universe, chip_bullish, top_n=5)
    without_chip = compute_hot_sectors(universe, pd.DataFrame(), top_n=5)
    score_with = next(r for r in with_chip if r["產業"] == "半導體業")["三大法人淨買_張"]
    score_without = next(r for r in without_chip if r["產業"] == "半導體業")["三大法人淨買_張"]
    assert score_with > 0
    assert score_without == 0


def _universe_for_stocks():
    ok_value = HOT_STOCK_MIN_TRADE_VALUE * 2
    return pd.DataFrame({
        "code":        ["2330", "9903", "0050", "1234"],
        "name":        ["台積電", "低流動性", "元大台灣50", "低價股"],
        "industry":    ["半導體業", "其他", "半導體業", "其他"],
        "close":       [1000.0, 500.0, 100.0, 5.0],           # 1234 below PRICE_MIN(10)
        "change":      [10.0, 1.0, 1.0, 1.0],
        "change_pct":  [15.0, 1.0, 1.0, 1.0],
        "trade_value": [ok_value, HOT_STOCK_MIN_TRADE_VALUE / 2, ok_value, ok_value],
    })


def test_compute_hot_stocks_applies_liquidity_filters():
    """Regression guard for the market_hot/config threshold unification (P5)."""
    result = compute_hot_stocks(_universe_for_stocks(), pd.DataFrame(), top_n=10)
    codes = {r["代號"] for r in result}
    assert "9903" not in codes    # below HOT_STOCK_MIN_TRADE_VALUE
    assert "0050" not in codes    # ETF excluded
    assert "1234" not in codes    # below PRICE_MIN
    assert "2330" in codes


def test_compute_hot_stocks_ranks_by_composite_score():
    ok_value = HOT_STOCK_MIN_TRADE_VALUE * 2
    universe = pd.DataFrame({
        "code":        ["2330", "2317"],
        "name":        ["台積電", "鴻海"],
        "industry":    ["半導體業", "電子"],
        "close":       [1000.0, 200.0],
        "change":      [10.0, 1.0],
        "change_pct":  [15.0, 1.0],     # 2330 clearly stronger momentum
        "trade_value": [ok_value, ok_value],
    })
    result = compute_hot_stocks(universe, pd.DataFrame(), top_n=10)
    assert [r["代號"] for r in result] == ["2330", "2317"]


def test_compute_hot_stocks_empty_universe():
    assert compute_hot_stocks(pd.DataFrame(), pd.DataFrame()) == []
