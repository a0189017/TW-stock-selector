"""Unit tests for shared helpers (the 空頭排列 fix lives here)."""
import pandas as pd

from analysis.common import (
    exclude_etfs, ma_structure_label, serialize_tech, serialize_chip,
    serialize_fundamental,
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


def test_serialize_tech_includes_rs_label():
    block = serialize_tech({"kd_k": 80, "kd_d": 70, "rs_label": "明顯強於大盤"})
    assert block["相對大盤強度"] == "明顯強於大盤"
    assert block["KD(K/D)"] == "80.0/70.0"


def test_serialize_chip_formats_signs():
    block = serialize_chip({"foreign_net_today": 1234, "trust_net_today": -50})
    assert block["外資今日淨買(張)"] == "+1,234"
    assert block["投信今日淨買(張)"] == "-50"


def test_serialize_fundamental_empty_returns_empty():
    assert serialize_fundamental({}) == {}


def test_serialize_fundamental_formats_yoy():
    block = serialize_fundamental({"rev_yoy": 25.0, "rev_mom": -3.0, "rev_month": "2026-05", "revenue_b": 12.3})
    assert block["月營收YoY%"] == "+25.0%"
    assert block["月營收MoM%"] == "-3.0%"
