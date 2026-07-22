import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# Taiwan market time. Taiwan observes no DST, so a fixed UTC+8 offset is exact
# and dependency-free (no tzdata needed). Use this everywhere instead of the
# host-local datetime.today(), so cache keys and data dates stay correct on any
# host timezone (CI/cloud).
TAIPEI_TZ = timezone(timedelta(hours=8))


def taipei_now() -> datetime:
    """Current wall-clock time in Taiwan (UTC+8)."""
    return datetime.now(TAIPEI_TZ)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Screening thresholds
VOLUME_MIN_VALUE_TWD = 10_000_000   # 10M TWD daily trade value
PRICE_MIN = 10.0
PRICE_MAX = 5000.0
CHIP_SIGNAL_MIN = 2                  # min chip signals required for Stage 2
STAGE3_MIN_SCORE = 35               # min technical score for Stage 3 pass
STAGE3_TOP_N = 80                   # top N candidates sent to Claude

# 強勢個股 (market_hot.compute_hot_stocks): deliberately STRICTER than the
# general Stage-1 liquidity bar above — this ranks today's true liquid movers,
# not just screenable candidates. Named here (not reusing PRICE_MIN/MAX /
# VOLUME_MIN_VALUE_TWD) so the two bars don't silently drift into each other.
HOT_STOCK_PRICE_MAX = 2000.0
HOT_STOCK_MIN_TRADE_VALUE = 5e7      # 5,000萬以上成交額才算流動性夠

# 回測名單 (fetch_backtest_picks): pure score_stock ranking, chip-blind.
# Score the most-liquid N of the liquidity-filtered universe.
BACKTEST_POOL_SIZE = 150

# 飆股 (fetch_momentum_stocks): pure-momentum ranking.
MOMENTUM_POOL_SIZE = 200
LIMIT_UP_PCT = 9.0                  # 漲跌幅 >= 此值視為(近)漲停/跌停
MOMENTUM_MIN_SCORE = 20              # below this, a stock isn't meaningfully "飆" —
                                     # a thin/quiet pool shouldn't pad the list with noise

# Cache
CACHE_TTL_SECONDS = 1 * 3600       # 1-hour cache TTL
SNAPSHOT_TTL_SECONDS = 90          # intraday MIS snapshot cache (short — live data)

# Claude
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 8192

# API base URLs
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"
TWSE_MIS = "https://mis.twse.com.tw/stock"   # intraday bulk quotes (getStockInfo)
MIS_BATCH_SIZE = 50                          # codes per getStockInfo request
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"
FINMIND_API = "https://api.finmindtrade.com/api/v4"
# FinMind free tier no longer allows whole-market pulls (HTTP 400); a token
# enables the fast one-shot pull. Without a token we fall back to per-stock
# fetches for the candidate list only (per-stock works on the free tier).
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
FINMIND_PERSTOCK_MAX = 250   # cap per-stock fallback so we never hammer the API
TAIFEX_OPENAPI = "https://openapi.taifex.com.tw/v1"
TAIFEX_BASE = "https://www.taifex.com.tw"

REQUEST_TIMEOUT = 20  # seconds
REQUEST_DELAY = 0.4   # seconds between TWSE historical calls


def get_recent_weekdays(n: int = 7) -> list[str]:
    """Return last n weekdays (Mon–Fri) in YYYYMMDD format, most recent first."""
    dates = []
    d = taipei_now()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return dates


def clean_number(s) -> float:
    """Parse a number string that may contain commas or sign prefixes."""
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "").replace("+", "").replace("--", "0")
    # TPEX uses △ and ▽ for up/down
    s = s.replace("△", "").replace("▽", "-")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0
