"""
Intraday whole-market quotes via the TWSE MIS bulk endpoint
(https://mis.twse.com.tw/stock/api/getStockInfo.jsp).

Unlike the OpenAPI/RWD universe fetchers (daily close only) and yfinance
(15-min delayed, doesn't scale to ~2000 tickers), MIS returns near-real-time
prices for both 上市 (tse_) and 上櫃 (otc_) in batches of ~50 codes/request.
Used by the 盤中族群 and 盤中飆股 tools; chip data stays end-of-day.
"""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

import certifi
import requests

from config import (TWSE_MIS, MIS_BATCH_SIZE, REQUEST_TIMEOUT, REQUEST_DELAY,
                    SNAPSHOT_TTL_SECONDS)
from data.cache import cache_get, cache_set, make_key
from log import get_logger

logger = get_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _num(x):
    """Parse a MIS numeric field; '-' / '' / bad → None."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ex_ch(code: str, exchange: str) -> str:
    prefix = "tse" if exchange == "TWSE" else "otc"
    return f"{prefix}_{code}.tw"


def _current_price(item: dict):
    """
    Best available current price. `z` (last deal) is the truth but is often '-'
    intraday; fall back to best bid/ask midpoint, then open, then prev close.
    """
    z = _num(item.get("z"))
    if z is not None:
        return z
    ask = (item.get("a") or "").split("_")
    bid = (item.get("b") or "").split("_")
    a0 = _num(ask[0]) if ask and ask[0] else None
    b0 = _num(bid[0]) if bid and bid[0] else None
    if a0 is not None and b0 is not None:
        return (a0 + b0) / 2
    o = _num(item.get("o"))
    if o is not None:
        return o
    return _num(item.get("y"))


def fetch_taiex_live() -> dict | None:
    """
    Live 加權指數 (發行量加權股價指數) via TWSE MIS (ex_ch=tse_t00.tw).

    This exists because yfinance's ^TWII feed has been observed to stop
    updating for multiple days at a time (confirmed live: querying yfinance
    fresh still returned a close dated two trading days earlier), silently
    making every 加權指數/漲跌 figure — and the futures basis calculation that
    depends on it — stale. MIS reflects the live tick and is the preferred
    source; callers should fall back to yfinance history only if this is None.

    Returns {price, prev_close, change, change_pct, open, high, low} or None
    on failure (open/high/low may themselves be None before the day's first
    print establishes them).
    """
    key = make_key("mis_taiex")
    cached = cache_get(key)
    if cached is not None:
        return cached

    try:
        with requests.Session() as session:
            session.headers.update(_HEADERS)
            try:
                session.get(f"{TWSE_MIS}/index.jsp", timeout=REQUEST_TIMEOUT, verify=certifi.where())
            except Exception as e:
                logger.warning("MIS cookie prime failed: %s", e)

            r = session.get(
                f"{TWSE_MIS}/api/getStockInfo.jsp",
                params={"ex_ch": "tse_t00.tw", "json": "1", "delay": "0"},
                timeout=REQUEST_TIMEOUT, verify=certifi.where(),
            )
            r.raise_for_status()
            arr = r.json().get("msgArray", [])
    except Exception as e:
        logger.warning("MIS TAIEX fetch failed: %s", e)
        return None

    if not arr:
        return None
    item = arr[0]
    price = _current_price(item)
    prev = _num(item.get("y"))
    if price is None or prev is None or prev == 0:
        return None

    change = price - prev
    open_ = _num(item.get("o"))
    high = _num(item.get("h"))
    low = _num(item.get("l"))
    result = {
        "price": round(price, 2),
        "prev_close": round(prev, 2),
        "change": round(change, 2),
        "change_pct": round(change / prev * 100, 2),
        "open": round(open_, 2) if open_ is not None else None,
        "high": round(high, 2) if high is not None else None,
        "low": round(low, 2) if low is not None else None,
    }
    cache_set(key, result, ttl=SNAPSHOT_TTL_SECONDS)
    return result


def fetch_market_snapshot(candidates: list[dict]) -> dict:
    """
    candidates: [{'code','exchange'}, ...].
    Returns {code: {price, prev_close, change, change_pct, volume_lots,
    open, high, low}} for every code MIS answered (open/high/low may be None
    before the day's first print). Partial results on batch failure (logged,
    not raised).
    """
    if not candidates:
        return {}

    codes = [(str(c["code"]), c["exchange"]) for c in candidates
             if str(c.get("code", "")).isdigit()]
    if not codes:
        return {}

    # Short-TTL cache keyed on the exact code set — intraday freshness matters,
    # but repeated calls within TTL (e.g. sectors + 飆股) shouldn't re-hit MIS.
    digest = hashlib.md5(
        "|".join(sorted(f"{c}:{e}" for c, e in codes)).encode()
    ).hexdigest()[:16]
    key = make_key("mis_snapshot", digest)
    cached = cache_get(key)
    if cached is not None:
        return cached

    result = _fetch_all_batches(codes)
    if result:
        cache_set(key, result, ttl=SNAPSHOT_TTL_SECONDS)
    return result


def _fetch_all_batches(codes: list[tuple[str, str]]) -> dict:
    """Fetch every code's MIS quote across concurrent batches. Closes the HTTP
    session when done (was previously left open for the caller's lifetime)."""
    with requests.Session() as session:
        session.headers.update(_HEADERS)
        try:  # prime session cookie (some MIS deployments require it)
            session.get(f"{TWSE_MIS}/index.jsp", timeout=REQUEST_TIMEOUT, verify=certifi.where())
        except Exception as e:
            logger.warning("MIS cookie prime failed: %s", e)

        batches = [codes[i:i + MIS_BATCH_SIZE] for i in range(0, len(codes), MIS_BATCH_SIZE)]

        def _fetch_batch(batch):
            """One MIS request (2 tries). Returns msgArray list or []."""
            ex_ch = "|".join(_ex_ch(c, e) for c, e in batch)
            for attempt in range(2):
                try:
                    r = session.get(
                        f"{TWSE_MIS}/api/getStockInfo.jsp",
                        params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
                        timeout=REQUEST_TIMEOUT, verify=certifi.where(),
                    )
                    r.raise_for_status()
                    return r.json().get("msgArray", [])
                except Exception as e:
                    if attempt == 0:
                        time.sleep(0.5)
                    else:
                        logger.warning("MIS batch failed (%d codes): %s", len(batch), e)
            return []

        # Concurrent batches — ~40 sequential requests took ~47s; a small pool cuts
        # that to ~10s while staying gentle on MIS.
        result: dict = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            for items in ex.map(_fetch_batch, batches):
                for item in items:
                    code = str(item.get("c", "")).strip()
                    if not code:
                        continue
                    price = _current_price(item)
                    prev = _num(item.get("y"))
                    if price is None or prev is None or prev == 0:
                        continue
                    change = price - prev
                    open_ = _num(item.get("o"))
                    high = _num(item.get("h"))
                    low = _num(item.get("l"))
                    result[code] = {
                        "price": round(price, 2),
                        "prev_close": round(prev, 2),
                        "change": round(change, 4),
                        "change_pct": round(change / prev * 100, 2),
                        "volume_lots": _num(item.get("v")) or 0,
                        "open": round(open_, 2) if open_ is not None else None,
                        "high": round(high, 2) if high is not None else None,
                        "low": round(low, 2) if low is not None else None,
                    }

        return result
