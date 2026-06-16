import diskcache
from pathlib import Path
from config import CACHE_TTL_SECONDS

_cache_dir = Path(__file__).parent.parent / "cache"
_cache = diskcache.Cache(str(_cache_dir))

# Global switches. Prefer these over monkeypatching cache_get/cache_set on
# individual modules — those imports are bound by name (`from data.cache import
# cache_get`), so patching one module never reaches the others.
_BYPASS_READ = False   # True → cache_get always misses (force fresh fetch)
_BYPASS_WRITE = False  # True → cache_set is a no-op (don't pollute cache)


def set_bypass(read: bool = False, write: bool = False) -> None:
    """Toggle global cache behaviour. Affects every module via cache_get/cache_set."""
    global _BYPASS_READ, _BYPASS_WRITE
    _BYPASS_READ = read
    _BYPASS_WRITE = write


def cache_get(key: str):
    if _BYPASS_READ:
        return None
    return _cache.get(key)


def cache_set(key: str, value, ttl: int = CACHE_TTL_SECONDS):
    if _BYPASS_WRITE:
        return
    _cache.set(key, value, expire=ttl)


def make_key(*parts) -> str:
    return "_".join(str(p) for p in parts)
