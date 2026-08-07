"""In-memory cache with TTL and per-source health tracking."""

import time
from datetime import datetime

_cache = {}
_source_status = {}
CACHE_TTL = 3600


def get_cached(source_name):
    key = f"events_{source_name}"
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None


def set_cache(source_name, data):
    key = f"events_{source_name}"
    _cache[key] = (data, time.time())


def record_status(name, count=None, error=None):
    _source_status[name] = {
        "ok": error is None,
        "count": count,
        "error": error,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_all_status():
    return dict(_source_status)


def source(name):
    """Decorator: wrap a fetcher with caching and status recording. Errors return []."""
    def deco(fn):
        def wrapper():
            cached = get_cached(name)
            if cached is not None:
                return cached
            try:
                result = fn()
                if result:
                    set_cache(name, result)
                record_status(name, count=len(result))
                return result
            except Exception as e:
                record_status(name, error=f"{type(e).__name__}: {e}")
                return []
        return wrapper
    return deco
