"""Fetch stock universe from TWSE + TPEX with industry classification.

Data availability by time (Taiwan time):
  - 盤中 (09:00–13:30): OpenAPI returns YESTERDAY's close data
  - 盤後 (~16:00+):      OpenAPI returns TODAY's close data
  - 非交易日/清晨:       OpenAPI may return empty → falls back to last-known-good cache
"""
import time
import requests
import pandas as pd
from datetime import datetime
from data.cache import cache_get, cache_set, make_key
from config import TWSE_OPENAPI, TWSE_RWD, TPEX_OPENAPI, FINMIND_API, REQUEST_TIMEOUT, CACHE_TTL_SECONDS, clean_number, get_recent_weekdays
from log import get_logger

logger = get_logger()

# How many stocks minimum before we consider the data "valid"
_MIN_STOCKS = 200
# Persistent cache key for last successful fetch (7-day TTL)
_TWSE_LAST_KEY = "twse_universe_last"
_TPEX_LAST_KEY = "tpex_universe_last"
_LAST_CACHE_TTL = 7 * 24 * 3600


def _fetch_json(url: str, params: dict = None, retries: int = 2) -> list | dict | None:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"}, verify=False)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                logger.warning("universe fetch failed (%s): %s", url, e)
    return None


# ---------------------------------------------------------------------------
# TWSE
# ---------------------------------------------------------------------------

def _parse_twse_openapi(data: list) -> list[dict]:
    """Parse TWSE OpenAPI STOCK_DAY_ALL response."""
    rows = []
    if not data:
        return rows
    for item in data:
        code = str(item.get("Code", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = clean_number(item.get("ClosingPrice"))
        trade_value = clean_number(item.get("TradeValue"))
        if close <= 0 or trade_value <= 0:
            continue
        change = clean_number(str(item.get("Change", "0")).strip())
        prev = close - change
        change_pct = (change / prev * 100) if prev != 0 else 0.0
        rows.append({
            "code": code,
            "name": str(item.get("Name", "")).strip(),
            "exchange": "TWSE",
            "close": close,
            "change": change,
            "change_pct": round(change_pct, 2),
            "open": clean_number(item.get("OpeningPrice")),
            "high": clean_number(item.get("HighestPrice")),
            "low": clean_number(item.get("LowestPrice")),
            "volume_shares": clean_number(item.get("TradeVolume")),
            "trade_value": trade_value,
            "transactions": clean_number(item.get("Transaction")),
        })
    return rows


def _parse_twse_rwd(data: dict) -> list[dict]:
    """Parse TWSE RWD afterTrading/STOCK_DAY_ALL response."""
    rows = []
    if not data or data.get("stat") != "OK":
        return rows
    fields = data.get("fields", [])
    records = data.get("data", [])
    if not fields or not records:
        return rows

    def idx(name: str) -> int:
        for i, f in enumerate(fields):
            if name in f:
                return i
        return -1

    code_i = idx("證券代號")
    name_i = idx("證券名稱")
    close_i = idx("收盤價")
    open_i = idx("開盤價")
    high_i = idx("最高價")
    low_i = idx("最低價")
    vol_i = idx("成交股數")
    val_i = idx("成交金額")
    txn_i = idx("成交筆數")
    chg_i = idx("漲跌價差")

    required = [code_i, name_i, close_i, val_i]
    if any(i == -1 for i in required):
        return rows

    for row in records:
        if len(row) <= max(i for i in [code_i, name_i, close_i, val_i] if i >= 0):
            continue
        code = str(row[code_i]).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = clean_number(row[close_i])
        trade_value = clean_number(row[val_i])
        if close <= 0 or trade_value <= 0:
            continue
        change = clean_number(row[chg_i]) if chg_i >= 0 and len(row) > chg_i else 0.0
        prev = close - change
        change_pct = (change / prev * 100) if prev != 0 else 0.0
        rows.append({
            "code": code,
            "name": str(row[name_i]).strip(),
            "exchange": "TWSE",
            "close": close,
            "change": change,
            "change_pct": round(change_pct, 2),
            "open": clean_number(row[open_i]) if open_i >= 0 and len(row) > open_i else 0.0,
            "high": clean_number(row[high_i]) if high_i >= 0 and len(row) > high_i else 0.0,
            "low": clean_number(row[low_i]) if low_i >= 0 and len(row) > low_i else 0.0,
            "volume_shares": clean_number(row[vol_i]) if vol_i >= 0 and len(row) > vol_i else 0.0,
            "trade_value": trade_value,
            "transactions": clean_number(row[txn_i]) if txn_i >= 0 and len(row) > txn_i else 0.0,
        })
    return rows


def _roc_date_to_gregorian(roc_str: str) -> str:
    """Convert TWSE ROC date string '1150513' → '20260513'."""
    try:
        roc_str = str(roc_str).strip()
        if len(roc_str) == 7:
            roc_year = int(roc_str[:3])
            return str(roc_year + 1911) + roc_str[3:]
    except Exception:
        pass
    return ""


def fetch_twse_universe() -> pd.DataFrame:
    """
    Fetch all TWSE stocks with the most current available closing prices.

    Strategy (in order):
      1. RWD afterTrading endpoint for today → has today's close once market settles
      2. OpenAPI STOCK_DAY_ALL → returns latest published (may lag ~30 min after close)
      3. RWD for previous trading days → for non-trading days / weekends
      4. last-known-good cache → absolute fallback
    """
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("twse_universe", today)
    cached = cache_get(key)
    if cached is not None:
        return pd.DataFrame(cached)

    rows = []
    data_date = ""

    # 1) Try RWD with today's date first — most accurate once data is published
    rwd_today = _fetch_json(
        f"{TWSE_RWD}/afterTrading/STOCK_DAY_ALL",
        params={"date": today, "response": "json"},
    )
    rows = _parse_twse_rwd(rwd_today or {})
    if len(rows) >= _MIN_STOCKS:
        data_date = today

    # 2) Try OpenAPI if RWD today is empty (data not published yet)
    if len(rows) < _MIN_STOCKS:
        openapi_data = _fetch_json(f"{TWSE_OPENAPI}/exchangeReport/STOCK_DAY_ALL")
        rows = _parse_twse_openapi(openapi_data or [])
        # Check if OpenAPI data is actually today's or stale (yesterday's)
        if rows and openapi_data:
            first_date = _roc_date_to_gregorian(openapi_data[0].get("Date", ""))
            data_date = first_date
            if first_date and first_date != today:
                # OpenAPI still serving a previous day — try RWD for recent days
                rows = []

    # 3) Try RWD for recent trading days (skip today — already tried above)
    if len(rows) < _MIN_STOCKS:
        for date in get_recent_weekdays(7):
            if date == today:
                continue
            rwd = _fetch_json(
                f"{TWSE_RWD}/afterTrading/STOCK_DAY_ALL",
                params={"date": date, "response": "json"},
            )
            rows = _parse_twse_rwd(rwd or {})
            if len(rows) >= _MIN_STOCKS:
                data_date = date
                break
            time.sleep(0.4)

    # 4) last-known-good fallback
    if len(rows) < _MIN_STOCKS:
        last = cache_get(_TWSE_LAST_KEY)
        if last:
            return pd.DataFrame(last)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # If data is from a previous trading day (market not yet closed or lag),
    # cache with a short 5-min TTL so we pick up today's data quickly once available.
    # If it IS today's data, use the normal 45-min TTL.
    is_today_data = (data_date == today)
    ttl = 45 * 60 if is_today_data else 5 * 60
    cache_set(key, df.to_dict("records"), ttl=ttl)
    # Store the actual data date so callers can report it accurately
    cache_set(make_key("twse_universe_date", today), data_date, ttl=ttl)
    cache_set(_TWSE_LAST_KEY, df.to_dict("records"), ttl=_LAST_CACHE_TTL)
    return df


# ---------------------------------------------------------------------------
# TPEX
# ---------------------------------------------------------------------------

def _parse_tpex(data: list) -> list[dict]:
    """Parse TPEX mainboard_quotes response."""
    rows = []
    if not data:
        return rows
    for item in data:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = clean_number(item.get("Close"))
        trade_value = clean_number(item.get("TransactionAmount"))
        if close <= 0 or trade_value <= 0:
            continue
        change = clean_number(str(item.get("Change", "0")).strip())
        prev = close - change
        change_pct = (change / prev * 100) if prev != 0 else 0.0
        rows.append({
            "code": code,
            "name": str(item.get("CompanyName", "")).strip(),
            "exchange": "TPEX",
            "close": close,
            "change": change,
            "change_pct": round(change_pct, 2),
            "open": clean_number(item.get("Open")),
            "high": clean_number(item.get("High")),
            "low": clean_number(item.get("Low")),
            "volume_shares": clean_number(item.get("TradingShares")),
            "trade_value": trade_value,
            "transactions": clean_number(item.get("TransactionNumber")),
        })
    return rows


def _parse_tpex_rwd(data: dict) -> list[dict]:
    """Parse TPEX RWD historical response (if available)."""
    rows = []
    if not data or data.get("iTotalRecords", 0) == 0:
        return rows
    for item in data.get("aaData", []):
        if not item:
            continue
        try:
            code = str(item[0]).strip()
            if not (code.isdigit() and len(code) == 4):
                continue
            close = clean_number(item[2])
            trade_value = clean_number(item[9]) if len(item) > 9 else 0.0
            if close <= 0:
                continue
            change = clean_number(item[3]) if len(item) > 3 else 0.0
            prev = close - change
            change_pct = (change / prev * 100) if prev != 0 else 0.0
            rows.append({
                "code": code,
                "name": str(item[1]).strip() if len(item) > 1 else "",
                "exchange": "TPEX",
                "close": close,
                "change": change,
                "change_pct": round(change_pct, 2),
                "open": clean_number(item[4]) if len(item) > 4 else 0.0,
                "high": clean_number(item[5]) if len(item) > 5 else 0.0,
                "low": clean_number(item[6]) if len(item) > 6 else 0.0,
                "volume_shares": clean_number(item[7]) if len(item) > 7 else 0.0,
                "trade_value": trade_value,
                "transactions": 0.0,
            })
        except (IndexError, TypeError):
            continue
    return rows


def fetch_tpex_universe() -> pd.DataFrame:
    """Fetch all TPEX stocks. Falls back to previous trading day if today unavailable."""
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("tpex_universe", today)
    cached = cache_get(key)
    if cached is not None:
        return pd.DataFrame(cached)

    # 1) Try OpenAPI
    data = _fetch_json(f"{TPEX_OPENAPI}/tpex_mainboard_quotes")
    rows = _parse_tpex(data or [])
    used_fallback = False

    # 2) If too few rows, try TPEX RWD historical endpoint
    if len(rows) < _MIN_STOCKS:
        for date in get_recent_weekdays(7):
            # TPEX RWD daily quotes format: YYYY/MM/DD
            date_fmt = f"{date[:4]}/{date[4:6]}/{date[6:]}"
            rwd = _fetch_json(
                "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php",
                params={"l": "zh-tw", "d": date_fmt, "se": "EW"},
            )
            rows = _parse_tpex_rwd(rwd or {})
            if len(rows) >= _MIN_STOCKS:
                used_fallback = (date != today)
                break
            time.sleep(0.4)

    # 3) Last-known-good fallback
    if len(rows) < _MIN_STOCKS:
        last = cache_get(_TPEX_LAST_KEY)
        if last:
            return pd.DataFrame(last)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Short TTL when data is from a previous trading day so today's data is picked up quickly
    tpex_ttl = 5 * 60 if used_fallback else CACHE_TTL_SECONDS
    cache_set(key, df.to_dict("records"), ttl=tpex_ttl)
    cache_set(_TPEX_LAST_KEY, df.to_dict("records"), ttl=_LAST_CACHE_TTL)
    return df


# ---------------------------------------------------------------------------
# Supporting data
# ---------------------------------------------------------------------------

def fetch_twse_pe() -> dict:
    """Fetch TWSE P/E, PB, dividend yield."""
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("twse_pe", today)
    cached = cache_get(key)
    if cached is not None:
        return cached

    data = _fetch_json(f"{TWSE_OPENAPI}/exchangeReport/BWIBBU_ALL")
    if not data:
        last = cache_get("twse_pe_last")
        return last or {}

    result = {}
    for item in data:
        code = str(item.get("Code", "")).strip()
        result[code] = {
            "pe_ratio": clean_number(item.get("PEratio")),
            "pb_ratio": clean_number(item.get("PBratio")),
            "div_yield": clean_number(item.get("DividendYield")),
        }
    cache_set(key, result)
    cache_set("twse_pe_last", result, ttl=_LAST_CACHE_TTL)
    return result


def fetch_industry_map() -> dict:
    """Fetch industry categories from FinMind (free, no token)."""
    key = make_key("industry_map")
    cached = cache_get(key)
    if cached is not None:
        return cached

    data = _fetch_json(f"{FINMIND_API}/data", params={"dataset": "TaiwanStockInfo"})
    if not data or "data" not in data:
        return {}

    result = {}
    for item in data.get("data", []):
        code = str(item.get("stock_id", "")).strip()
        industry = str(item.get("industry_category", "")).strip()
        if code and industry:
            result[code] = industry

    cache_set(key, result, ttl=24 * 3600)
    return result


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def fetch_universe() -> pd.DataFrame:
    """Return combined TWSE+TPEX universe with industry info. Raises if nothing fetched."""
    twse_df = fetch_twse_universe()
    tpex_df = fetch_tpex_universe()

    if twse_df.empty and tpex_df.empty:
        raise RuntimeError("無法取得股票清單，請確認網路連線後再試")

    parts = [df for df in [twse_df, tpex_df] if not df.empty]
    df = pd.concat(parts, ignore_index=True)

    pe_map = fetch_twse_pe()
    for col in ("pe_ratio", "pb_ratio", "div_yield"):
        df[col] = df["code"].map(lambda c: pe_map.get(c, {}).get(col, 0.0))

    industry_map = fetch_industry_map()
    df["industry"] = df["code"].map(lambda c: industry_map.get(c, "其他"))

    return df


def fetch_market_summary(universe_df: pd.DataFrame) -> dict:
    """Compute high-level market summary from universe data."""
    if universe_df.empty:
        return {}

    twse = universe_df[universe_df["exchange"] == "TWSE"]
    up = int((twse["change"] > 0).sum())
    down = int((twse["change"] < 0).sum())
    flat = int((twse["change"] == 0).sum())
    total_value_b = round(twse["trade_value"].sum() / 1e8, 1)

    # Canonical 大盤概況 — raw values, Chinese keys. taiex/外資合計 are filled in
    # later by the pipeline once history/chip data is available; default to None.
    return {
        "上漲家數": up,
        "下跌家數": down,
        "持平家數": flat,
        "成交值_億": total_value_b,
        "加權指數": None,
        "加權指數漲跌": None,
        "加權指數漲跌_%": None,
        "外資合計淨買_張": None,
    }
