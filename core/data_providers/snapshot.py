"""SnapshotStore-backed provider.

Loads a previously-frozen series from a :class:`SnapshotStore`. Always
``point_in_time=True`` because SnapshotStore freezes data at a known
``asof`` and verifies the SHA-256 on every read -- the data cannot
silently change between calls.

Tier permission is ``ANY``. Callers can pass either ``sha256=...`` to
load by hash, or just a ``symbol`` to load the most recent snapshot for
that symbol (optionally restricted by ``start``/``end`` overlap).
"""
from __future__ import annotations

import os
from typing import Any, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError


class SnapshotProvider(BaseDataProvider):
    """SnapshotStore lookup provider.

    Construction kwargs:
        root_dir: SnapshotStore root. Defaults to ``<PROJ>/data_snapshots``
            so the provider points at the same store the rest of
            QuantForge writes to.

    Fetch kwargs (in priority order):
        sha256: load by content hash. Takes precedence over ``symbol``.
        require_unlocked: when True (default False), raises if the
            chosen snapshot is locked. Locked snapshots can still be
            loaded if an explicit OOSGuard("explicit_unlock_*") is
            active (handled inside ``SnapshotStore.load``).
    """

    name: str = "snapshot"
    version: str = "snapshot:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"

    def __init__(self, root_dir: Optional[str] = None) -> None:
        if root_dir is None:
            from quantforge.core.runtime_paths import snapshot_root
            root_dir = str(snapshot_root())
        self.root_dir = root_dir

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        from quantforge.core.snapshots import SnapshotStore
        store = SnapshotStore(self.root_dir)

        sha = kwargs.get("sha256")
        if sha is not None:
            prices, _snap = store.load(str(sha))
            return self._slice(prices, start, end)

        snaps = store.get_by_symbol(
            symbol,
            start=start.isoformat() if start is not None else None,
            end=end.isoformat() if end is not None else None,
        )
        if not snaps:
            raise ProviderError(
                f"snapshot provider: no snapshot for {symbol!r} found in "
                f"{self.root_dir!r}"
            )
        # Most recent.
        chosen = snaps[-1]
        prices, _snap = store.load(chosen.sha256)
        return self._slice(prices, start, end)

    @staticmethod
    def _slice(
        prices: pd.Series,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
    ) -> pd.Series:
        if start is not None:
            prices = prices[prices.index >= start]
        if end is not None:
            prices = prices[prices.index <= end]
        return prices
