"""
Shared HTTP helpers: retry + backoff, TLS verification (certifi), consistent
logging. Centralises what used to be a near-identical `_get`/`_fetch_json`
copy in every fetcher — so retries, TLS, and timeouts stay consistent.
"""
import time

import certifi
import requests

from config import REQUEST_TIMEOUT
from log import get_logger

logger = get_logger()

_UA = {"User-Agent": "Mozilla/5.0"}


def _request(method: str, url: str, *, params=None, data=None,
             retries: int = 2, timeout: int | None = None, label: str = ""):
    """Return a successful Response or None (logged) after `retries` attempts."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(
                method, url, params=params, data=data,
                timeout=timeout or REQUEST_TIMEOUT, headers=_UA,
                verify=certifi.where(),
            )
            r.raise_for_status()
            return r
        except Exception as e:  # network / HTTP / TLS — retry then give up
            last = e
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    logger.warning("%s fetch failed (%s): %s", label or "http", url, last)
    return None


def _decode(r: requests.Response) -> str:
    for enc in ("utf-8-sig", "utf-8", "big5"):
        try:
            return r.content.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.text


def get_json(url, params=None, retries: int = 2, timeout: int | None = None, label: str = ""):
    r = _request("GET", url, params=params, retries=retries, timeout=timeout, label=label)
    if r is None:
        return None
    try:
        return r.json()
    except ValueError as e:
        logger.warning("%s non-JSON response (%s): %s", label or "http", url, e)
        return None


def get_text(url, params=None, retries: int = 2, timeout: int | None = None, label: str = ""):
    r = _request("GET", url, params=params, retries=retries, timeout=timeout, label=label)
    return _decode(r) if r is not None else None


def post_text(url, data=None, retries: int = 2, timeout: int | None = None, label: str = ""):
    r = _request("POST", url, data=data, retries=retries, timeout=timeout, label=label)
    return _decode(r) if r is not None else None
