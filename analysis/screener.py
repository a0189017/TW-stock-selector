"""3-stage screening funnel: ~2,000 stocks → 80 Claude candidates."""
import pandas as pd
import numpy as np
from config import (VOLUME_MIN_VALUE_TWD, PRICE_MIN, PRICE_MAX,
                    CHIP_SIGNAL_MIN, STAGE3_MIN_SCORE, STAGE3_TOP_N)
from analysis.indicators import add_all_indicators, score_stock


# ---------------------------------------------------------------------------
# Stage 1: Liquidity filter (instant, from today's snapshot)
# ---------------------------------------------------------------------------

def stage1_liquidity(universe_df: pd.DataFrame,
                     exclusion_codes: set[str] | None = None) -> pd.DataFrame:
    """
    Filter by trade value, price range, valid code, and exclusion list.
    Returns filtered DataFrame.
    """
    df = universe_df.copy()

    # Numeric code, 4 digits
    df = df[df["code"].str.match(r"^\d{4}$")]

    # Exclude ETFs (codes 00xx, or names containing ETF/基金)
    is_etf = (df["code"].str.startswith("00") |
              df["name"].str.contains("ETF|指數|基金|債券|REITs|REIT|期信", na=False, regex=True))
    df = df[~is_etf]

    # Price range
    df = df[(df["close"] >= PRICE_MIN) & (df["close"] <= PRICE_MAX)]

    # Minimum daily trade value
    df = df[df["trade_value"] >= VOLUME_MIN_VALUE_TWD]

    # Exclude disposition/warning stocks
    if exclusion_codes:
        df = df[~df["code"].isin(exclusion_codes)]

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stage 2: Chip signal filter (instant, using today's chip data)
# ---------------------------------------------------------------------------

def stage2_chip(stage1_df: pd.DataFrame, chip_df: pd.DataFrame) -> pd.DataFrame:
    """
    Require a stock to show at least CHIP_SIGNAL_MIN bullish chip signals.
    Returns filtered DataFrame with chip columns attached.
    """
    if chip_df.empty:
        return stage1_df

    chip = chip_df.set_index("code") if "code" in chip_df.columns else chip_df

    # Attach chip data
    df = stage1_df.copy()
    for col in ("foreign_net_today", "trust_net_today", "big3_net_today",
                "foreign_net_5d", "trust_net_5d",
                "margin_today", "margin_prev", "margin_change_pct", "margin_util_rate"):
        df[col] = df["code"].map(chip[col] if col in chip.columns else {}).fillna(0)

    def chip_signals(row) -> int:
        signals = 0
        if row.get("foreign_net_today", 0) > 0:
            signals += 1
        if row.get("trust_net_today", 0) > 0:
            signals += 1
        if row.get("big3_net_today", 0) > 0:
            signals += 1
        if row.get("margin_change_pct", 0) < 0:  # margin declining = bullish
            signals += 1
        if row.get("foreign_net_5d", 0) > 0:
            signals += 1
        return signals

    df["chip_signals"] = df.apply(chip_signals, axis=1)
    df = df[df["chip_signals"] >= CHIP_SIGNAL_MIN]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stage 3: Technical indicator scoring (after yfinance download)
# ---------------------------------------------------------------------------

def stage3_technical(stage2_df: pd.DataFrame,
                     history: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Score each candidate on technical indicators.
    Returns top STAGE3_TOP_N stocks with score >= STAGE3_MIN_SCORE.
    """
    rows = []
    for _, stock in stage2_df.iterrows():
        code = stock["code"]
        exchange = stock["exchange"]
        suffix = ".TW" if exchange == "TWSE" else ".TWO"
        ticker = f"{code}{suffix}"

        df_hist = history.get(ticker)
        if df_hist is None or len(df_hist) < 60:
            continue

        df_ind = add_all_indicators(df_hist)
        tech_score, tech_signals = score_stock(df_ind)

        if tech_score < STAGE3_MIN_SCORE:
            continue

        last = df_ind.iloc[-1]
        prev = df_ind.iloc[-2] if len(df_ind) > 1 else last

        def v(col, default=0.0):
            val = last.get(col, default)
            return float(val) if pd.notna(val) else default

        # Build MA structure label
        close = v("Close")
        ma5, ma10, ma20, ma60 = v("MA5"), v("MA10"), v("MA20"), v("MA60")
        if ma5 > ma10 > ma20 > ma60 > 0:
            ma_structure = "多頭排列"
        elif ma5 > ma20 > 0:
            ma_structure = "短多"
        elif ma5 < ma20 < 0:
            ma_structure = "空頭排列"
        else:
            ma_structure = "整理"

        row = stock.to_dict()
        row.update({
            "tech_score": tech_score,
            "tech_signals": tech_signals,
            "kd_k": round(v("K"), 1),
            "kd_d": round(v("D"), 1),
            "macd_hist": round(v("MACD_hist"), 4),
            "bias5": round(v("Bias5"), 2) if not pd.isna(v("Bias5")) else 0.0,
            "bias20": round(v("Bias20"), 2) if not pd.isna(v("Bias20")) else 0.0,
            "bias60": round(v("Bias60"), 2) if not pd.isna(v("Bias60")) else 0.0,
            "vol_ratio": round(v("VolRatio"), 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma_structure": ma_structure,
        })
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result = result.sort_values("tech_score", ascending=False)
    return result.head(STAGE3_TOP_N).reset_index(drop=True)
