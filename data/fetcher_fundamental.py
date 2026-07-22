"""Fetch monthly-revenue fundamentals from FinMind.

Taiwan stocks are very revenue-driven — 月營收 YoY/MoM is one of the few
high-signal fundamental data points published monthly.

FinMind's free tier NO LONGER allows a whole-market pull (returns HTTP 400,
"Your level is free"). Two supported paths:
  • FINMIND_TOKEN set  → one whole-market request (fast).
  • no token + codes   → per-stock requests for the candidate list only
                          (per-stock works on the free tier), capped and cached.
With neither, 基本面 is honestly empty (revenue is only a scoring bonus).
"""
from datetime import timedelta

import pandas as pd

from config import FINMIND_API, FINMIND_TOKEN, FINMIND_PERSTOCK_MAX, REQUEST_TIMEOUT, taipei_now
from data.cache import cache_get, cache_set, make_key
from log import get_logger

logger = get_logger()


def _fetch_json(url: str, params: dict) -> dict | None:
    from data.http import get_json
    return get_json(url, params=params, label="FinMind")


def fetch_month_revenue(codes: list[str] | None = None) -> dict[str, dict]:
    """
    Return {code: {revenue_b, rev_yoy, rev_mom, rev_month}}.

    With FINMIND_TOKEN → one whole-market request. Without a token, pass `codes`
    (the candidate list) to fetch those per-stock (free-tier allowed); the result
    is cached so repeated pipeline runs don't re-hit the API.
    """
    cache_key_suffix = "all" if FINMIND_TOKEN else f"n{len(codes)}" if codes else "none"
    key = make_key("month_revenue", cache_key_suffix)
    cached = cache_get(key)
    if cached is not None:
        return cached

    # ~14 months back so every stock has this-month + same-month-last-year + prev-month
    start = (taipei_now() - timedelta(days=430)).strftime("%Y-%m-%d")
    rows: list[dict] = []

    if FINMIND_TOKEN:
        data = _fetch_json(f"{FINMIND_API}/data", params={
            "dataset": "TaiwanStockMonthRevenue",
            "start_date": start,
            "token": FINMIND_TOKEN,
        })
        if not data or data.get("status") != 200 or not data.get("data"):
            logger.warning("FinMind whole-market month-revenue returned no data")
            return {}
        rows = data["data"]
    elif codes:
        from concurrent.futures import ThreadPoolExecutor
        wanted = [c for c in dict.fromkeys(codes) if str(c).isdigit()][:FINMIND_PERSTOCK_MAX]

        def _one(c):
            return _fetch_json(f"{FINMIND_API}/data", params={
                "dataset": "TaiwanStockMonthRevenue",
                "data_id": c,
                "start_date": start,
            })

        with ThreadPoolExecutor(max_workers=8) as ex:
            for data in ex.map(_one, wanted):
                if data and data.get("status") == 200 and data.get("data"):
                    rows.extend(data["data"])
        if not rows:
            logger.warning("FinMind per-stock month-revenue returned no data "
                           "(set FINMIND_TOKEN for whole-market)")
            # Negative-cache briefly so a dead/limited API isn't re-hit each run.
            cache_set(key, {}, ttl=6 * 3600)
            return {}
    else:
        logger.warning("FinMind month-revenue skipped: no FINMIND_TOKEN and no codes")
        return {}

    df = pd.DataFrame(rows)
    needed = {"stock_id", "revenue", "revenue_year", "revenue_month"}
    if not needed.issubset(df.columns):
        logger.warning("FinMind month-revenue missing columns: have %s", list(df.columns))
        return {}

    df = df.dropna(subset=["revenue"])
    df["ym"] = df["revenue_year"].astype(int) * 100 + df["revenue_month"].astype(int)

    result = _rows_to_result(df)
    if result:
        cache_set(key, result, ttl=24 * 3600)
    logger.debug("month-revenue: %d stocks", len(result))
    return result


def _rows_to_result(df: pd.DataFrame) -> dict[str, dict]:
    """Group FinMind revenue rows by stock and compute latest YoY / MoM."""
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

        y, m = divmod(latest_ym, 100)
        prev_ym = (y - 1) * 100 + 12 if m == 1 else y * 100 + (m - 1)
        yoy_ym = (y - 1) * 100 + m

        result[code] = {
            "revenue_b": round(latest_rev / 1e8, 2),
            "rev_yoy": _pct(latest_rev, by_ym.get(yoy_ym)),
            "rev_mom": _pct(latest_rev, by_ym.get(prev_ym)),
            "rev_month": f"{y}-{m:02d}",
        }
    return result


def _pct(current: float, base) -> float | None:
    if base is None or base == 0:
        return None
    return round((current - base) / abs(base) * 100, 1)
