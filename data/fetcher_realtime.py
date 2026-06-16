"""Fetch latest intraday prices via yfinance (15-min delayed)."""
import yfinance as yf

from log import get_logger

logger = get_logger()


def fetch_realtime_quotes(candidates: list[dict]) -> dict[str, dict]:
    """
    Batch-fetch today's latest price for each candidate via yfinance.

    During trading hours, yfinance daily bars include today's partial bar
    with ~15-min delayed quotes.

    candidates: list of {code, exchange}  — exchange is "TWSE" or "TPEX"
    Returns {code: {close, change_pct, volume_shares}}
    """
    if not candidates:
        return {}

    ticker_map: dict[str, str] = {}  # ticker -> code
    for c in candidates:
        code = c["code"]
        suffix = ".TW" if c.get("exchange") == "TWSE" else ".TWO"
        ticker_map[f"{code}{suffix}"] = code

    tickers_str = " ".join(ticker_map)
    result: dict[str, dict] = {}
    multi = len(ticker_map) > 1

    try:
        df = yf.download(
            tickers=tickers_str,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if df.empty:
            return {}

        for ticker, code in ticker_map.items():
            try:
                stock_df = df[ticker] if multi else df
                stock_df = stock_df.dropna(subset=["Close"])
                if len(stock_df) < 2:
                    continue

                last = stock_df.iloc[-1]
                prev = stock_df.iloc[-2]

                close = round(float(last["Close"]), 2)
                prev_close = float(prev["Close"])
                change_pct = (
                    round((close - prev_close) / prev_close * 100, 2)
                    if prev_close > 0 else 0.0
                )
                vol_shares = float(last.get("Volume", 0))

                result[code] = {
                    "close": close,
                    "change_pct": change_pct,
                    "volume_shares": vol_shares,
                }
            except Exception as e:
                logger.debug("realtime parse failed for %s: %s", ticker, e)
                continue

    except Exception as e:
        logger.warning("realtime quote download failed: %s", e)

    return result
