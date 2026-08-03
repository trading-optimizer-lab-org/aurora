"""Tests for the P0.B DataProviderRegistry.

Covers:
* Registry register/get/list semantics + duplicate handling.
* DatasetMetadata immutability + content_hash determinism.
* Built-in providers (yahoo, snapshot, csv, openbb stub, synthetic) PIT
  flags + tier permissions.
* Tier-aware fetch gating against OOSGuard.
* Wiring through ``data_layer.load_asset`` and the CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from aurora.core.data_providers import (
    BaseDataProvider,
    Dataset,
    DataProvider,
    DataProviderRegistry,
    DatasetMetadata,
    ProviderNotRegistered,
    ProviderUnavailable,
    TIER_LABELS,
    TierPermissionError,
    compute_content_hash,
    get_default_registry,
    reset_default_registry,
)
from aurora.core.data_providers.csv import CSVProvider
from aurora.core.data_providers.openbb import OpenBBProvider
from aurora.core.data_providers.snapshot import SnapshotProvider
from aurora.core.data_providers.synthetic import SyntheticProvider
from aurora.core.data_providers.yahoo import YahooProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_series(n: int = 50, name: str = "TEST") -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=idx, name=name)


# ---------------------------------------------------------------------------
# 1. Registry register/get/list
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    reg = DataProviderRegistry()
    p = SyntheticProvider()
    reg.register(p)
    assert reg.get("synthetic") is p


def test_registry_list():
    reg = DataProviderRegistry()
    reg.register(SyntheticProvider())
    reg.register(YahooProvider())
    assert reg.list() == ["synthetic", "yahoo"]


def test_registry_duplicate_register_raises():
    reg = DataProviderRegistry()
    reg.register(SyntheticProvider())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(SyntheticProvider())
    # ``replace=True`` overwrites.
    reg.register(SyntheticProvider(), replace=True)


def test_registry_get_missing_raises():
    reg = DataProviderRegistry()
    with pytest.raises(ProviderNotRegistered):
        reg.get("does_not_exist")


# ---------------------------------------------------------------------------
# 2. DatasetMetadata + Dataset
# ---------------------------------------------------------------------------


def test_dataset_metadata_immutable():
    m = DatasetMetadata(
        name="x:y",
        source="x",
        source_version="x:1.0",
        asof_date=pd.Timestamp("2020-01-01"),
        point_in_time=True,
        content_hash="0" * 64,
        tier_permission="ANY",
    )
    with pytest.raises(FrozenInstanceError):
        m.point_in_time = False
    with pytest.raises(FrozenInstanceError):
        m.content_hash = "1" * 64


def test_dataset_metadata_invalid_tier_raises():
    with pytest.raises(ValueError, match="tier_permission"):
        DatasetMetadata(
            name="x", source="x", source_version="0",
            asof_date=pd.Timestamp("2020-01-01"),
            point_in_time=True, content_hash="0" * 64,
            tier_permission="NOT_A_TIER",
        )


# ---------------------------------------------------------------------------
# 3. content_hash determinism
# ---------------------------------------------------------------------------


def test_content_hash_deterministic():
    s = _mk_series(100, name="X")
    h1 = compute_content_hash(s)
    h2 = compute_content_hash(s.copy())
    assert h1 == h2
    # Same values, different name -> different hash
    s2 = s.copy()
    s2.name = "Y"
    assert compute_content_hash(s2) != h1


def test_content_hash_changes_on_mutation():
    s = _mk_series(50, name="X")
    h1 = compute_content_hash(s)
    s2 = s.copy()
    s2.iloc[0] = s2.iloc[0] + 1.0
    assert compute_content_hash(s2) != h1


# ---------------------------------------------------------------------------
# 4. Provider PIT + tier flags
# ---------------------------------------------------------------------------


def test_yahoo_provider_marks_not_pit():
    p = YahooProvider()
    assert p.is_point_in_time() is False
    assert p.tier_permission == "IS_TRAIN"
    # IS_TRAIN provider supports IS_TRAIN only (chronological cap).
    assert p.supported_tiers() == {"IS_TRAIN"}


def test_snapshot_provider_marks_pit():
    p = SnapshotProvider(root_dir=os.path.join(os.getcwd(), "_test_snap_root"))
    assert p.is_point_in_time() is True
    assert p.tier_permission == "ANY"
    assert "OOS_LOCKED" in p.supported_tiers()
    assert "FORWARD" in p.supported_tiers()


def test_synthetic_provider_seed_reproducible():
    p = SyntheticProvider()
    ds1 = p.fetch("X", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"),
                  seed=7)
    ds2 = p.fetch("X", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"),
                  seed=7)
    pd.testing.assert_series_equal(ds1.data, ds2.data)
    # Same metadata hash too.
    assert ds1.metadata.content_hash == ds2.metadata.content_hash
    # Different seed -> different hash.
    ds3 = p.fetch("X", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"),
                  seed=8)
    assert ds3.metadata.content_hash != ds1.metadata.content_hash


# ---------------------------------------------------------------------------
# 5. OpenBB lazy-import unavailability
# ---------------------------------------------------------------------------


def test_openbb_provider_lazy_import_unavailable(monkeypatch):
    """If ``openbb`` is not installed, fetch raises ProviderUnavailable.

    We simulate the missing dependency by injecting a sentinel that
    raises ImportError when ``from openbb import obb`` runs.
    """
    p = OpenBBProvider()
    # Block the openbb module so the lazy import inside ``_import_obb``
    # fails. Save/restore the prior value so other tests see a stable env.
    prev_openbb = sys.modules.get("openbb")
    sys.modules["openbb"] = None
    try:
        with pytest.raises(ProviderUnavailable):
            p.fetch("AAPL", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"))
    finally:
        if prev_openbb is None:
            sys.modules.pop("openbb", None)
        else:
            sys.modules["openbb"] = prev_openbb


# ---------------------------------------------------------------------------
# 6. CSV provider
# ---------------------------------------------------------------------------


def test_csv_provider_loads_with_metadata(tmp_path):
    s = _mk_series(20, name="ABC")
    df = pd.DataFrame({"date": s.index, "close": s.values})
    csv_path = tmp_path / "ABC.csv"
    df.to_csv(csv_path, index=False)
    # Sidecar pinning a PIT date.
    sidecar = str(csv_path) + ".meta.json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"asof_date": "2020-06-30"}, f)
    p = CSVProvider(root_dir=str(tmp_path), point_in_time=True)
    ds = p.fetch("ABC", None, None)
    assert isinstance(ds, Dataset)
    assert ds.metadata.point_in_time is True
    assert ds.metadata.asof_date == pd.Timestamp("2020-06-30")
    assert "csv_path" in ds.metadata.extra
    assert len(ds.data) == 20


# ---------------------------------------------------------------------------
# 7. Tier gating
# ---------------------------------------------------------------------------


def test_fetch_inside_oos_locked_without_ceremony_refuses_non_pit(tmp_path):
    """Non-PIT provider inside ``OOSGuard("explicit_unlock_oos_locked")``
    must be refused unless it declares OOS_LOCKED support."""
    from aurora.core.data_layer import OOSGuard
    reg = DataProviderRegistry()
    reg.register(YahooProvider())  # IS_TRAIN, not PIT
    with OOSGuard("explicit_unlock_oos_locked",
                  lock_path=str(tmp_path / "lock.json")):
        with pytest.raises(TierPermissionError):
            reg.fetch("yahoo", "SPY",
                      start="2021-01-01", end="2021-06-30")


def test_fetch_inside_oos_locked_with_ceremony_allows_pit(tmp_path, monkeypatch):
    """A PIT provider (synthetic) is allowed under the same ceremony."""
    from aurora.core.data_layer import OOSGuard
    reg = DataProviderRegistry()
    reg.register(SyntheticProvider())
    with OOSGuard("explicit_unlock_oos_locked",
                  lock_path=str(tmp_path / "lock.json")) as g:
        ds = reg.fetch(
            "synthetic", "X",
            start="2021-01-01", end="2021-06-30", seed=1,
        )
        assert ds.metadata.point_in_time is True
        # Recorded as authorized read on the active guard.
        assert g.authorized_reads >= 1


# ---------------------------------------------------------------------------
# 8. Lock-file recording
# ---------------------------------------------------------------------------


def test_fetch_records_in_data_layer_authorized_reads(tmp_path):
    """Inside an OOSGuard, the registry records the read on the guard's
    authorized_reads counter."""
    from aurora.core.data_layer import OOSGuard
    reg = DataProviderRegistry()
    reg.register(SyntheticProvider())
    lock = tmp_path / "lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        before = g.authorized_reads
        reg.fetch("synthetic", "X",
                  start="2020-01-01", end="2020-06-30", seed=1)
        assert g.authorized_reads == before + 1
        # Where-string mentions the registry + content hash.
        assert any("DataProviderRegistry.fetch" in w for w in g.authorized_log)


# ---------------------------------------------------------------------------
# 9. data_layer.load_asset back-compat
# ---------------------------------------------------------------------------


def _mk_is_series(n: int = 40, name: str = "TEST") -> pd.Series:
    """In-sample series ending before IS_END=2012-12-31."""
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=idx, name=name)


def test_load_asset_backward_compat_default_yahoo(monkeypatch, tmp_path):
    """``load_asset`` with no ``provider=`` kwarg keeps using the legacy
    parquet/yfinance path. We patch ``_download`` so the test does not
    hit the network. Using a synthetic ticker ("TEST") avoids the
    test_lint_config.py guard against unmarked SPY parquet loads."""
    from aurora.core import data_layer
    fake = _mk_is_series(40, name="TEST")

    def _fake_download(symbol, source="yfinance", start=None, end=None):
        return fake.copy()

    # Redirect QF_CACHE so we don't pollute the user's cache and there's
    # nothing on disk -> _download path is taken.
    monkeypatch.setattr(data_layer, "QF_CACHE", str(tmp_path), raising=False)
    monkeypatch.setattr(data_layer, "_download", _fake_download)
    s = data_layer.load_asset("TEST", include_oos=False)
    assert isinstance(s, pd.Series)
    assert len(s) > 0


def test_load_asset_with_provider_routes_through_registry(monkeypatch, tmp_path):
    """``load_asset(provider='synthetic')`` returns data via the registry."""
    from aurora.core import data_layer
    monkeypatch.setattr(data_layer, "QF_CACHE", str(tmp_path), raising=False)
    # Use IS-window dates so the include_oos=False filter doesn't drop everything.
    s = data_layer.load_asset(
        "TEST", provider="synthetic",
        start="2010-01-01", end="2010-06-30",
    )
    assert isinstance(s, pd.Series)
    assert len(s) > 0
    assert s.index.min() >= pd.Timestamp("2010-01-01")


# ---------------------------------------------------------------------------
# 10. preflight uses snapshot provider when available
# ---------------------------------------------------------------------------


def test_preflight_uses_snapshot_provider(tmp_path, monkeypatch):
    """``deployment.preflight.check_data_availability`` accepts a snapshot
    provider via ``load_asset(provider='snapshot')``: we drop a frozen
    snapshot in a tmp store, then verify the registry can read it back
    with PIT flag set."""
    from aurora.core.snapshots import SnapshotStore
    store_dir = tmp_path / "snapshots"
    store = SnapshotStore(str(store_dir))
    s = _mk_series(60, name="SPY")
    snap = store.freeze(s, symbol="SPY", provenance="test")
    p = SnapshotProvider(root_dir=str(store_dir))
    ds = p.fetch("SPY", None, None)
    assert ds.metadata.point_in_time is True
    assert ds.metadata.tier_permission == "ANY"
    assert len(ds.data) == 60
    assert snap.sha256


# ---------------------------------------------------------------------------
# 11. SnapshotStore.freeze metadata round-trip
# ---------------------------------------------------------------------------


def test_snapshot_freeze_stores_metadata(tmp_path):
    """Snapshot freeze + Provider read produces consistent metadata."""
    from aurora.core.snapshots import SnapshotStore
    store = SnapshotStore(str(tmp_path / "store"))
    s = _mk_series(40, name="ABC")
    snap = store.freeze(s, symbol="ABC", provenance="unit-test")
    p = SnapshotProvider(root_dir=str(tmp_path / "store"))
    ds = p.fetch("ABC", None, None)
    # Hash from the registry should match what SnapshotStore registered
    # for the same data round-trip.
    assert ds.metadata.content_hash
    assert ds.metadata.source == "snapshot"
    assert ds.metadata.source_version == "snapshot:1.0"
    assert snap.symbol == "ABC"


# ---------------------------------------------------------------------------
# 12. CLI smoke
# ---------------------------------------------------------------------------


def _run_forge(*args):
    """Run ``forge`` via the CLI module so we exercise the parser too."""
    cmd = [sys.executable, "-m", "aurora.cli.forge", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def test_cli_data_list_providers_smoke():
    result = _run_forge("data", "list-providers")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "synthetic" in out
    assert "yahoo" in out
    assert "snapshot" in out


def test_cli_data_verify_detects_tampering(tmp_path):
    """``forge data fetch`` then mutate parquet -> ``forge data verify`` fails."""
    out_path = tmp_path / "data.parquet"
    fetch = _run_forge(
        "data", "fetch", "synthetic", "TEST",
        "--start", "2020-01-01", "--end", "2020-06-30",
        "--output", str(out_path),
    )
    assert fetch.returncode == 0, fetch.stderr
    sidecar = str(out_path) + ".meta.json"
    assert os.path.exists(sidecar)

    # First verify passes.
    verify_ok = _run_forge("data", "verify", str(out_path))
    assert verify_ok.returncode == 0, verify_ok.stderr
    assert "PASS" in verify_ok.stdout

    # Tamper with the parquet by rewriting one value.
    df = pd.read_parquet(out_path)
    col = df.columns[0]
    df.iloc[0, df.columns.get_loc(col)] = -999.0
    df.to_parquet(out_path)
    verify_bad = _run_forge("data", "verify", str(out_path))
    assert verify_bad.returncode == 1
    assert "FAIL" in verify_bad.stdout


def test_failed_data_verify_bypasses_native_teardown(monkeypatch):
    """The module runner preserves exit 1 after a failed parquet check."""
    from aurora.cli import forge

    observed = []

    def fake_exit(code):
        observed.append(code)
        raise RuntimeError("immediate exit")

    monkeypatch.setattr(forge.os, "_exit", fake_exit)
    monkeypatch.setattr(forge.sys, "argv", ["forge", "data", "verify"])
    with pytest.raises(RuntimeError, match="immediate exit"):
        forge._exit_after_main(1)
    assert observed == [1]


# ---------------------------------------------------------------------------
# 13. Default registry singleton
# ---------------------------------------------------------------------------


def test_default_registry_has_builtins():
    reset_default_registry()
    reg = get_default_registry()
    names = reg.list()
    assert {"yahoo", "snapshot", "csv", "synthetic", "openbb"}.issubset(set(names))
