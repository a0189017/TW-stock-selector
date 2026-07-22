"""Fetch 1-year OHLCV history for candidate stocks via yfinance."""
import yfinance as yf
import pandas as pd
import numpy as np
from analysis.common import make_ticker as _make_ticker
from data.cache import cache_get, cache_set, make_key
from config import taipei_now
from log import get_logger

logger = get_logger()

MIN_TRADING_DAYS = 60


def _serialize_df(df: pd.DataFrame) -> dict:
    return (df.reset_index()
            .assign(Date=lambda d: d["Date"].astype(str))
            .set_index("Date")
            .to_dict("index"))


def deserialize_history(cached_dict: dict) -> dict[str, pd.DataFrame]:
    result = {}
    for ticker, rows in cached_dict.items():
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        result[ticker] = df
    return result


def fetch_history(
    candidates: list[dict],
    bypass_cache: bool = False,
    include_taiex: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Fetch 1-year OHLCV for each candidate.

    bypass_cache=True  → skip cache reads entirely (always download fresh).
                         Use this for portfolio health checks where holdings
                         may not exist in the screener's candidate cache.
    bypass_cache=False → normal behaviour: read from cache, download only misses.
    """
    today = taipei_now().strftime("%Y%m%d")
    tickers = [_make_ticker(c["code"], c["exchange"]) for c in candidates]

    result: dict[str, pd.DataFrame] = {}
    missing_tickers = list(tickers)  # start with all as missing when bypassing

    if not bypass_cache:
        # Check which tickers are already cached
        missing_tickers = []
        for ticker in tickers:
            key = make_key("hist1y", ticker, today)
            cached = cache_get(key)
            if cached is not None:
                deserialized = deserialize_history({ticker: cached})
                df = deserialized.get(ticker)
                if df is not None and len(df) >= MIN_TRADING_DAYS:
                    result[ticker] = df
                    continue
            missing_tickers.append(ticker)

    # Also get TAIEX
    if include_taiex:
        taiex_key = make_key("hist1y", "^TWII", today)
        taiex_cached = cache_get(taiex_key)
        if not bypass_cache and taiex_cached is not None:
            deserialized = deserialize_history({"^TWII": taiex_cached})
            df = deserialized.get("^TWII")
            if df is not None:
                result["^TWII"] = df
        else:
            missing_tickers.append("^TWII")

    if not missing_tickers:
        return result

    # Download in chunks with a timeout: a batch of 150-200 tickers can stall on
    # a single slow name and yfinance has no ceiling; chunking + timeout bounds it.
    CHUNK = 50
    for start in range(0, len(missing_tickers), CHUNK):
        chunk = missing_tickers[start:start + CHUNK]
        try:
            raw = yf.download(
                tickers=chunk,
                period="1y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
                timeout=30,
            )
        except Exception as e:
            logger.warning("yfinance download failed for %d tickers: %s", len(chunk), e)
            continue

        if raw is None or raw.empty:
            logger.warning("yfinance returned empty for %d tickers", len(chunk))
            continue

        # yfinance 1.x returns MultiIndex columns with group_by='ticker' (even for
        # a single ticker); flat columns only for a lone ticker without group_by.
        is_multiindex = isinstance(raw.columns, pd.MultiIndex)

        for ticker in chunk:
            try:
                if is_multiindex:
                    if ticker not in raw.columns.get_level_values(0):
                        continue
                    df = raw[ticker].copy()
                else:
                    df = raw.copy()

                df = df.dropna(subset=["Close"])
                if df.empty:
                    continue
                ohlcv_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
                df = df[ohlcv_cols].copy()
                min_rows = 5 if ticker == "^TWII" else MIN_TRADING_DAYS
                if len(df) >= min_rows:
                    result[ticker] = df
                    if not bypass_cache:
                        key = make_key("hist1y", ticker, today)
                        cache_set(key, _serialize_df(df))
            except Exception as e:
                logger.debug("parse failed for %s: %s", ticker, e)
                continue

    return result
