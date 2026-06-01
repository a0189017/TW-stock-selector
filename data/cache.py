import diskcache
from pathlib import Path
from config import CACHE_TTL_SECONDS

_cache_dir = Path(__file__).parent.parent / "cache"
_cache = diskcache.Cache(str(_cache_dir))


def cache_get(key: str):
    return _cache.get(key)


def cache_set(key: str, value, ttl: int = CACHE_TTL_SECONDS):
    _cache.set(key, value, expire=ttl)


def make_key(*parts) -> str:
    return "_".join(str(p) for p in parts)
