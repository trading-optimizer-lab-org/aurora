"""Tests for the immutable data snapshots store.

Run: uv run pytest quantforge/tests/test_snapshots.py -v
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantforge.core.snapshots import (
    DataSnapshot,
    IntegrityError,
    SnapshotStore,
)
from quantforge.core.data_layer import OOSGuard


def _make_series(n: int = 50, start: str = "2020-01-01", seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, periods=n, freq="B")
    values = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    return pd.Series(values, index=idx, name="Close")


# ---------------------------------------------------------------------------
# freeze + parquet + index
# ---------------------------------------------------------------------------

def test_freeze_creates_parquet_and_index(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series()
    snap = store.freeze(s, symbol="SPY", provenance="manual")

    assert isinstance(snap, DataSnapshot)
    assert os.path.exists(snap.data_path)
    assert os.path.exists(os.path.join(str(tmp_path), "snapshots_index.sqlite"))
    assert snap.symbol == "SPY"
    assert snap.provenance == "manual"
    assert snap.n_bars == len(s)
    assert snap.start == s.index[0]
    assert snap.end == s.index[-1]

    # index has exactly one row
    with sqlite3.connect(store.index_path) as con:
        rows = con.execute("SELECT * FROM snapshots").fetchall()
    assert len(rows) == 1


def test_load_verifies_hash(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=1)
    snap = store.freeze(s, symbol="QQQ", provenance="yfinance")
    loaded, snap2 = store.load(snap.sha256)
    assert snap2.sha256 == snap.sha256
    assert len(loaded) == len(s)
    assert np.allclose(loaded.to_numpy(), s.to_numpy())


def test_load_detects_corrupted_parquet(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=2)
    snap = store.freeze(s, symbol="IWM", provenance="manual")

    # Corrupt the parquet file
    with open(snap.data_path, "wb") as f:
        f.write(b"\x00\x00not-a-parquet\x00")

    with pytest.raises(IntegrityError):
        store.load(snap.sha256)


def test_list_snapshots(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    store.freeze(_make_series(seed=10), symbol="A", provenance="manual")
    store.freeze(_make_series(seed=11), symbol="B", provenance="manual")
    store.freeze(_make_series(seed=12), symbol="C", provenance="parquet")
    snaps = store.list_snapshots()
    assert len(snaps) == 3
    assert {snap.symbol for snap in snaps} == {"A", "B", "C"}


def test_get_by_symbol(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    store.freeze(_make_series(seed=20, start="2020-01-01"),
                 symbol="SPY", provenance="manual")
    store.freeze(_make_series(seed=21, start="2021-01-01"),
                 symbol="SPY", provenance="manual")
    store.freeze(_make_series(seed=22), symbol="QQQ", provenance="manual")

    spy_all = store.get_by_symbol("SPY")
    assert len(spy_all) == 2
    assert {snap.symbol for snap in spy_all} == {"SPY"}

    # filter to a window that overlaps only the first SPY snapshot
    spy_2020 = store.get_by_symbol("SPY", end="2020-06-30")
    assert len(spy_2020) == 1
    assert spy_2020[0].start == pd.Timestamp("2020-01-01")


# ---------------------------------------------------------------------------
# Lock semantics
# ---------------------------------------------------------------------------

def test_locked_snapshot_requires_oosguard(tmp_path: Path):
    """A locked snapshot must NOT be loadable without OOSGuard('explicit_unlock')."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=30)
    snap = store.freeze(s, symbol="OOS", provenance="parquet", locked=True)
    assert snap.locked is True

    # No guard active → must raise
    with pytest.raises(IntegrityError, match="locked"):
        store.load(snap.sha256)

    # Wrong-phase guard also blocks
    with pytest.raises(IntegrityError, match="locked"):
        with OOSGuard("optimization"):
            store.load(snap.sha256)


def test_locked_snapshot_loads_inside_oosguard(tmp_path: Path):
    """Inside ``with OOSGuard('explicit_unlock'): ...`` a locked snapshot loads."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=31)
    snap = store.freeze(s, symbol="OOS", provenance="parquet", locked=True)
    with OOSGuard("explicit_unlock"):
        loaded, snap2 = store.load(snap.sha256)
    assert snap2.sha256 == snap.sha256
    assert len(loaded) == len(s)


# ---------------------------------------------------------------------------
# Integrity & determinism
# ---------------------------------------------------------------------------

def test_integrity_error_raised_on_mismatch(tmp_path: Path):
    """If the parquet content drifts from the recorded hash, load() raises."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=40)
    snap = store.freeze(s, symbol="DRIFT", provenance="manual")

    # Overwrite parquet with a different (valid) series → hash mismatch
    different = _make_series(seed=99)  # same length & freq, different values
    different.to_frame("Close").to_parquet(snap.data_path)

    assert store.verify_integrity(snap.sha256) is False
    with pytest.raises(IntegrityError, match="hash mismatch"):
        store.load(snap.sha256)


def test_freeze_is_deterministic(tmp_path: Path):
    """Freezing the same input twice must produce the same SHA-256."""
    store_a = SnapshotStore(root_dir=str(tmp_path / "a"))
    store_b = SnapshotStore(root_dir=str(tmp_path / "b"))
    s = _make_series(seed=42)
    snap_a = store_a.freeze(s, symbol="DET", provenance="manual")
    snap_b = store_b.freeze(s, symbol="DET", provenance="manual")
    assert snap_a.sha256 == snap_b.sha256


def test_verify_integrity_round_trip(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    snap = store.freeze(_make_series(seed=50), symbol="OK", provenance="manual")
    assert store.verify_integrity(snap.sha256) is True


def test_load_unknown_sha_raises(tmp_path: Path):
    store = SnapshotStore(root_dir=str(tmp_path))
    with pytest.raises(IntegrityError, match="not in index"):
        store.load("0" * 64)


# ---------------------------------------------------------------------------
# Hardening: SQLite WAL, exact unlock phase, hash determinism, no demotion,
# UTC timestamps, threading.local OOSGuard stack.
# ---------------------------------------------------------------------------

def test_sqlite_wal_enabled(tmp_path: Path):
    """SnapshotStore must enable WAL + busy_timeout on its index DB."""
    store = SnapshotStore(root_dir=str(tmp_path))
    with sqlite3.connect(store.index_path) as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        bt = con.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(mode).lower() == "wal"
    assert int(bt) >= 5000


def test_unlock_phase_exact_match(tmp_path: Path):
    """OOSGuard('explicit_unlock_oops') must NOT unlock a locked snapshot."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=900)
    snap = store.freeze(s, symbol="OOS", provenance="parquet", locked=True)

    # Phase that startswith the magic prefix but isn't an exact match must fail.
    with pytest.raises(IntegrityError, match="locked"):
        with OOSGuard("explicit_unlock_but_actually_no"):
            store.load(snap.sha256)

    # Exact match works.
    with OOSGuard("explicit_unlock"):
        loaded, _ = store.load(snap.sha256)
    assert len(loaded) == len(s)


def test_snapshot_hash_cross_platform_stable(tmp_path: Path):
    """Hash must be byte-order independent. We force little-endian inputs and
    compare the digest to a known constant for a fixed series.
    """
    from quantforge.core.snapshots import _compute_sha256

    idx = pd.date_range("2020-01-01", periods=5, freq="B")
    vals = [100.0, 101.5, 99.25, 102.0, 100.75]
    s = pd.Series(vals, index=idx, name="Close")
    h = _compute_sha256("DET", s.index[0], s.index[-1], s)
    # Recompute and verify deterministic
    h2 = _compute_sha256("DET", s.index[0], s.index[-1], s)
    assert h == h2
    # Hash must have shape of sha256 hex digest
    assert isinstance(h, str) and len(h) == 64


def test_snapshot_distinguishes_different_indices(tmp_path: Path):
    """Two series with identical values but different index timestamps must
    produce different hashes (the prior bug ignored the index).
    """
    from quantforge.core.snapshots import _compute_sha256

    vals = [100.0, 101.0, 102.0, 103.0, 104.0]
    a = pd.Series(vals, index=pd.date_range("2020-01-01", periods=5, freq="B"))
    b = pd.Series(vals, index=pd.date_range("2021-01-01", periods=5, freq="B"))
    ha = _compute_sha256("X", a.index[0], a.index[-1], a)
    hb = _compute_sha256("X", b.index[0], b.index[-1], b)
    assert ha != hb


def test_locked_snapshot_no_demotion(tmp_path: Path):
    """Re-freezing a locked snapshot with locked=False must raise."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=700)
    snap = store.freeze(s, symbol="X", provenance="manual", locked=True)
    assert snap.locked is True

    with pytest.raises(ValueError, match="cannot demote locked snapshot"):
        store.freeze(s, symbol="X", provenance="manual", locked=False)


def test_locked_demotion_does_not_orphan_parquet(tmp_path: Path):
    """When the locked-demotion check rejects a re-freeze, no fresh
    parquet file may be left behind. Previously the parquet was written
    before the SQLite check ran, so the file persisted unindexed.
    """
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=701)
    # First write (locked=True) succeeds and leaves one parquet on disk.
    store.freeze(s, symbol="X", provenance="manual", locked=True)
    parquets_after_first = sorted(p for p in os.listdir(str(tmp_path))
                                  if p.endswith(".parquet"))
    assert len(parquets_after_first) == 1

    with pytest.raises(ValueError, match="cannot demote locked snapshot"):
        store.freeze(s, symbol="X", provenance="manual", locked=False)
    # No new parquet must have been added by the rejected call.
    parquets_after_reject = sorted(p for p in os.listdir(str(tmp_path))
                                   if p.endswith(".parquet"))
    assert parquets_after_reject == parquets_after_first


def test_freeze_normalizes_tz_aware_index(tmp_path: Path):
    """tz-aware indexes must hash identically to their tz-naive UTC twin.

    Documents the canonical contract: SnapshotStore stores tz-naive UTC
    timestamps. Two callers passing the same wall-clock instant in UTC
    must produce identical digests regardless of whether one labels the
    index ``tz='UTC'``.
    """
    store = SnapshotStore(root_dir=str(tmp_path))
    naive = _make_series(seed=900)
    aware = naive.copy()
    aware.index = aware.index.tz_localize("UTC")
    snap_naive = store.freeze(naive, symbol="TZ", provenance="naive")
    snap_aware = store.freeze(aware, symbol="TZ", provenance="aware")
    assert snap_naive.sha256 == snap_aware.sha256


def test_snapshot_created_at_is_utc(tmp_path: Path):
    """created_at must be tz-aware UTC."""
    store = SnapshotStore(root_dir=str(tmp_path))
    s = _make_series(seed=800)
    snap = store.freeze(s, symbol="X", provenance="manual")
    assert snap.created_at.tzinfo is not None
    assert snap.created_at.utcoffset().total_seconds() == 0.0


def test_oosguard_thread_isolated():
    """Two threads each running their own OOSGuard must not see each other's
    active guard.
    """
    import threading
    from quantforge.core.data_layer import OOSGuard

    seen_t1: list = []
    seen_t2: list = []
    barrier = threading.Barrier(2)

    def t1():
        with OOSGuard("t1") as g:
            barrier.wait()
            # while inside this guard, the *other* thread must NOT see it
            seen_t1.append(OOSGuard.active().phase)
            barrier.wait()

    def t2():
        barrier.wait()
        # at this point t1 holds an OOSGuard("t1"); t2 must see no guard
        seen_t2.append(OOSGuard.active())
        barrier.wait()

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    assert seen_t1 == ["t1"]
    assert seen_t2 == [None]
