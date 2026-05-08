"""Materialized view manager.

Pre-computes aggregations from a callable source and refreshes them when one
of the configured policies fires:

- ``on_demand``  - only when ``refresh()`` is called.
- ``ttl``        - refresh when the cached result is older than ``ttl_s``.
- ``on_change``  - refresh when the source emits a different payload hash.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class MVConfig:
    """Static config for :class:`MaterializedViewManager`.

    Attributes:
        policy: ``on_demand`` | ``ttl`` | ``on_change``.
        ttl_s: time-to-live in seconds when ``policy='ttl'``.
    """
    policy: str = "on_demand"
    ttl_s: float = 60.0


@dataclass
class _ViewState:
    name: str
    source: Callable[[], Any]
    aggregator: Callable[[Any], Any]
    last_refreshed: float = 0.0
    last_source_hash: str = ""
    materialized: Any = None
    refresh_count: int = 0


class MaterializedViewManager:
    """Register, refresh, and read materialized views."""

    def __init__(self, config: Optional[MVConfig] = None) -> None:
        self.config = config or MVConfig()
        self._views: dict[str, _ViewState] = {}

    # ------------------------------------------------------------------
    def register(self, name: str,
                 source: Callable[[], Any],
                 aggregator: Callable[[Any], Any]) -> None:
        if name in self._views:
            raise ValueError(f"view {name!r} already registered")
        self._views[name] = _ViewState(
            name=name, source=source, aggregator=aggregator,
        )

    def refresh(self, name: str, force: bool = False) -> Any:
        v = self._require(name)
        if force or self._should_refresh(v):
            payload = v.source()
            v.materialized = v.aggregator(payload)
            v.last_refreshed = time.time()
            v.last_source_hash = self._hash(payload)
            v.refresh_count += 1
        return v.materialized

    def get(self, name: str) -> Any:
        return self.refresh(name, force=False)

    def names(self) -> list[str]:
        return sorted(self._views.keys())

    def stats(self, name: str) -> dict[str, Any]:
        v = self._require(name)
        return {
            "name": v.name,
            "last_refreshed": v.last_refreshed,
            "refresh_count": v.refresh_count,
            "policy": self.config.policy,
        }

    # ------------------------------------------------------------------
    def _should_refresh(self, v: _ViewState) -> bool:
        if v.refresh_count == 0:
            return True
        policy = self.config.policy
        if policy == "on_demand":
            return False
        if policy == "ttl":
            return (time.time() - v.last_refreshed) >= float(self.config.ttl_s)
        if policy == "on_change":
            payload = v.source()
            new_hash = self._hash(payload)
            if new_hash != v.last_source_hash:
                # We already paid for the source call - reuse it.
                v.materialized = v.aggregator(payload)
                v.last_refreshed = time.time()
                v.last_source_hash = new_hash
                v.refresh_count += 1
            return False
        raise ValueError(f"unknown policy: {policy!r}")

    def _require(self, name: str) -> _ViewState:
        v = self._views.get(name)
        if v is None:
            raise KeyError(f"view {name!r} not registered")
        return v

    @staticmethod
    def _hash(payload: Any) -> str:
        try:
            blob = json.dumps(payload, sort_keys=True, default=str)
        except TypeError:
            blob = repr(payload)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
