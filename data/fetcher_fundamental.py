"""Fetch monthly-revenue fundamentals from FinMind (free, no token required).

Taiwan stocks are very revenue-driven — 月營收 YoY/MoM is one of the few
high-signal fundamental data points published monthly. We fetch the whole
market in a single request and compute per-stock YoY / MoM growth.
"""
from datetime import datetime, timedelta

import pandas as pd

from config import FINMIND_API, REQUEST_TIMEOUT
from data.cache import cache_get, cache_set, make_key
from log import get_logger

logger = get_logger()


def _fetch_json(url: str, params: dict) -> dict | None:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"}, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("FinMind month-revenue fetch failed: %s", e)
        return None


def fetch_month_revenue() -> dict[str, dict]:
    """
    Return {code: {revenue_b, rev_yoy, rev_mom, rev_month}} for the whole market.

    revenue_b : latest month revenue in 億元 (best-effort; FinMind reports 元)
    rev_yoy   : YoY growth % vs the same month last year (None if unavailable)
    rev_mom   : MoM growth % vs previous month (None if unavailable)
    rev_month : "YYYY-MM" of the latest reported month
    """
    key = make_key("month_revenue")
    cached = cache_get(key)
    if cached is not None:
        return cached

    # ~14 months back so every stock has this-month + same-month-last-year + prev-month
    start = (datetime.today() - timedelta(days=430)).strftime("%Y-%m-%d")
    data = _fetch_json(f"{FINMIND_API}/data", params={
        "dataset": "TaiwanStockMonthRevenue",
        "start_date": start,
    })
    if not data or data.get("status") != 200 or not data.get("data"):
        logger.warning("FinMind month-revenue returned no data")
        return {}

    df = pd.DataFrame(data["data"])
    needed = {"stock_id", "revenue", "revenue_year", "revenue_month"}
    if not needed.issubset(df.columns):
        logger.warning("FinMind month-revenue missing columns: have %s", list(df.columns))
        return {}

    df = df.dropna(subset=["revenue"])
    df["ym"] = df["revenue_year"].astype(int) * 100 + df["revenue_month"].astype(int)

    result: dict[str, dict] = {}
    for code, grp in df.groupby("stock_id"):
        code = str(code).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        grp = grp.sort_values("ym")
        latest = grp.iloc[-1]
        latest_rev = float(latest["revenue"])
        latest_ym = int(latest["ym"])
        by_ym = dict(zip(grp["ym"], grp["revenue"].astype(float)))

        # MoM: previous calendar month
        y, m = divmod(latest_ym, 100)
        prev_ym = (y - 1) * 100 + 12 if m == 1 else y * 100 + (m - 1)
        yoy_ym = (y - 1) * 100 + m

        rev_mom = _pct(latest_rev, by_ym.get(prev_ym))
        rev_yoy = _pct(latest_rev, by_ym.get(yoy_ym))

        result[code] = {
            "revenue_b": round(latest_rev / 1e8, 2),
            "rev_yoy": rev_yoy,
            "rev_mom": rev_mom,
            "rev_month": f"{y}-{m:02d}",
        }

    if result:
        cache_set(key, result, ttl=24 * 3600)
    logger.debug("month-revenue: %d stocks", len(result))
    return result


def _pct(current: float, base) -> float | None:
    if base is None or base == 0:
        return None
    return round((current - base) / abs(base) * 100, 1)
