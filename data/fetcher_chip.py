"""Fetch chip data: 三大法人 (institutional) and 融資融券 (margin trading)."""
import time
import requests
import pandas as pd
from data.cache import cache_get, cache_set, make_key
from config import TWSE_RWD, TWSE_OPENAPI, TPEX_OPENAPI, REQUEST_TIMEOUT, REQUEST_DELAY, clean_number, get_recent_weekdays


def _get(url: str, params: dict = None) -> dict | list | None:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"}, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# TWSE 三大法人 (T86)
# ---------------------------------------------------------------------------

def _parse_t86(data: dict) -> pd.DataFrame:
    """Parse TWSE T86 RWD response into DataFrame."""
    if not data or data.get("stat") != "OK":
        return pd.DataFrame()

    fields = data.get("fields", [])
    rows = data.get("data", [])
    if not fields or not rows:
        return pd.DataFrame()

    def field_idx(*keywords) -> int:
        """Find field index where the field name contains ALL given keywords."""
        for i, f in enumerate(fields):
            if all(kw in f for kw in keywords):
                return i
        return -1

    code_idx = field_idx("證券代號")
    # 外資：外陸資買賣超股數(不含外資自營商)  or  外資及陸資-買賣超
    foreign_idx = field_idx("外陸資買賣超", "不含")
    if foreign_idx == -1:
        foreign_idx = field_idx("外資及陸資", "買賣超")
    if foreign_idx == -1:
        foreign_idx = field_idx("外資", "買賣超")
    # 投信：投信買賣超股數
    trust_idx = field_idx("投信買賣超")
    if trust_idx == -1:
        trust_idx = field_idx("投信", "買賣超")
    # 三大法人：三大法人買賣超股數
    big3_idx = field_idx("三大法人買賣超")
    if big3_idx == -1:
        big3_idx = field_idx("三大法人", "買賣超")

    if any(i == -1 for i in [code_idx, foreign_idx, trust_idx, big3_idx]):
        return pd.DataFrame()

    records = []
    for row in rows:
        max_idx = max(code_idx, foreign_idx, trust_idx, big3_idx)
        if len(row) <= max_idx:
            continue
        code = str(row[code_idx]).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        records.append({
            "code": code,
            "foreign_net": clean_number(row[foreign_idx]) / 1000,   # shares → 張
            "trust_net": clean_number(row[trust_idx]) / 1000,
            "big3_net": clean_number(row[big3_idx]) / 1000,
        })
    return pd.DataFrame(records)


def fetch_twse_institutional(dates: list[str]) -> pd.DataFrame:
    """Fetch TWSE T86 for given dates. Returns DataFrame with 5-day aggregates per stock."""
    all_dfs = []
    for date in dates:
        key = make_key("t86", date)
        cached = cache_get(key)
        if cached is not None:
            df = pd.DataFrame(cached)
        else:
            raw = _get(f"{TWSE_RWD}/fund/T86",
                       params={"date": date, "selectType": "ALLBUT0999", "response": "json"})
            df = _parse_t86(raw)
            if not df.empty:
                cache_set(key, df.to_dict("records"))
            time.sleep(REQUEST_DELAY)

        if not df.empty:
            df["date"] = date
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)

    # Today's net + 5-day accumulated
    latest_date = max(d["date"] for d in [{"date": row} for row in combined["date"].unique()])
    today_df = combined[combined["date"] == latest_date].set_index("code")

    agg = (combined.groupby("code")[["foreign_net", "trust_net", "big3_net"]]
           .sum()
           .rename(columns={
               "foreign_net": "foreign_net_5d",
               "trust_net": "trust_net_5d",
               "big3_net": "big3_net_5d",
           }))

    today_df = today_df[["foreign_net", "trust_net", "big3_net"]].rename(columns={
        "foreign_net": "foreign_net_today",
        "trust_net": "trust_net_today",
        "big3_net": "big3_net_today",
    })

    result = agg.join(today_df, how="left").reset_index()
    return result


# ---------------------------------------------------------------------------
# TWSE 融資融券 (MI_MARGN)
# ---------------------------------------------------------------------------

def fetch_twse_margin() -> pd.DataFrame:
    """Fetch TWSE margin balance (today vs yesterday) from OpenAPI."""
    from datetime import datetime
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("mi_margn", today)
    cached = cache_get(key)
    if cached is not None:
        return pd.DataFrame(cached)

    data = _get(f"{TWSE_OPENAPI}/exchangeReport/MI_MARGN")
    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        # Support both English and Chinese field names
        code = str(item.get("StockCode") or item.get("股票代號", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue

        today_bal = clean_number(
            item.get("MarginPurchaseTodayBalance") or item.get("融資今日餘額", 0))
        prev_bal = clean_number(
            item.get("MarginPurchaseYesterdayBalance") or item.get("融資前日餘額", 0))
        limit = clean_number(
            item.get("MarginPurchaseLimit") or item.get("融資限額", 0))
        if prev_bal > 0:
            change_pct = (today_bal - prev_bal) / prev_bal * 100
        else:
            change_pct = 0.0
        util_rate = (today_bal / limit * 100) if limit > 0 else 0.0

        rows.append({
            "code": code,
            "margin_today": today_bal,
            "margin_prev": prev_bal,
            "margin_change_pct": round(change_pct, 2),
            "margin_util_rate": round(util_rate, 2),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        cache_set(key, df.to_dict("records"))
    return df


# ---------------------------------------------------------------------------
# TPEX 三大法人 + 融資融券
# ---------------------------------------------------------------------------

def fetch_tpex_institutional() -> pd.DataFrame:
    """Fetch TPEX today's institutional net buy/sell."""
    from datetime import datetime
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("tpex_3insti", today)
    cached = cache_get(key)
    if cached is not None:
        return pd.DataFrame(cached)

    data = _get(f"{TPEX_OPENAPI}/tpex_3insti_daily_trading")
    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        # Field names may vary; try multiple keys
        foreign = clean_number(item.get("ForeignAndMainlandChina_Diff") or
                               item.get("Foreign_Diff") or item.get("ForeignDiff", 0))
        trust = clean_number(item.get("InvestmentTrust_Diff") or
                             item.get("Trust_Diff") or item.get("InvestmentTrustDiff", 0))
        dealer = clean_number(item.get("Dealer_Diff") or item.get("DealerDiff", 0))
        total = clean_number(item.get("TotalDiff") or item.get("Total_Diff", 0))
        if total == 0:
            total = foreign + trust + dealer
        rows.append({
            "code": code,
            "foreign_net_today": foreign / 1000,
            "trust_net_today": trust / 1000,
            "big3_net_today": total / 1000,
            "foreign_net_5d": foreign / 1000,  # only today available for TPEX
            "trust_net_5d": trust / 1000,
            "big3_net_5d": total / 1000,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        cache_set(key, df.to_dict("records"))
    return df


def fetch_tpex_margin() -> pd.DataFrame:
    """Fetch TPEX margin balance (today only, no yesterday comparison)."""
    from datetime import datetime
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("tpex_margin", today)
    cached = cache_get(key)
    if cached is not None:
        return pd.DataFrame(cached)

    data = _get(f"{TPEX_OPENAPI}/tpex_mainboard_margin_balance")
    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        today_bal = clean_number(item.get("MarginPurchaseBalance") or
                                 item.get("MarginPurchaseTodayBalance", 0))
        limit = clean_number(item.get("MarginPurchaseQuota") or
                             item.get("MarginPurchaseLimit", 1))
        util_rate = (today_bal / limit * 100) if limit > 0 else 0.0
        rows.append({
            "code": code,
            "margin_today": today_bal,
            "margin_prev": today_bal,       # no prev available
            "margin_change_pct": 0.0,
            "margin_util_rate": round(util_rate, 2),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        cache_set(key, df.to_dict("records"))
    return df


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def fetch_chip_data(dates: list[str] | None = None) -> pd.DataFrame:
    """
    Return chip DataFrame indexed by code with columns:
    foreign_net_today, foreign_net_5d, trust_net_today, trust_net_5d,
    big3_net_today, margin_today, margin_prev, margin_change_pct, margin_util_rate
    """
    if dates is None:
        dates = get_recent_weekdays(7)[:5]

    twse_insti = fetch_twse_institutional(dates)
    tpex_insti = fetch_tpex_institutional()
    twse_margin = fetch_twse_margin()
    tpex_margin = fetch_tpex_margin()

    insti = pd.concat([twse_insti, tpex_insti], ignore_index=True)
    margin = pd.concat([twse_margin, tpex_margin], ignore_index=True)

    if insti.empty and margin.empty:
        return pd.DataFrame()

    chip = insti.set_index("code") if not insti.empty else pd.DataFrame()
    marg = margin.set_index("code") if not margin.empty else pd.DataFrame()

    if chip.empty:
        result = marg
    elif marg.empty:
        result = chip
    else:
        result = chip.join(marg, how="outer")

    return result.reset_index()


def compute_market_foreign_total(chip_df: pd.DataFrame) -> str:
    """Sum 外資 today net across all stocks in 億張."""
    if chip_df.empty or "foreign_net_today" not in chip_df.columns:
        return "—"
    total = chip_df["foreign_net_today"].sum()
    return f"{total:+,.0f} 張"
