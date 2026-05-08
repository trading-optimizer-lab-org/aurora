"""Tests for core.snapshots_distributed (R7)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from quantforge.core.snapshots_distributed import (
    LocalSnapshotBackend,
    make_backend,
)

# --------------------------------------------------------------------------
# LocalSnapshotBackend
# --------------------------------------------------------------------------


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_local_backend_round_trips_blob(tmp_path: Path):
    be = LocalSnapshotBackend(root_dir=tmp_path)
    payload = b"some parquet bytes"
    key = _hash(payload)
    be.put_blob(key, payload)
    assert be.has_blob(key)
    assert be.get_blob(key) == payload


def test_local_backend_missing_blob_raises(tmp_path: Path):
    be = LocalSnapshotBackend(root_dir=tmp_path)
    with pytest.raises(KeyError):
        be.get_blob("nonexistent")
    assert be.has_blob("nonexistent") is False


def test_local_backend_round_trips_metadata(tmp_path: Path):
    be = LocalSnapshotBackend(root_dir=tmp_path)
    payload = {
        "sha256": "abc",
        "symbol": "SPY",
        "policy_hash": "ph123",
        "n_bars": 1000,
    }
    be.put_metadata("abc", payload)
    got = be.get_metadata("abc")
    assert got["policy_hash"] == "ph123"
    assert got["sha256"] == "abc"


def test_local_backend_list_metadata_orders_by_key(tmp_path: Path):
    be = LocalSnapshotBackend(root_dir=tmp_path)
    be.put_metadata("zzz", {"sha256": "zzz"})
    be.put_metadata("aaa", {"sha256": "aaa"})
    be.put_metadata("mmm", {"sha256": "mmm"})
    rows = be.list_metadata()
    assert [r["sha256"] for r in rows] == ["aaa", "mmm", "zzz"]


def test_local_backend_verify_detects_corruption(tmp_path: Path):
    be = LocalSnapshotBackend(root_dir=tmp_path)
    payload = b"correct payload"
    key = _hash(payload)
    be.put_blob(key, payload)
    assert be.verify(key) is True
    # Corrupt the blob behind the backend's back.
    blob_path = be._blob_path(key)
    blob_path.write_bytes(b"tampered payload")
    assert be.verify(key) is False


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def test_make_backend_local(tmp_path: Path):
    be = make_backend("local", root_dir=tmp_path)
    assert isinstance(be, LocalSnapshotBackend)
    assert be.root_dir == tmp_path


def test_make_backend_remote_raises_not_implemented(tmp_path: Path):
    for kind in ("s3", "postgres", "gcs", "azure_blob"):
        with pytest.raises(NotImplementedError):
            make_backend(kind, root_dir=tmp_path)


def test_make_backend_unknown_raises_value_error(tmp_path: Path):
    with pytest.raises(ValueError):
        make_backend("totally_bogus", root_dir=tmp_path)
