"""Unit tests for shared helpers (the 空頭排列 fix + canonical output schema)."""
import pandas as pd

from analysis.common import (
    exclude_etfs, ma_structure_label, serialize_tech, serialize_chip,
    serialize_fundamental, TECH_KEYS, CHIP_KEYS, FUNDAMENTAL_KEYS,
)


def test_exclude_etfs_drops_00_codes_and_fund_names():
    df = pd.DataFrame({
        "code": ["2330", "0050", "1234", "2454"],
        "name": ["台積電", "元大台灣50", "某某ETF基金", "聯發科"],
    })
    out = exclude_etfs(df)
    assert set(out["code"]) == {"2330", "2454"}


def test_exclude_etfs_drops_non_4digit():
    df = pd.DataFrame({"code": ["2330", "00878", "123"], "name": ["a", "b", "c"]})
    out = exclude_etfs(df)
    assert list(out["code"]) == ["2330"]


def test_ma_structure_bullish():
    assert ma_structure_label(30, 28, 25, 20) == "多頭排列"


def test_ma_structure_short_bull():
    assert ma_structure_label(26, 24, 25, 30) == "短多"


def test_ma_structure_bearish_is_reachable():
    # Regression test for the old dead branch `ma5 < ma20 < 0` that never fired.
    assert ma_structure_label(20, 22, 25, 30) == "空頭排列"


def test_ma_structure_consolidation():
    assert ma_structure_label(25, 25, 25, 25) == "整理"


def test_serialize_tech_raw_values_and_keys():
    block = serialize_tech({"kd_k": 80.0, "kd_d": 70.0, "rs_label": "明顯強於大盤", "rs20": 5.2})
    # canonical key set, raw numeric values (no formatted strings)
    assert set(block) == set(TECH_KEYS)
    assert block["KD_K"] == 80.0 and block["KD_D"] == 70.0
    assert block["相對大盤強度"] == "明顯強於大盤"
    assert block["RS_20日_%"] == 5.2


def test_serialize_tech_full_adds_long_mas():
    block = serialize_tech({"ma5": 1.0, "ma240": 2.0}, full=True)
    assert "MA5" in block and "MA240" in block


def test_serialize_tech_missing_is_null():
    block = serialize_tech({})
    assert block["KD_K"] is None
    assert block["RS_20日_%"] is None


def test_serialize_chip_raw_values():
    block = serialize_chip({"foreign_net_today": 1234.0, "trust_net_today": -50.0,
                            "foreign_consec_buy": 3, "margin_change_pct": 5.0})
    assert set(block) == set(CHIP_KEYS)
    assert block["外資今日淨買_張"] == 1234        # rounded int, not "+1,234"
    assert block["投信今日淨買_張"] == -50
    assert block["外資連續買超_日"] == 3
    assert block["融資餘額變化_%"] == 5.0


def test_serialize_chip_missing_is_null():
    block = serialize_chip({"foreign_net_today": 100})
    assert block["外資今日淨買_張"] == 100
    assert block["券資比_%"] is None              # absent → null, not 0


def test_serialize_fundamental_empty_returns_empty():
    assert serialize_fundamental({}) == {}


def test_serialize_fundamental_raw_values():
    block = serialize_fundamental({"rev_yoy": 25.0, "rev_mom": -3.0,
                                   "rev_month": "2026-05", "revenue_b": 12.3})
    assert set(block) == set(FUNDAMENTAL_KEYS)
    assert block["月營收YoY_%"] == 25.0
    assert block["月營收MoM_%"] == -3.0
    assert block["營收月份"] == "2026-05"


def test_serialize_fundamental_partial_missing_is_null():
    block = serialize_fundamental({"revenue_b": 12.3})
    assert block["月營收YoY_%"] is None
