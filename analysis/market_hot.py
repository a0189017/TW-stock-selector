"""Compute today's hot sectors and hot individual stocks from full universe data."""
import pandas as pd


def compute_hot_sectors(universe_df: pd.DataFrame,
                        chip_df: pd.DataFrame,
                        top_n: int = 5) -> list[dict]:
    """
    Rank industries by: % rising stocks, avg change%, institutional net buying.
    Returns top_n sector dicts.
    """
    if universe_df.empty or "industry" not in universe_df.columns:
        return []

    df = universe_df.copy()
    # Exclude ETFs / funds
    is_etf = (df["code"].str.startswith("00") |
              df["name"].str.contains("ETF|指數|基金|債券|REITs|REIT|期信", na=False, regex=True))
    df = df[~is_etf & df["code"].str.match(r"^\d{4}$")]
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

    top = grouped.nlargest(top_n, "score")

    result = []
    for _, row in top.iterrows():
        result.append({
            "industry": row["industry"],
            "stock_count": int(row["stock_count"]),
            "up_count": int(row["up_count"]),
            "down_count": int(row["down_count"]),
            "avg_change_pct": round(float(row["avg_change_pct"]), 2),
            "up_ratio_pct": round(float(row["up_ratio"]) * 100, 1),
            "trade_value_b": round(float(row["total_trade_value"]) / 1e8, 1),
            "foreign_net": round(float(row["foreign_net"]), 0),
            "trust_net": round(float(row["trust_net"]), 0),
            "big3_net": round(float(row["big3_net"]), 0),
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

    df = universe_df.copy()
    is_etf = (df["code"].str.startswith("00") |
              df["name"].str.contains("ETF|指數|基金|債券|REITs|REIT|期信", na=False, regex=True))
    df = df[~is_etf & df["code"].str.match(r"^\d{4}$")]
    df = df[(df["close"] >= 10) & (df["close"] <= 2000)]
    df = df[df["trade_value"] >= 5e7]  # 5,000萬以上成交額才算流動性夠

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
            "code": row["code"],
            "name": row["name"],
            "industry": row.get("industry", "其他"),
            "close": row["close"],
            "change_pct": round(float(row["change_pct"]), 2),
            "trade_value_b": round(float(row["trade_value"]) / 1e8, 2),
            "foreign_net_today": round(float(row["foreign_net_today"]), 0),
            "trust_net_today": round(float(row["trust_net_today"]), 0),
            "big3_net_today": round(float(row["big3_net_today"]), 0),
            "foreign_net_5d": round(float(row["foreign_net_5d"]), 0),
        })
    return result
