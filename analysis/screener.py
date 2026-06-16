"""3-stage screening funnel: ~2,000 stocks → 80 Claude candidates."""
import pandas as pd

from config import (VOLUME_MIN_VALUE_TWD, PRICE_MIN, PRICE_MAX,
                    CHIP_SIGNAL_MIN, STAGE3_MIN_SCORE, STAGE3_TOP_N)
from analysis.common import exclude_etfs, extract_indicators
from analysis.indicators import add_all_indicators, score_stock, compute_relative_strength


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

    # Drop ETFs / funds, keep 4-digit ordinary codes
    df = exclude_etfs(df)

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
    chip_cols = (
        "foreign_net_today", "trust_net_today", "big3_net_today",
        "foreign_net_5d", "trust_net_5d",
        "margin_today", "margin_prev", "margin_change_pct", "margin_util_rate",
        "short_today", "short_change_pct", "short_margin_ratio",
        "foreign_consec_buy", "foreign_consec_sell",
    )
    for col in chip_cols:
        df[col] = df["code"].map(chip[col] if col in chip.columns else {}).fillna(0)

    def chip_signals(row) -> int:
        signals = 0
        if row.get("foreign_net_today", 0) > 0:
            signals += 1
        if row.get("trust_net_today", 0) > 0:
            signals += 1
        if row.get("big3_net_today", 0) > 0:
            signals += 1
        if row.get("margin_change_pct", 0) < 0:       # 融資下降 = 籌碼健康
            signals += 1
        if row.get("foreign_net_5d", 0) > 0:
            signals += 1
        if row.get("foreign_consec_buy", 0) >= 3:      # 外資連續3日買超 = 強信號
            signals += 1
        if row.get("short_change_pct", 0) > 5:         # 融券大增 = 空方壓力
            signals -= 1
        return signals

    df["chip_signals"] = df.apply(chip_signals, axis=1)
    df = df[df["chip_signals"] >= CHIP_SIGNAL_MIN]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stage 3: Technical indicator scoring (after yfinance download)
# ---------------------------------------------------------------------------

def stage3_technical(stage2_df: pd.DataFrame,
                     history: dict[str, pd.DataFrame],
                     fundamental: dict[str, dict] | None = None) -> pd.DataFrame:
    """
    Score each candidate on technical indicators (+ relative strength vs TAIEX
    and monthly-revenue growth when available).
    Returns top STAGE3_TOP_N stocks with score >= STAGE3_MIN_SCORE.
    """
    fundamental = fundamental or {}
    bench_df = history.get("^TWII")

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
        rs = compute_relative_strength(df_hist, bench_df)
        fund = fundamental.get(code, {})
        tech_score, tech_signals = score_stock(df_ind, rs=rs, fundamental=fund)

        if tech_score < STAGE3_MIN_SCORE:
            continue

        ind = extract_indicators(df_ind)

        # Price-source reconciliation: universe close is the official close;
        # yfinance close drives the indicators. Flag large divergences so the
        # analyst knows the technical readout may be on a different print.
        official_close = float(stock.get("close", 0) or 0)
        yf_close = ind.get("yf_close", 0)
        if official_close > 0 and yf_close > 0:
            diff_pct = abs(yf_close - official_close) / official_close * 100
            if diff_pct > 2:
                tech_signals = list(tech_signals) + [
                    f"⚠官方收盤{official_close}與yfinance{yf_close}背離{diff_pct:.1f}%"]

        row = stock.to_dict()
        row.update(ind)
        row.update({
            "tech_score": tech_score,
            "tech_signals": tech_signals,
            "rs20": rs.get("rs20"),
            "rs60": rs.get("rs60"),
            "rs_label": rs.get("rs_label", "—"),
            "revenue_b": fund.get("revenue_b"),
            "rev_yoy": fund.get("rev_yoy"),
            "rev_mom": fund.get("rev_mom"),
            "rev_month": fund.get("rev_month"),
        })
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result = result.sort_values("tech_score", ascending=False)
    return result.head(STAGE3_TOP_N).reset_index(drop=True)
