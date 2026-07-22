"""Unit tests for screener helpers."""
import pandas as pd

from analysis.screener import select_liquid_pool, stage2_chip
from config import VOLUME_MIN_VALUE_TWD, CHIP_SIGNAL_MIN


def _universe():
    return pd.DataFrame({
        "code":        ["2330", "2317", "0050", "1101", "9999"],
        "name":        ["台積電", "鴻海", "元大台灣50", "台泥", "怪股"],
        "close":       [1000.0, 200.0, 190.0, 40.0, 5.0],  # 9999 below PRICE_MIN(10)
        "trade_value": [9e10,   5e10,   8e10,  2e10,  9e10],
    })


def test_select_liquid_pool_ranks_by_trade_value_and_excludes_etf():
    pool = select_liquid_pool(_universe(), n=3)
    # 0050 is an ETF (code starts 00) → excluded; 9999 fails price floor → excluded.
    assert "0050" not in pool["code"].values
    assert "9999" not in pool["code"].values
    # Highest trade_value first among the survivors (2330 > 2317 > 1101).
    assert list(pool["code"]) == ["2330", "2317", "1101"]


def test_select_liquid_pool_respects_n():
    pool = select_liquid_pool(_universe(), n=1)
    assert len(pool) == 1
    assert pool.iloc[0]["code"] == "2330"


def test_select_liquid_pool_applies_min_trade_value():
    df = _universe()
    df.loc[df["code"] == "1101", "trade_value"] = VOLUME_MIN_VALUE_TWD - 1
    pool = select_liquid_pool(df, n=10)
    assert "1101" not in pool["code"].values


# ---------------------------------------------------------------------------
# stage2_chip
# ---------------------------------------------------------------------------

def _stage1_df():
    return pd.DataFrame({"code": ["2330", "2317"], "exchange": ["TWSE", "TWSE"]})


def test_stage2_chip_empty_chip_df_attaches_null_columns_no_filter():
    """No chip data at all: honest nulls, and Stage 2 must not silently drop
    every candidate (the bug this schema was designed to prevent)."""
    result = stage2_chip(_stage1_df(), pd.DataFrame())
    assert len(result) == 2   # unfiltered — chip signals can't be evaluated
    assert result["foreign_net_today"].isna().all()
    assert "chip_signals" not in result.columns  # never computed without chip data


def test_stage2_chip_filters_by_signal_count():
    stage1 = _stage1_df()
    # 2330: 3 bullish signals (foreign/trust/big3 all positive) -> passes.
    # 2317: 0 signals -> filtered out (CHIP_SIGNAL_MIN=2).
    chip = pd.DataFrame({
        "code": ["2330", "2317"],
        "foreign_net_today": [100, -100],
        "trust_net_today": [50, -50],
        "big3_net_today": [150, -150],
    })
    result = stage2_chip(stage1, chip)
    assert list(result["code"]) == ["2330"]
    assert result.iloc[0]["chip_signals"] >= CHIP_SIGNAL_MIN


def test_stage2_chip_apply_filter_false_keeps_all_but_still_scores():
    stage1 = _stage1_df()
    chip = pd.DataFrame({
        "code": ["2330", "2317"],
        "foreign_net_today": [100, -100],
        "trust_net_today": [50, -50],
        "big3_net_today": [150, -150],
    })
    result = stage2_chip(stage1, chip, apply_filter=False)
    assert len(result) == 2
    assert "chip_signals" in result.columns


def test_stage2_chip_missing_stock_defaults_to_zero_not_null():
    """A stock present in stage1 but absent from chip_df (e.g. TPEX 3insti gap)
    gets neutral 0 signals via fillna — distinct from the whole-source-missing
    case above, which uses None."""
    stage1 = _stage1_df()
    chip = pd.DataFrame({
        "code": ["2330"],   # 2317 not present in chip data at all
        "foreign_net_today": [100],
        "trust_net_today": [50],
        "big3_net_today": [150],
    })
    result = stage2_chip(stage1, chip, apply_filter=False)
    row_2317 = result[result["code"] == "2317"].iloc[0]
    assert row_2317["foreign_net_today"] == 0
    assert row_2317["chip_signals"] == 0
