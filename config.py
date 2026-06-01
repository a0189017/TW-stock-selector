import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Screening thresholds
VOLUME_MIN_VALUE_TWD = 10_000_000   # 10M TWD daily trade value
PRICE_MIN = 10.0
PRICE_MAX = 5000.0
CHIP_SIGNAL_MIN = 2                  # min chip signals required for Stage 2
STAGE3_MIN_SCORE = 30               # min technical score for Stage 3 pass
STAGE3_TOP_N = 80                   # top N candidates sent to Claude

# Cache
CACHE_TTL_SECONDS = 6 * 3600       # 6-hour cache TTL

# Claude
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 8096

# API base URLs
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1"
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1"
FINMIND_API = "https://api.finmindtrade.com/api/v4"

REQUEST_TIMEOUT = 20  # seconds
REQUEST_DELAY = 0.4   # seconds between TWSE historical calls


def get_recent_weekdays(n: int = 7) -> list[str]:
    """Return last n weekdays (Mon–Fri) in YYYYMMDD format, most recent first."""
    dates = []
    d = datetime.today()
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
