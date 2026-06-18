"""
Fetch Taiwan futures data from TAIFEX:
  - 台指期 (TX) 正逆價差 vs TAIEX
  - 三大法人台指期留倉淨口數
"""
import io
import csv
import requests
from datetime import datetime

from data.cache import cache_get, cache_set, make_key
from config import TAIFEX_OPENAPI, TAIFEX_BASE, REQUEST_TIMEOUT, clean_number
from log import get_logger

logger = get_logger()


def _get(url: str, params: dict = None) -> list | dict | None:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.get(
            url, params=params, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"}, verify=False,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("futures fetch failed (%s): %s", url, e)
        return None


def _post_text(url: str, data: dict = None) -> str | None:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.post(
            url, data=data, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"}, verify=False,
        )
        r.raise_for_status()
        # TAIFEX CSV may be Big5 or UTF-8 with BOM
        for enc in ("utf-8-sig", "utf-8", "big5"):
            try:
                return r.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return r.text
    except Exception as e:
        logger.warning("futures CSV fetch failed (%s): %s", url, e)
        return None


# ---------------------------------------------------------------------------
# 台指期近月收盤價
# ---------------------------------------------------------------------------

def fetch_tx_close() -> float:
    """
    Fetch 台指期近月合約收盤價 from TAIFEX OpenAPI.
    Returns 0.0 if unavailable.
    """
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("tx_close", today)
    cached = cache_get(key)
    if cached is not None:
        return float(cached)

    data = _get(f"{TAIFEX_OPENAPI}/DailyMarketInfo")
    if not data or not isinstance(data, list):
        return 0.0

    today_month = today[:6]  # YYYYMM
    candidates = []
    for item in data:
        code = str(item.get("ContractCode", "")).strip().upper()
        if code not in ("TX", "TXF", "TXFIT"):
            continue
        month = str(item.get("ContractMonth", "")).strip()
        if len(month) >= 6 and month[:6] >= today_month:
            close = clean_number(
                item.get("ClosePrice") or item.get("SettlementPrice") or 0
            )
            if close > 0:
                candidates.append((month[:6], close))

    if not candidates:
        return 0.0

    # Near-month = smallest contract month >= today_month
    candidates.sort()
    result = candidates[0][1]
    cache_set(key, result)
    return result


# ---------------------------------------------------------------------------
# 三大法人期貨留倉
# ---------------------------------------------------------------------------

def fetch_futures_institutional() -> dict:
    """
    Fetch 三大法人台指期留倉淨口數 from TAIFEX.
    Returns {"foreign_net": int, "dealer_net": int, "trust_net": int}
    or empty dict if unavailable.
    """
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("futures_insti", today)
    cached = cache_get(key)
    if cached is not None:
        return cached

    date_fmt = f"{today[:4]}/{today[4:6]}/{today[6:]}"
    result = _fetch_institutional_csv(date_fmt)
    if result:
        cache_set(key, result)
    return result


def _fetch_institutional_csv(date_fmt: str) -> dict:
    """
    Download 三大法人期貨留倉 CSV from TAIFEX.
    CSV columns: 日期, 商品, 身份別, 多口, 多金額, 空口, 空金額, 淨口, 淨金額
    """
    text = _post_text(
        f"{TAIFEX_BASE}/cht/3/futContractsDateDown",
        data={
            "queryStartDate": date_fmt,
            "queryEndDate": date_fmt,
            "commodityId": "TX",
        },
    )
    if not text or len(text) < 30:
        return {}

    foreign_net = dealer_net = trust_net = None
    try:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if len(row) < 8:
                continue
            identity = row[2].strip() if len(row) > 2 else ""
            try:
                net = int(clean_number(row[7]))
            except (ValueError, IndexError):
                continue
            if "外資" in identity:
                foreign_net = net
            elif "自營" in identity:
                dealer_net = net
            elif "投信" in identity:
                trust_net = net
    except Exception:
        return {}

    if foreign_net is not None:
        return {
            "foreign_net": foreign_net,
            "dealer_net": dealer_net or 0,
            "trust_net": trust_net or 0,
        }
    return {}


# ---------------------------------------------------------------------------
# 組合摘要
# ---------------------------------------------------------------------------

def fetch_futures_summary(taiex_close: float = 0.0) -> dict:
    """
    Return combined futures market summary for inclusion in 大盤概況.

    Keys returned (if data available):
      台指期收盤, 正逆價差(點), 價差解讀,
      外資期貨淨口, 自營商期貨淨口, 外資期貨方向
    """
    today = datetime.today().strftime("%Y%m%d")
    key = make_key("futures_summary", today)
    cached = cache_get(key)
    if cached is not None:
        return cached

    result = {}

    # --- 正逆價差 (raw numbers + label) ---
    tx_close = fetch_tx_close()
    if tx_close > 0 and taiex_close > 0:
        basis = round(tx_close - taiex_close, 1)
        if basis > 50:
            sentiment = "正價差偏大，多方信心強"
        elif basis > 0:
            sentiment = "小幅正價差，市場偏多"
        elif basis > -50:
            sentiment = "小幅逆價差，謹慎觀望"
        else:
            sentiment = "逆價差偏大，空方或大量避險"

        result["台指期收盤"] = round(tx_close, 1)
        result["正逆價差_點"] = basis
        result["價差解讀"] = sentiment

    # --- 三大法人留倉 (raw 口數 + 方向 label) ---
    insti = fetch_futures_institutional()
    if insti:
        fn = insti.get("foreign_net", 0)
        dn = insti.get("dealer_net", 0)
        result["外資期貨淨口_口"] = fn
        result["自營商期貨淨口_口"] = dn
        result["外資期貨方向"] = (
            "淨多（看多後市）" if fn > 0 else
            "淨空（看空/避險）" if fn < 0 else "中立"
        )

    if result:
        cache_set(key, result)
    return result
