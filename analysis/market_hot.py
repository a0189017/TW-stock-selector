"""Compute today's hot sectors and hot individual stocks from full universe data."""
import pandas as pd

from analysis.common import exclude_etfs
from config import PRICE_MIN, HOT_STOCK_PRICE_MAX, HOT_STOCK_MIN_TRADE_VALUE


def _sector_groups(universe_df: pd.DataFrame, chip_df: pd.DataFrame) -> pd.DataFrame:
    """
    Shared groupby behind compute_hot_sectors (top_n display) and
    compute_sector_score_map (every industry, for per-stock factor scoring).
    Returns one row per industry with stock_count/up_count/down_count/
    avg_change_pct/total_trade_value/foreign_net/trust_net/big3_net/up_ratio/score
    (already filtered to stock_count >= 3, industry not blank/其他, ETFs excluded).
    """
    if universe_df.empty or "industry" not in universe_df.columns:
        return pd.DataFrame()

    df = exclude_etfs(universe_df.copy())
    df = df[df["industry"].str.strip() != ""]
    df = df[df["industry"] != "其他"]

    # Merge chip data if available
    if not chip_df.empty and "code" in chip_df.columns:
        chip = chip_df[["code", "foreign_net_today", "trust_net_today",
                        "big3_net_today"]].copy()
        df = df.merge(chip, on="code", how="left")
        for col in ("foreign_net_today", "trust_net_today", "big3_net_today"):
            df[col] = df[col].fillna(0)
    else:
        df["foreign_net_today"] = 0
        df["trust_net_today"] = 0
        df["big3_net_today"] = 0

    grouped = df.groupby("industry").agg(
        stock_count=("code", "count"),
        up_count=("change", lambda x: (x > 0).sum()),
        down_count=("change", lambda x: (x < 0).sum()),
        avg_change_pct=("change_pct", "mean"),
        total_trade_value=("trade_value", "sum"),
        foreign_net=("foreign_net_today", "sum"),
        trust_net=("trust_net_today", "sum"),
        big3_net=("big3_net_today", "sum"),
    ).reset_index()

    grouped = grouped[grouped["stock_count"] >= 3]
    grouped["up_ratio"] = grouped["up_count"] / grouped["stock_count"]

    # Composite score: weighted avg_change_pct + up_ratio + institutional signal
    grouped["score"] = (
        grouped["avg_change_pct"] * 0.4 +
        grouped["up_ratio"] * 5.0 +
        (grouped["big3_net"] > 0).astype(float) * 1.0
    )
    return grouped


def compute_sector_score_map(universe_df: pd.DataFrame, chip_df: pd.DataFrame) -> dict[str, float]:
    """
    {industry: raw score} for EVERY industry (not just the top_n compute_hot_sectors
    displays) — used by analysis/multi_factor.py so a candidate can look up its own
    industry's strength as a ranking factor, not just see the top-5 in isolation.
    """
    grouped = _sector_groups(universe_df, chip_df)
    if grouped.empty:
        return {}
    return dict(zip(grouped["industry"], grouped["score"]))


def compute_hot_sectors(universe_df: pd.DataFrame,
                        chip_df: pd.DataFrame,
                        top_n: int = 5) -> list[dict]:
    """
    Rank industries by: % rising stocks, avg change%, institutional net buying.
    Returns top_n sector dicts.
    """
    grouped = _sector_groups(universe_df, chip_df)
    if grouped.empty:
        return []

    top = grouped.nlargest(top_n, "score")

    result = []
    for _, row in top.iterrows():
        result.append({
            "產業": row["industry"],
            "成分股數": int(row["stock_count"]),
            "上漲家數": int(row["up_count"]),
            "下跌家數": int(row["down_count"]),
            "平均漲幅_%": round(float(row["avg_change_pct"]), 2),
            "上漲率_%": round(float(row["up_ratio"]) * 100, 1),
            "成交值_億": round(float(row["total_trade_value"]) / 1e8, 1),
            "外資淨買_張": round(float(row["foreign_net"])),
            "投信淨買_張": round(float(row["trust_net"])),
            "三大法人淨買_張": round(float(row["big3_net"])),
        })
    return result


def compute_hot_stocks(universe_df: pd.DataFrame,
                       chip_df: pd.DataFrame,
                       top_n: int = 10) -> list[dict]:
    """
    Return top hot individual stocks from the full universe (not just screened candidates).
    Two sub-lists: top gainers and top institutional buying.
    Combined into one deduped list, sorted by composite score.
    """
    if universe_df.empty:
        return []

    df = exclude_etfs(universe_df.copy())
    df = df[(df["close"] >= PRICE_MIN) & (df["close"] <= HOT_STOCK_PRICE_MAX)]
    df = df[df["trade_value"] >= HOT_STOCK_MIN_TRADE_VALUE]

    if not chip_df.empty and "code" in chip_df.columns:
        chip = chip_df[["code", "foreign_net_today", "trust_net_today",
                        "big3_net_today", "foreign_net_5d"]].copy()
        df = df.merge(chip, on="code", how="left")
        for col in ("foreign_net_today", "trust_net_today", "big3_net_today", "foreign_net_5d"):
            df[col] = df[col].fillna(0)
    else:
        for col in ("foreign_net_today", "trust_net_today", "big3_net_today", "foreign_net_5d"):
            df[col] = 0.0

    # Normalize metrics to 0-10 scale for composite scoring
    def _norm(series: pd.Series) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.0, index=series.index)
        return (series - mn) / (mx - mn) * 10

    df["score_change"] = _norm(df["change_pct"].clip(-20, 20))
    df["score_big3"] = _norm(df["big3_net_today"].clip(-5000, 5000))
    df["score_foreign5d"] = _norm(df["foreign_net_5d"].clip(-10000, 10000))
    df["score_vol"] = _norm(df["trade_value"].clip(0, 5e9))

    df["hot_score"] = (
        df["score_change"] * 0.35 +
        df["score_big3"] * 0.30 +
        df["score_foreign5d"] * 0.20 +
        df["score_vol"] * 0.15
    )

    top = df.nlargest(top_n, "hot_score")

    result = []
    for _, row in top.iterrows():
        result.append({
            "代號": row["code"],
            "名稱": row["name"],
            "產業": row.get("industry", "其他"),
            "收盤": round(float(row["close"]), 2),
            "漲跌_%": round(float(row["change_pct"]), 2),
            "成交值_億": round(float(row["trade_value"]) / 1e8, 2),
            "外資今日淨買_張": round(float(row["foreign_net_today"])),
            "投信今日淨買_張": round(float(row["trust_net_today"])),
            "三大法人今日淨買_張": round(float(row["big3_net_today"])),
            "外資5日淨買_張": round(float(row["foreign_net_5d"])),
        })
    return result
