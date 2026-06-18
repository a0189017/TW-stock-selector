"""Shared helpers used across screening, hot-list, portfolio and MCP output.

Centralises three things that used to be copy-pasted in 4-5 places:
  - ETF / fund exclusion
  - MA-structure label (多頭排列 / 短多 / 空頭排列 / 整理)
  - flat indicator extraction + the tech / chip JSON blocks emitted to Claude
"""
import numpy as np
import pandas as pd

# Codes starting 00 are ETFs; names matching these are funds/bonds/REITs.
_ETF_NAME_PATTERN = "ETF|指數|基金|債券|REITs|REIT|期信"


def exclude_etfs(df: pd.DataFrame) -> pd.DataFrame:
    """Drop ETFs/funds and keep only 4-digit ordinary stock codes."""
    is_etf = (df["code"].str.startswith("00") |
              df["name"].str.contains(_ETF_NAME_PATTERN, na=False, regex=True))
    return df[~is_etf & df["code"].str.match(r"^\d{4}$")]


def ma_structure_label(ma5: float, ma10: float, ma20: float, ma60: float) -> str:
    """Classify moving-average alignment. All inputs are prices (> 0)."""
    if ma5 > ma10 > ma20 > ma60 > 0:
        return "多頭排列"
    if ma5 > ma20 > 0:
        return "短多"
    if ma5 < ma20 < ma60:        # 真正的空頭排列（不是 < 0）
        return "空頭排列"
    return "整理"


def extract_indicators(df_ind: pd.DataFrame) -> dict:
    """
    Pull the latest-day indicator values out of an indicator DataFrame into the
    flat dict shape used everywhere downstream (kd_k, rsi, bias20, ma_structure…).
    Does NOT include the technical score — call score_stock separately.
    """
    last = df_ind.iloc[-1]

    def v(col, default=0.0):
        val = last.get(col, default)
        return float(val) if pd.notna(val) else default

    ma5, ma10, ma20, ma60 = v("MA5"), v("MA10"), v("MA20"), v("MA60")
    return {
        "kd_k": round(v("K"), 1),
        "kd_d": round(v("D"), 1),
        "rsi": round(v("RSI", 50), 1),
        "bb_pct": round(v("BB_pct", 0.5), 3),
        "macd_hist": round(v("MACD_hist"), 4),
        "bias5": round(v("Bias5"), 2),
        "bias20": round(v("Bias20"), 2),
        "bias60": round(v("Bias60"), 2),
        "vol_ratio": round(v("VolRatio"), 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "ma120": round(v("MA120"), 2),
        "ma240": round(v("MA240"), 2),
        "ma_structure": ma_structure_label(ma5, ma10, ma20, ma60),
        "yf_close": round(v("Close"), 2),
    }


# Canonical output-format version. See docs/OUTPUT_SCHEMA.md for the full spec.
# Bump when key names / value semantics of any serialize_* block change.
SCHEMA_VERSION = "1.0"


def _r0(x):
    """Round to nearest integer (張/口/家數). Pass through None/non-numeric."""
    return round(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def _r2(x):
    """Round to 2 decimals (%/價). Pass through None/non-numeric."""
    return round(x, 2) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


# Canonical key sets — used by tests to enforce the schema contract.
TECH_KEYS = (
    "KD_K", "KD_D", "RSI", "布林%B", "MACD柱",
    "乖離_MA5_%", "乖離_MA20_%", "乖離_MA60_%",
    "量比", "均線結構", "相對大盤強度", "RS_20日_%", "MA20", "MA60",
)
CHIP_KEYS = (
    "外資今日淨買_張", "外資5日淨買_張", "外資連續買超_日",
    "投信今日淨買_張", "三大法人今日淨買_張",
    "融資餘額變化_%", "融資使用率_%", "融券餘額變化_%", "券資比_%",
)
FUNDAMENTAL_KEYS = ("最新月營收_億", "月營收YoY_%", "月營收MoM_%", "營收月份")


def serialize_tech(d: dict, full: bool = False) -> dict:
    """
    技術指標 block — RAW numeric values under canonical Chinese keys (units in key
    names). The model formats for display; missing numerics are null. Labels
    (均線結構 / 相對大盤強度) stay as strings.
    """
    block = {
        "KD_K": _r2(d.get("kd_k")),
        "KD_D": _r2(d.get("kd_d")),
        "RSI": _r2(d.get("rsi")),
        "布林%B": _r2(d.get("bb_pct")),
        "MACD柱": d.get("macd_hist"),
        "乖離_MA5_%": _r2(d.get("bias5")),
        "乖離_MA20_%": _r2(d.get("bias20")),
        "乖離_MA60_%": _r2(d.get("bias60")),
        "量比": _r2(d.get("vol_ratio")),
        "均線結構": d.get("ma_structure"),
        "相對大盤強度": d.get("rs_label"),
        "RS_20日_%": _r2(d.get("rs20")),
        "MA20": _r2(d.get("ma20")),
        "MA60": _r2(d.get("ma60")),
    }
    if full:
        block["MA5"] = _r2(d.get("ma5"))
        block["MA10"] = _r2(d.get("ma10"))
        block["MA120"] = _r2(d.get("ma120"))
        block["MA240"] = _r2(d.get("ma240"))
    return block


def serialize_chip(d: dict) -> dict:
    """籌碼 block — RAW values (張 rounded to int, % to 2dp). Missing → null."""
    return {
        "外資今日淨買_張": _r0(d.get("foreign_net_today")),
        "外資5日淨買_張": _r0(d.get("foreign_net_5d")),
        "外資連續買超_日": _r0(d.get("foreign_consec_buy")),
        "投信今日淨買_張": _r0(d.get("trust_net_today")),
        "三大法人今日淨買_張": _r0(d.get("big3_net_today")),
        "融資餘額變化_%": _r2(d.get("margin_change_pct")),
        "融資使用率_%": _r2(d.get("margin_util_rate")),
        "融券餘額變化_%": _r2(d.get("short_change_pct")),
        "券資比_%": _r2(d.get("short_margin_ratio")),
    }


def serialize_fundamental(d: dict) -> dict:
    """
    基本面 block — RAW values. Returns {} when there is no fundamental data at all
    (all fields null) — works whether called with the fund sub-dict or a full stock
    row that merely carries null revenue_* keys. Partial data → block with nulls.
    """
    block = {
        "最新月營收_億": _r2(d.get("revenue_b")),
        "月營收YoY_%": _r2(d.get("rev_yoy")),
        "月營收MoM_%": _r2(d.get("rev_mom")),
        "營收月份": d.get("rev_month"),
    }
    if all(v is None for v in block.values()):
        return {}
    return block
