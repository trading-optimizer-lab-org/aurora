"""Redis cache for ``data_layer`` fetches with TTL.

Lazy ``redis-py``. The default ``mock=True`` mode keeps an in-memory
dict with synthetic TTL handling so tests run without redis-server.
Both modes share the same ``get`` / ``set`` / ``delete`` API and the
same DataFrame-aware helpers.
"""
from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd


@dataclass
class RedisCacheConfig:
    """Static config for :class:`RedisCache`.

    Attributes:
        url: redis URL (``redis://host:port/db``).
        url_env: env var fallback when ``url`` empty.
        namespace: key prefix for all entries; isolates apps sharing one redis.
        default_ttl: default TTL in seconds (None = no expiry).
    """
    url: str = "redis://localhost:6379/0"
    url_env: str = "AURORA_REDIS_URL"
    namespace: str = "aurora"
    default_ttl: Optional[int] = 3600


class RedisCache:
    """Thin redis cache with DataFrame and JSON helpers."""

    def __init__(self, config: Optional[RedisCacheConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or RedisCacheConfig()
        self.mock = bool(mock)
        # Mock store maps full_key -> (value_bytes, expires_at_or_None)
        self._store: dict[str, tuple[bytes, Optional[float]]] = {}
        self._client: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, key: str) -> Optional[bytes]:
        """Raw bytes get; None on miss or expired."""
        full = self._key(key)
        if self.mock:
            entry = self._store.get(full)
            if entry is None:
                return None
            value, expires = entry
            if expires is not None and time.time() >= expires:
                self._store.pop(full, None)
                return None
            return value
        c = self._connect()
        return c.get(full)

    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        """Raw bytes set with optional TTL (defaults to config.default_ttl)."""
        full = self._key(key)
        ttl = ttl if ttl is not None else self.config.default_ttl
        if self.mock:
            expires = time.time() + ttl if ttl else None
            self._store[full] = (bytes(value), expires)
            return
        c = self._connect()
        if ttl:
            c.setex(full, int(ttl), bytes(value))
        else:
            c.set(full, bytes(value))

    def delete(self, key: str) -> bool:
        """Delete the key; returns True if present."""
        full = self._key(key)
        if self.mock:
            return self._store.pop(full, None) is not None
        c = self._connect()
        return bool(c.delete(full))

    def exists(self, key: str) -> bool:
        """True if the key exists and has not expired."""
        return self.get(key) is not None

    # --- typed helpers ---

    def get_json(self, key: str) -> Any:
        raw = self.get(key)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    def set_json(self, key: str, obj: Any, ttl: Optional[int] = None) -> None:
        self.set(key, json.dumps(obj, default=str).encode("utf-8"), ttl=ttl)

    def get_dataframe(self, key: str) -> Optional[pd.DataFrame]:
        raw = self.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)

    def set_dataframe(self, key: str, df: pd.DataFrame,
                      ttl: Optional[int] = None) -> None:
        self.set(key, pickle.dumps(df, protocol=pickle.HIGHEST_PROTOCOL), ttl=ttl)

    # --- bulk helpers ---

    def clear_namespace(self) -> int:
        """Delete every key under the configured namespace. Returns count."""
        prefix = f"{self.config.namespace}:"
        if self.mock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                self._store.pop(k, None)
            return len(keys)
        c = self._connect()  # pragma: no cover - real path
        cursor = 0
        deleted = 0
        while True:  # pragma: no cover - real path
            cursor, batch = c.scan(cursor=cursor, match=f"{prefix}*", count=500)
            if batch:
                deleted += int(c.delete(*batch))
            if cursor == 0:
                break
        return deleted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _key(self, key: str) -> str:
        return f"{self.config.namespace}:{key}"

    def _resolve_url(self) -> str:
        if self.config.url:
            return self.config.url
        import os

        return os.environ.get(self.config.url_env, "")

    def _connect(self):  # pragma: no cover - real redis path
        if self._client is not None:
            return self._client
        try:
            import redis
        except ImportError as e:
            raise ImportError("redis-py required for RedisCache mock=False") from e
        url = self._resolve_url()
        if not url:
            raise RuntimeError(
                f"missing redis URL; set config.url or env {self.config.url_env}"
            )
        self._client = redis.Redis.from_url(url)
        return self._client
