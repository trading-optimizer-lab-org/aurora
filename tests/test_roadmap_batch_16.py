"""Tests for R19 SnapshotStore mirror backend."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd
import pytest

from aurora.core.snapshots import SnapshotStore
from aurora.core.snapshots_distributed import SnapshotBackend


class _FakeBackend(SnapshotBackend):
    """In-memory fake; verifies SnapshotStore actually calls the abstraction."""

    name = "fake"

    def __init__(self) -> None:
        self.blobs: Dict[str, bytes] = {}
        self.metadata: Dict[str, Mapping[str, Any]] = {}

    def put_blob(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    def get_blob(self, key: str) -> bytes:
        if key not in self.blobs:
            raise KeyError(key)
        return self.blobs[key]

    def has_blob(self, key: str) -> bool:
        return key in self.blobs

    def put_metadata(self, key: str, payload: Mapping[str, Any]) -> None:
        self.metadata[key] = dict(payload)

    def get_metadata(self, key: str) -> Mapping[str, Any]:
        if key not in self.metadata:
            raise KeyError(key)
        return self.metadata[key]

    def list_metadata(self) -> List[Mapping[str, Any]]:
        return list(self.metadata.values())


def _make_series() -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    return pd.Series(range(100, 110), index=idx, dtype=float, name="Close")


def test_default_store_works_without_backend(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path / "snaps"))
    snap = store.freeze(_make_series(), symbol="SPY", provenance="test")
    assert snap.sha256


def test_store_with_backend_mirrors_blob_and_metadata(tmp_path: Path):
    backend = _FakeBackend()
    store = SnapshotStore(root_dir=str(tmp_path / "snaps"), backend=backend)
    snap = store.freeze(_make_series(), symbol="SPY", provenance="test")
    # Backend received the blob and metadata.
    assert snap.sha256 in backend.blobs
    assert snap.sha256 in backend.metadata
    meta = backend.metadata[snap.sha256]
    assert meta["symbol"] == "SPY"
    assert meta["n_bars"] == 10


def test_store_with_backend_blob_hashes_match(tmp_path: Path):
    backend = _FakeBackend()
    store = SnapshotStore(root_dir=str(tmp_path / "snaps"), backend=backend)
    snap = store.freeze(_make_series(), symbol="SPY", provenance="test")
    # The backend stored the same bytes as the on-disk parquet.
    on_disk = (tmp_path / "snaps" / f"{snap.sha256}.parquet").read_bytes()
    assert backend.blobs[snap.sha256] == on_disk


def test_store_backend_offline_does_not_break_primary_freeze(tmp_path: Path):
    class _Broken(_FakeBackend):
        def put_blob(self, key, data):
            raise RuntimeError("backend offline")

    store = SnapshotStore(root_dir=str(tmp_path / "snaps"), backend=_Broken())
    snap = store.freeze(_make_series(), symbol="SPY", provenance="test")
    # Primary path still committed despite mirror failure.
    assert snap.sha256
    series, reloaded = store.load(snap.sha256)
    assert reloaded.symbol == "SPY"
    assert len(series) == 10
