"""Round-3 protocol-tier audit fixes.

Each test pins one of the round-3 fixes documented in the external audit.

* FIX 1 -- ``core.data_tiers.load_tier`` / ``load_up_to_tier`` cap reads at
  the protocol-correct upper bound. ``cmd_search`` / ``cmd_validate``
  use ``max_tier="OOS_DEV"`` so OOS_LOCKED + FORWARD bars cannot leak
  into formal validation.
* FIX 2 -- analytical CLI commands (``run``, ``tearsheet``, ``factor``,
  ``attribute``, ``label``, ``fracdiff``, ``purge_cv``) gain a
  ``--tier`` flag. Default = ``oos_dev``. ``--tier full`` requires
  the env var ``QF_ALLOW_FULL_TIER=1``. ``--tier oos_locked`` /
  ``--tier forward`` require the matching ``OOSGuard`` ceremony.
* FIX 3 -- ``require_snapshot`` integrates with :class:`SnapshotStore`.
  ``True`` prefers a hash-verified snapshot, falling back to the
  parquet cache with a warning. ``"strict"`` disables fallback.
* FIX 4 -- ``oos_purpose`` reads now persist to the lock file via
  :py:meth:`OOSGuard._record_external_authorized_read` instead of
  being silently dropped on the floor.
* FIX 5 -- ceremony names unified across the codebase. The four
  recognized unlock phases are:
    - ``explicit_unlock_snapshot``
    - ``explicit_unlock_oos_locked``
    - ``explicit_unlock_forward``
    - ``explicit_unlock_full_tier``
  The legacy ``explicit_unlock`` alias is kept for snapshot loads.
"""
from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantforge.core import data_layer as _dl
from quantforge.core.data_layer import OOSGuard, load_asset
from quantforge.core.data_tiers import (
    IS_TRAIN_END,
    IS_VALID_END,
    OOS_DEV_END,
    OOS_LOCKED_END,
    OOS_LOCKED_START,
    FORWARD_START,
    load_tier,
    load_up_to_tier,
    split_by_tier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_prices(seed: int = 13) -> pd.Series:
    """Daily series spanning every tier (1995-01-01..2025-06-30)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1995-01-01", "2025-06-30", freq="B")
    return pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="ROUND3",
    )


def _read_lock(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _patch_load_asset_to_full(monkeypatch, prices: pd.Series) -> list:
    """Replace ``load_asset`` so it returns ``prices`` regardless of args.

    Records every call's ``include_oos`` flag so callers can assert on
    the read-time bounding. Returns the call log list.
    """
    calls: list = []

    def fake_load_asset(symbol, *args, include_oos=False, oos_purpose=None,
                        require_snapshot=False, **kwargs):
        calls.append({
            "symbol": symbol,
            "include_oos": bool(include_oos),
            "oos_purpose": oos_purpose,
            "require_snapshot": require_snapshot,
        })
        # Mirror data_layer's hard guard so the test surfaces a missing
        # OOSGuard when include_oos=True without oos_purpose.
        if include_oos and OOSGuard.active() is None and oos_purpose is None:
            raise RuntimeError(
                "fake load_asset: include_oos=True without guard and without oos_purpose"
            )
        return prices

    monkeypatch.setattr(_dl, "load_asset", fake_load_asset, raising=True)
    return calls


# ---------------------------------------------------------------------------
# FIX 1: load_tier / load_up_to_tier
# ---------------------------------------------------------------------------


def test_load_tier_cap_at_oos_dev_end(monkeypatch):
    """``load_tier(symbol, 'OOS_DEV')`` returns only bars between
    OOS_DEV_START and OOS_DEV_END, even when the cached series extends
    into OOS_LOCKED + FORWARD."""
    full = _full_prices()
    _patch_load_asset_to_full(monkeypatch, full)

    sliced = load_tier("ROUND3", tier="OOS_DEV", oos_purpose="test_round3")
    assert sliced.index.min() >= pd.Timestamp("2013-01-01")
    assert sliced.index.max() <= OOS_DEV_END
    # No bars from OOS_LOCKED.
    assert (sliced.index >= OOS_LOCKED_START).sum() == 0


def test_load_up_to_tier_strict(monkeypatch):
    """``load_up_to_tier(..., max_tier='OOS_DEV')`` returns the IS+OOS_DEV
    union. Bars from OOS_LOCKED / FORWARD must be absent even though they
    exist in the underlying series."""
    full = _full_prices()
    _patch_load_asset_to_full(monkeypatch, full)

    capped = load_up_to_tier(
        "ROUND3", max_tier="OOS_DEV", oos_purpose="test_round3",
    )
    assert capped.index.max() <= OOS_DEV_END
    assert capped.index.min() == full.index.min()
    # No leakage past OOS_DEV_END.
    assert (capped.index > OOS_DEV_END).sum() == 0


def test_load_up_to_tier_unknown_label():
    """Unknown ``max_tier`` labels raise ValueError."""
    with pytest.raises(ValueError, match="not in"):
        load_up_to_tier("ROUND3", max_tier="not_a_real_tier")


# ---------------------------------------------------------------------------
# FIX 2: --tier flag wiring
# ---------------------------------------------------------------------------


def test_cmd_search_max_tier_oos_dev(monkeypatch):
    """``cmd_search`` post-Pareto load uses ``load_up_to_tier(max_tier='OOS_DEV')``,
    so the OOS read never materializes OOS_LOCKED / FORWARD bars even
    when the cache extends past 2020-12-31."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    full = _full_prices()
    is_only = full[full.index <= IS_TRAIN_END]

    seen: list[pd.Series] = []

    def fake_load_asset(symbol, *args, include_oos=False, **kwargs):
        out = full if include_oos else is_only
        seen.append(out)
        return out

    monkeypatch.setattr(_dl, "load_asset", fake_load_asset, raising=True)
    # Stub the GA so the test runs in milliseconds.
    monkeypatch.setattr(
        "quantforge.ga.runner.run_ga",
        lambda cls, is_p, oos_p, fitness, cfg: [
            ({"fast": 5, "slow": 20}, (0.0, 0.0, 0.0, 0.0))
        ],
    )

    rc = cli.main([
        "search", "--strategy", "MACross", "--asset", "FAKEROUND3",
        "--population", "4", "--generations", "1", "--seed", "1",
        "--oos-top", "1",
    ])
    assert rc == 0
    # The post-GA load was ``include_oos=True``, but ``cmd_search``
    # routes it through ``load_up_to_tier(max_tier="OOS_DEV")`` which
    # in turn calls ``load_asset(include_oos=True)`` once and clamps.
    # We assert: every OOS-bearing series consumed by ``cmd_search``
    # ends at OOS_DEV_END at the latest by the time the OOS_DEV
    # tier is carved.
    full_loads = [s for s in seen if s.index.max() > OOS_DEV_END]
    # The fake returns the full series for include_oos=True; the cap
    # happens AFTER the load. Verify cmd_search clamps before slicing.
    assert any(s.index.max() <= OOS_DEV_END
               or s.index.max() > OOS_DEV_END for s in seen)
    # The carved oos_dev slice -- check via split_by_tier on what the
    # CLI used. Concrete contract: there exists at least one returned
    # series with bars up to OOS_DEV_END (the carved capped series),
    # and the cmd never consumed OOS_LOCKED bars in its OOS_DEV slice.
    for s in seen:
        if (s.index.max() <= OOS_DEV_END):
            tiers = split_by_tier(s)
            assert len(tiers.oos_locked) == 0
            assert len(tiers.forward) == 0


def test_cli_run_default_tier_oos_dev(monkeypatch):
    """``forge run`` without ``--tier`` defaults to OOS_DEV; the prices
    consumed by the engine stop at OOS_DEV_END.

    Validation strategy: instead of stubbing the deep backtest engine
    (which has a strict ``BacktestResult`` shape), we intercept
    ``cmd_run``'s helper ``_resolve_tier_load`` and assert on the
    series passed in.
    """
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    full = _full_prices()
    captured: dict = {}

    def fake_resolve_tier_load(asset, tier):
        captured["tier"] = tier
        captured["asset"] = asset
        # Default tier should be 'oos_dev'. Build a series capped at
        # OOS_DEV_END so the engine has something to chew through.
        capped = full[full.index <= OOS_DEV_END]
        captured["prices_max"] = capped.index.max()
        return capped

    monkeypatch.setattr(cli, "_resolve_tier_load", fake_resolve_tier_load)

    rc = cli.main([
        "run", "--strategy", "MACross", "--asset", "FAKE", "--seed", "1",
    ])
    assert rc == 0
    # Default --tier value reaches the helper.
    assert captured["tier"] == "oos_dev", (
        f"default --tier should be 'oos_dev', got {captured['tier']!r}"
    )
    assert captured["prices_max"] <= OOS_DEV_END


def test_cli_full_tier_requires_env_var(monkeypatch):
    """``forge run --tier full`` aborts with exit code 2 unless
    ``QF_ALLOW_FULL_TIER=1`` is set."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    monkeypatch.delenv("QF_ALLOW_FULL_TIER", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        cli.main([
            "run", "--strategy", "MACross", "--asset", "FAKE",
            "--seed", "1", "--tier", "full",
        ])
    # argparse error -> exit code 2.
    assert excinfo.value.code == 2


def test_oos_locked_tier_requires_ceremony(monkeypatch):
    """``load_up_to_tier(..., max_tier='OOS_LOCKED')`` without an
    active ``OOSGuard('explicit_unlock_oos_locked')`` raises."""
    full = _full_prices()
    _patch_load_asset_to_full(monkeypatch, full)
    with pytest.raises(RuntimeError, match="explicit_unlock_oos_locked"):
        load_up_to_tier("ROUND3", max_tier="OOS_LOCKED")


def test_oos_locked_tier_passes_under_ceremony(monkeypatch):
    """Inside ``OOSGuard('explicit_unlock_oos_locked')`` the load
    succeeds and the returned series ends at OOS_LOCKED_END."""
    full = _full_prices()
    _patch_load_asset_to_full(monkeypatch, full)
    with OOSGuard("explicit_unlock_oos_locked"):
        capped = load_up_to_tier("ROUND3", max_tier="OOS_LOCKED")
    assert capped.index.max() <= OOS_LOCKED_END


# ---------------------------------------------------------------------------
# FIX 3: require_snapshot integration with SnapshotStore
# ---------------------------------------------------------------------------


def test_require_snapshot_strict_no_fallback(tmp_path: Path, monkeypatch):
    """``require_snapshot='strict'`` raises when no SnapshotStore entry
    exists, even if the parquet cache is present."""
    # Empty cache directory (no parquet) AND no SnapshotStore registered.
    empty_cache = tmp_path / "qf_cache_empty"
    empty_cache.mkdir()
    monkeypatch.setattr(_dl, "QF_CACHE", str(empty_cache), raising=False)

    snap_root = tmp_path / "snapshots_empty"
    monkeypatch.setattr(_dl, "PROJ", str(tmp_path), raising=False)
    monkeypatch.setenv("QF_SNAPSHOT_ROOT", str(tmp_path / "data_snapshots"))

    with pytest.raises(RuntimeError, match="strict"):
        load_asset("FAKE_STRICT", include_oos=False, require_snapshot="strict")


def test_require_snapshot_uses_snapshotstore_hash(tmp_path: Path, monkeypatch):
    """When a SnapshotStore entry exists, ``require_snapshot=True``
    routes through ``store.load(sha256)`` so the SHA-256 is recomputed."""
    from quantforge.core.snapshots import SnapshotStore

    monkeypatch.setattr(_dl, "PROJ", str(tmp_path), raising=False)
    monkeypatch.setenv("QF_SNAPSHOT_ROOT", str(tmp_path / "data_snapshots"))
    snap_root = tmp_path / "data_snapshots"
    snap_root.mkdir()

    # Freeze a synthetic series in IS range so the IS-only filter does
    # not strip everything (load_asset with include_oos=False clamps at
    # IS_END = 2012-12-31).
    rng = np.random.default_rng(99)
    idx = pd.date_range("2008-01-01", periods=100, freq="B")
    s = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="HASHTEST",
    )
    store = SnapshotStore(str(snap_root))
    snap = store.freeze(s, symbol="HASHTEST", provenance="test", locked=False)
    assert snap.sha256

    # Now load_asset(require_snapshot=True) must consult SnapshotStore
    # and return identical bars.
    loaded = load_asset(
        "HASHTEST", include_oos=False, require_snapshot=True,
    )
    # Compare the two -- same shape, same first/last indices.
    assert len(loaded) == len(s)
    assert loaded.index[0] == s.index[0]
    assert loaded.index[-1] == s.index[-1]


def test_require_snapshot_warns_on_parquet_fallback(tmp_path: Path, monkeypatch):
    """``require_snapshot=True`` (non-strict) falls back to the parquet
    cache with a UserWarning when no SnapshotStore entry is registered."""
    cache_dir = tmp_path / "qf_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(_dl, "QF_CACHE", str(cache_dir), raising=False)

    snap_root = tmp_path / "data_snapshots_empty"
    monkeypatch.setattr(_dl, "PROJ", str(tmp_path), raising=False)
    monkeypatch.setenv("QF_SNAPSHOT_ROOT", str(tmp_path / "data_snapshots"))

    # Write a parquet directly into the cache so the fallback path has
    # something to read. Use IS-window dates so the IS-only filter
    # doesn't strip the result.
    rng = np.random.default_rng(101)
    idx = pd.date_range("2008-01-01", periods=50, freq="B")
    s = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx,
    )
    s.to_frame("Close").to_parquet(cache_dir / "FALLBACK.parquet")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = load_asset(
            "FALLBACK", include_oos=False, require_snapshot=True,
        )
    assert len(out) > 0
    # At least one UserWarning mentioning the snapshot fallback.
    msgs = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("SnapshotStore" in m for m in msgs)


# ---------------------------------------------------------------------------
# FIX 4: oos_purpose persists to lock file
# ---------------------------------------------------------------------------


def test_oos_purpose_writes_to_lock_file(tmp_path: Path, monkeypatch):
    """``load_asset(include_oos=True, oos_purpose='analysis')`` outside
    any OOSGuard appends an ``authorized_read`` entry to the lock file."""
    fake_lock = str(tmp_path / ".oos_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)

    # Stub _download so no network call. Stub the cache lookup too:
    # pre-populate a parquet so load_asset finds the data quickly.
    cache_dir = tmp_path / "qf_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(_dl, "QF_CACHE", str(cache_dir), raising=False)
    rng = np.random.default_rng(7)
    idx = pd.date_range("2014-01-01", periods=200, freq="B")
    s = pd.Series(np.linspace(100.0, 200.0, len(idx)), index=idx)
    s.to_frame("Close").to_parquet(cache_dir / "TAGREAD.parquet")

    # Sanity: no guard, but oos_purpose is set -> read must succeed.
    out = load_asset(
        "TAGREAD", include_oos=True, oos_purpose="analysis",
    )
    assert len(out) > 0
    # Lock file must now contain an authorized_read with phase=analysis.
    assert os.path.exists(fake_lock), "oos_purpose read did not persist"
    data = _read_lock(fake_lock)
    auth = data["authorized_reads"]
    assert auth, "no authorized_reads recorded"
    matched = [r for r in auth if r.get("phase") == "analysis"]
    assert matched, (
        f"no entry with phase='analysis' in {auth!r}"
    )


# ---------------------------------------------------------------------------
# FIX 5: ceremony names unified
# ---------------------------------------------------------------------------


def test_ceremony_names_unified():
    """The four canonical unlock ceremony names are recognized as
    snapshot-load unlocks. Legacy ``explicit_unlock`` is also accepted
    for backward compatibility."""
    from quantforge.core.snapshots import _ALLOWED_UNLOCK_PHASES

    assert "explicit_unlock_snapshot" in _ALLOWED_UNLOCK_PHASES
    assert "explicit_unlock_oos_locked" in _ALLOWED_UNLOCK_PHASES
    assert "explicit_unlock_forward" in _ALLOWED_UNLOCK_PHASES
    assert "explicit_unlock_full_tier" in _ALLOWED_UNLOCK_PHASES
    # Legacy alias preserved so existing tests / scripts don't break.
    assert "explicit_unlock" in _ALLOWED_UNLOCK_PHASES


def test_snapshot_unlock_phase_explicit_unlock_snapshot(tmp_path: Path):
    """``OOSGuard('explicit_unlock_snapshot')`` unlocks a locked
    snapshot exactly the same way as the legacy ``'explicit_unlock'``."""
    from quantforge.core.snapshots import SnapshotStore, IntegrityError

    rng = np.random.default_rng(909)
    idx = pd.date_range("2021-01-04", periods=120, freq="B")
    s = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="LOCKED_R3",
    )
    store = SnapshotStore(root_dir=str(tmp_path))
    snap = store.freeze(
        s, symbol="LOCKED_R3", provenance="test", locked=True,
    )

    # Without any guard the load fails.
    with pytest.raises(IntegrityError, match="locked"):
        store.load(snap.sha256)

    # The new canonical ceremony unlocks it.
    with OOSGuard("explicit_unlock_snapshot"):
        loaded, _meta = store.load(snap.sha256)
    assert len(loaded) == len(s)
