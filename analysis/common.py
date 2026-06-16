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


def serialize_tech(d: dict, full: bool = False) -> dict:
    """Build the 技術指標 JSON block from a flat indicator dict."""
    block = {
        "KD(K/D)": f"{d.get('kd_k', 50):.1f}/{d.get('kd_d', 50):.1f}",
        "RSI": f"{d.get('rsi', 50):.1f}",
        "布林%B": f"{d.get('bb_pct', 0.5):.2f}",
        "MACD柱": f"{d.get('macd_hist', 0):.4f}",
        "均線乖離(MA5/MA20/MA60)": (
            f"{d.get('bias5', 0):+.1f}%/"
            f"{d.get('bias20', 0):+.1f}%/"
            f"{d.get('bias60', 0):+.1f}%"
        ),
        "量比": f"{d.get('vol_ratio', 1):.1f}x",
        "均線結構": d.get("ma_structure", "整理"),
        "相對大盤強度": d.get("rs_label", "—"),
        "MA20": d.get("ma20", 0),
        "MA60": d.get("ma60", 0),
    }
    if full:
        block["MA5"] = d.get("ma5", 0)
        block["MA10"] = d.get("ma10", 0)
        block["MA120"] = d.get("ma120", 0)
        block["MA240"] = d.get("ma240", 0)
    return block


def serialize_chip(d: dict) -> dict:
    """Build the 籌碼 JSON block from a flat chip dict."""
    return {
        "外資今日淨買(張)": f"{d.get('foreign_net_today', 0):+,.0f}",
        "外資5日淨買(張)": f"{d.get('foreign_net_5d', 0):+,.0f}",
        "外資連續買超(日)": int(d.get("foreign_consec_buy", 0)),
        "投信今日淨買(張)": f"{d.get('trust_net_today', 0):+,.0f}",
        "三大法人今日(張)": f"{d.get('big3_net_today', 0):+,.0f}",
        "融資餘額變化": f"{d.get('margin_change_pct', 0):+.1f}%",
        "融資使用率": f"{d.get('margin_util_rate', 0):.1f}%",
        "融券餘額變化": f"{d.get('short_change_pct', 0):+.1f}%",
        "券資比": f"{d.get('short_margin_ratio', 0):.1f}%",
    }


def serialize_fundamental(d: dict) -> dict:
    """Build the 基本面 JSON block from a flat fundamental dict (may be empty)."""
    if not d:
        return {}
    return {
        "最新月營收(億)": d.get("revenue_b", "—"),
        "月營收YoY%": f"{d.get('rev_yoy', 0):+.1f}%" if d.get("rev_yoy") is not None else "—",
        "月營收MoM%": f"{d.get('rev_mom', 0):+.1f}%" if d.get("rev_mom") is not None else "—",
        "營收月份": d.get("rev_month", "—"),
    }
