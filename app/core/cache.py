import time
from typing import Any, Optional, Dict, Tuple


class SimpleTTLCache:
    """
    Thread-safe, lightweight in-memory TTL cache with automatic expiration
    and prefix-based invalidation.
    """

    def __init__(self, default_ttl: int = 60, max_entries: int = 500):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._cache: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            val, expiry = self._cache[key]
            if time.time() < expiry:
                return val
            else:
                self._cache.pop(key, None)
        return None

    def set(self, key: str, val: Any, ttl: Optional[int] = None):
        now = time.time()
        # Clean expired entries if approaching max size
        if len(self._cache) >= self.max_entries:
            expired_keys = [k for k, (_, exp) in self._cache.items() if exp <= now]
            for k in expired_keys:
                self._cache.pop(k, None)

            # If still full, evict oldest 20%
            if len(self._cache) >= self.max_entries:
                sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][1])
                for k in sorted_keys[: int(self.max_entries * 0.2)]:
                    self._cache.pop(k, None)

        expiry = now + (ttl if ttl is not None else self.default_ttl)
        self._cache[key] = (val, expiry)

    def invalidate(self, prefix: str = ""):
        """
        Invalidates all keys matching a prefix. If prefix is empty, clears entire cache.
        """
        if not prefix:
            self._cache.clear()
        else:
            keys_to_del = [k for k in self._cache.keys() if k.startswith(prefix)]
            for k in keys_to_del:
                self._cache.pop(k, None)


# Global TTL cache instance with 60s default TTL
ttl_cache = SimpleTTLCache(default_ttl=60)
