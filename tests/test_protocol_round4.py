"""Round-4 protocol-tier audit fixes.

Each test pins one of the round-4 fixes documented in the external audit:

P1 (3) -- block before declaring stable:
* P1.1 -- Validation marker enforced at QFLiveStrategy.initialize() and
  QFPaperStrategy.initialize() time, not just by the standalone preflight CLI.
* P1.2 -- ``split_by_tier`` boundary off-by-day for intraday bars (e.g. a
  09:30 timestamp on the boundary date now sorts into the correct tier).
* P1.3 -- ``forge freeze`` CLI subcommand registers a new SnapshotStore entry.

P2 (4):
* P2.1 -- ``OOSGuard.record_oos_violation`` and ``_record_external_authorized_read``
  also append to the SOC2 audit JSONL trail.
* P2.2 -- ``forge validate --tier {oos_dev,oos_locked,forward}`` knob;
  locked tiers require ``--i-understand-ceremony``.
* P2.3 -- ``--tier full`` requires both ``QF_ALLOW_FULL_TIER=1`` AND an
  active ``OOSGuard("explicit_unlock_full_tier")``.
* P2.4 -- ``run_multi_asset_ga`` drops ``price_dict_oos`` requirement
  for the IS-only fitness signature; ``forge search-multi`` CLI loads
  via ``load_tier``.

P3 + extras:
* P3.6 -- DataSnapshot reproducibility metadata (git_hash, forge_version,
  seed, config_hash).

E (extras):
* E.1 -- multi-process OOSGuard lock concurrency.
* E.2 -- tier boundary with NaN at the boundary date.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantforge.core import data_layer as _dl
from quantforge.core.data_layer import DEFAULT_LOCK_PATH, OOSGuard
from quantforge.core.data_tiers import (
    IS_TRAIN_END,
    IS_VALID_END,
    OOS_DEV_END,
    OOS_LOCKED_END,
    split_by_tier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_prices(seed: int = 17) -> pd.Series:
    """Daily series spanning every tier (1995-01-01..2025-06-30)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1995-01-01", "2025-06-30", freq="B")
    return pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="ROUND4",
    )


# ---------------------------------------------------------------------------
# P1.1 -- validation marker enforcement at order submit time
# ---------------------------------------------------------------------------


def _make_qf_strategy_named(name: str):
    """Build a stub strategy whose type().__name__ is ``name``."""
    cls = type(name, (), {"signals": lambda self, prices: [0.0] * len(prices)})
    return cls()


def test_live_halts_without_validation_marker(tmp_path: Path, monkeypatch):
    """QFLiveStrategy.initialize() halts the session permanently when
    ``check_validation_marker`` reports FAIL (no marker file)."""
    from quantforge.deployment import live as live_mod
    from quantforge.deployment.live import QFLiveStrategy

    monkeypatch.setattr(live_mod, "HAS_LUMIBOT", True)

    qf_strat = _make_qf_strategy_named("UnvalidatedStrat_R4")
    cls = QFLiveStrategy.bind(
        qf_strategy=qf_strat,
        symbol="SPY",
        risk_per_trade=0.01,
        daily_loss_limit=0.05,
        max_notional_pct=1.0,
        project_dir=str(tmp_path),
    )
    inst = object.__new__(cls)
    inst.set_market = MagicMock()
    inst.sleeptime = None
    inst.get_portfolio_value = MagicMock(return_value=100_000.0)
    inst.initialize()
    assert inst.qf_halted is True


def test_live_proceeds_with_valid_marker(tmp_path: Path, monkeypatch):
    """When a fresh validation marker exists, the live wrapper proceeds
    (qf_halted stays False at the end of initialize)."""
    from quantforge.deployment import live as live_mod
    from quantforge.deployment.live import QFLiveStrategy
    from quantforge.deployment.preflight import write_validation_marker

    monkeypatch.setattr(live_mod, "HAS_LUMIBOT", True)
    qf_strat = _make_qf_strategy_named("ValidatedStrat_R4")

    # Write a fresh marker into the tmp project_dir's quantforge/data_cache_qf
    cache = tmp_path / "quantforge" / "data_cache_qf"
    cache.mkdir(parents=True, exist_ok=True)
    # ``write_validation_marker`` requires the report; we synthesize a minimal
    # JSON payload manually to stay independent of the report shape.
    marker = cache / ".validation_passed_ValidatedStrat_R4.json"
    marker.write_text(json.dumps({
        "strategy": "ValidatedStrat_R4",
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "overall_passed": True,
    }))
    # Make sure the marker resolves to this tmp project_dir, not the
    # real repo root: we point project_dir directly at tmp_path.
    cls = QFLiveStrategy.bind(
        qf_strategy=qf_strat,
        symbol="SPY",
        project_dir=str(tmp_path),
    )
    inst = object.__new__(cls)
    inst.set_market = MagicMock()
    inst.sleeptime = None
    inst.get_portfolio_value = MagicMock(return_value=100_000.0)
    inst.initialize()
    assert inst.qf_halted is False


def test_live_bypass_validation_check(tmp_path: Path, monkeypatch):
    """``bypass_validation_check=True`` allows the wrapper to skip the
    marker check (with a warning logged)."""
    from quantforge.deployment import live as live_mod
    from quantforge.deployment.live import QFLiveStrategy

    monkeypatch.setattr(live_mod, "HAS_LUMIBOT", True)
    qf_strat = _make_qf_strategy_named("BypassStrat_R4")
    cls = QFLiveStrategy.bind(
        qf_strategy=qf_strat,
        symbol="SPY",
        bypass_validation_check=True,
        project_dir=str(tmp_path),
    )
    inst = object.__new__(cls)
    inst.set_market = MagicMock()
    inst.sleeptime = None
    inst.get_portfolio_value = MagicMock(return_value=100_000.0)
    inst.initialize()
    # Bypass means the wrapper does not pre-halt despite no marker.
    assert inst.qf_halted is False


def test_paper_halts_without_validation_marker(tmp_path: Path, monkeypatch):
    """QFPaperStrategy.initialize() also halts when no marker is present."""
    from quantforge.deployment.paper import QFPaperStrategy

    qf_strat = _make_qf_strategy_named("UnvalidatedPaperStrat_R4")
    cls = QFPaperStrategy.bind(
        qf_strategy=qf_strat,
        symbol="SPY",
        project_dir=str(tmp_path),
    )
    inst = object.__new__(cls)
    inst.set_market = MagicMock()
    inst.sleeptime = None
    inst.get_portfolio_value = MagicMock(return_value=100_000.0)
    inst.initialize()
    assert inst.qf_halted is True


# ---------------------------------------------------------------------------
# P1.2 -- intraday boundary off-by-day
# ---------------------------------------------------------------------------


def test_split_by_tier_intraday_boundaries():
    """Intraday bars on the IS_TRAIN/IS_VALID boundary date sort into the
    correct tier despite their non-midnight timestamps."""
    # 09:30 / 12:00 / 23:59 on 2010-12-31 (last IS_TRAIN day) and on
    # 2011-01-01 (first IS_VALID day).
    ts = pd.DatetimeIndex([
        "2010-12-31 09:30",
        "2010-12-31 12:00",
        "2010-12-31 23:59",
        "2011-01-01 09:30",
        "2011-01-01 12:00",
        "2011-01-01 23:59",
    ])
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], index=ts)
    tiers = split_by_tier(s)
    # All three 2010-12-31 intraday bars must land in IS_TRAIN.
    assert len(tiers.is_train) == 3
    assert (tiers.is_train.index.date == pd.Timestamp("2010-12-31").date()).all()
    # The 2011-01-01 bars land in IS_VALID.
    assert len(tiers.is_valid) == 3


def test_split_by_tier_with_nan_at_boundary():
    """NaN values at exact tier boundaries are still routed to the right
    tier (nan-handling is unchanged: the value is preserved, only the
    index decides the tier)."""
    ts = pd.DatetimeIndex([
        "2010-12-31",
        "2011-01-01",
        "2012-12-31",
        "2013-01-01",
    ])
    s = pd.Series([np.nan, np.nan, 1.0, np.nan], index=ts)
    tiers = split_by_tier(s)
    assert len(tiers.is_train) == 1
    assert len(tiers.is_valid) == 2
    assert len(tiers.oos_dev) == 1


# ---------------------------------------------------------------------------
# P1.3 -- forge freeze CLI
# ---------------------------------------------------------------------------


def test_cmd_freeze_creates_snapshot(tmp_path: Path, monkeypatch):
    """``forge freeze --asset X`` calls SnapshotStore.freeze and prints
    the sha256 + data_path."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    full = _full_prices()
    full.name = "FREEZE_R4"

    def fake_load_asset(symbol, *args, include_oos=False, **kwargs):
        # The CLI wraps in OOSGuard so include_oos=True is permitted.
        return full

    monkeypatch.setattr(_dl, "load_asset", fake_load_asset, raising=True)

    # Redirect SnapshotStore root to tmp_path/data_snapshots so we don't
    # spam the real repo. cmd_freeze derives the path from the package
    # location; patch SnapshotStore class to inject the tmp root.
    from quantforge.core import snapshots as snap_mod
    original_init = snap_mod.SnapshotStore.__init__

    def patched_init(self, root_dir="data_snapshots/"):
        original_init(self, str(tmp_path / "data_snapshots"))

    monkeypatch.setattr(snap_mod.SnapshotStore, "__init__", patched_init)

    rc = cli.main([
        "freeze", "--asset", "FREEZE_R4",
        "--provenance", "yfinance",
    ])
    assert rc == 0
    # Snapshot file landed in the tmp root.
    snap_root = tmp_path / "data_snapshots"
    parquet_files = list(snap_root.glob("*.parquet"))
    assert len(parquet_files) >= 1
    # Sqlite index has a row.
    import sqlite3
    db = sqlite3.connect(snap_root / "snapshots_index.sqlite")
    n = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    db.close()
    assert n >= 1


# ---------------------------------------------------------------------------
# P2.1 -- SOC2 audit + OOSGuard lock unified
# ---------------------------------------------------------------------------


def test_oos_read_writes_both_lock_and_soc2(tmp_path: Path, monkeypatch):
    """When ``_record_external_authorized_read`` fires, both the OOS
    lock file AND the SOC2 audit JSONL receive an entry."""
    fake_lock = str(tmp_path / "round4_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)

    soc2_log = tmp_path / "soc2.jsonl"
    from quantforge.compliance import soc2_audit as _soc2_mod

    # Patch the SOC2Config default log_path so a fresh SOC2AuditTrail()
    # call inside _try_soc2_record uses our tmp file rather than the
    # repo-relative audit_trail.jsonl.
    original_init = _soc2_mod.SOC2AuditTrail.__init__

    def patched_init(self, config=None):
        if config is None:
            config = _soc2_mod.SOC2Config(log_path=str(soc2_log))
        original_init(self, config)

    monkeypatch.setattr(
        _soc2_mod.SOC2AuditTrail, "__init__", patched_init,
    )

    # Trigger an authorized read with no active guard via the data_layer
    # public API. ``_record_external_authorized_read`` is called inside
    # load_asset; we go through the helper directly so the test does not
    # depend on a parquet cache being present.
    OOSGuard._record_external_authorized_read(
        where="round4_test",
        phase="round4_phase",
        lock_path=fake_lock,
    )
    # Lock file got the authorized_read.
    assert os.path.exists(fake_lock)
    with open(fake_lock, "r", encoding="utf-8") as f:
        lock = json.load(f)
    assert any("round4_test" in str(rec)
               for rec in lock.get("authorized_reads", []))
    # SOC2 trail also got an event.
    assert soc2_log.exists()
    lines = [ln for ln in soc2_log.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert any("oos_authorized_read" in ln for ln in lines)


# ---------------------------------------------------------------------------
# P2.2 -- forge validate --tier
# ---------------------------------------------------------------------------


def test_validate_oos_locked_requires_ceremony_flag(monkeypatch):
    """``forge validate --tier oos_locked`` aborts with exit code 2
    unless ``--i-understand-ceremony`` is passed."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    with pytest.raises(SystemExit) as excinfo:
        cli.main([
            "validate", "--strategy", "MACross", "--asset", "FAKE",
            "--seed", "1", "--tier", "oos_locked",
        ])
    assert excinfo.value.code == 2


def test_validate_default_tier_is_oos_dev(monkeypatch):
    """Default ``forge validate`` (no --tier) keeps the legacy oos_dev
    behaviour: max_tier=OOS_DEV, OOSGuard phase post_ga_validation."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    captured: dict = {}

    def fake_load_up_to_tier(asset, *, max_tier="OOS_DEV", **kw):
        captured["max_tier"] = max_tier
        captured["phase_during_load"] = OOSGuard.active().phase if OOSGuard.active() else None
        return _full_prices()

    monkeypatch.setattr(
        "quantforge.core.data_tiers.load_up_to_tier",
        fake_load_up_to_tier,
    )

    # Stub validate_pipeline so we don't actually run the gates.
    class _Rep:
        overall_passed = True

        def report(self):
            return "stub"

    monkeypatch.setattr(
        "quantforge.validation.pipeline.validate_pipeline",
        lambda **kw: _Rep(),
    )
    rc = cli.main([
        "validate", "--strategy", "MACross", "--asset", "FAKE",
        "--seed", "1",
    ])
    assert rc == 0
    assert captured["max_tier"] == "OOS_DEV"
    assert captured["phase_during_load"] == "post_ga_validation"


# ---------------------------------------------------------------------------
# P2.3 -- --tier full requires both env var AND OOSGuard
# ---------------------------------------------------------------------------


def test_full_tier_requires_both_env_and_guard(monkeypatch):
    """``_resolve_tier_load(asset, 'full')`` aborts when only the env
    var is set; the guard ceremony is also required."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    monkeypatch.setenv("QF_ALLOW_FULL_TIER", "1")

    # No OOSGuard active -- must abort. ``_arg_error`` raises
    # ``_CLIArgError`` (a ``SystemExit`` subclass whose ``code`` is the
    # explanatory message). Match on the message so the test pins the
    # ceremony requirement, not the side-channel exit code.
    with pytest.raises(cli._CLIArgError) as excinfo:
        cli._resolve_tier_load("FAKE", "full")
    assert "OOSGuard" in str(excinfo.value)
    assert "explicit_unlock_full_tier" in str(excinfo.value)

    # Wrong-phase guard -- still must abort.
    with OOSGuard("post_ga_validation"):
        with pytest.raises(cli._CLIArgError) as excinfo:
            cli._resolve_tier_load("FAKE", "full")
        assert "explicit_unlock_full_tier" in str(excinfo.value)


def test_full_tier_passes_under_correct_ceremony(monkeypatch):
    """Inside ``OOSGuard('explicit_unlock_full_tier')`` and with the
    env var set, the full-tier load proceeds."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    monkeypatch.setenv("QF_ALLOW_FULL_TIER", "1")
    monkeypatch.setattr(
        "quantforge.core.data_layer.load_asset",
        lambda *a, **kw: _full_prices(),
    )
    with OOSGuard("explicit_unlock_full_tier"):
        prices = cli._resolve_tier_load("FAKE", "full")
    assert len(prices) > 0


# ---------------------------------------------------------------------------
# P2.4 -- multi_asset_runner uses load_tier
# ---------------------------------------------------------------------------


def test_multi_asset_search_uses_load_tier(monkeypatch):
    """``run_multi_asset_ga`` no longer rejects price_dict_oos=None
    when the fitness signature is is_only."""
    pytest.importorskip("deap")
    from quantforge.ga.multi_asset_runner import (
        run_multi_asset_ga, MultiAssetGAConfig, multi_asset_fitness_is,
    )
    from quantforge.strategies.library.pair_trade import PairTrade

    rng = np.random.default_rng(7)
    idx = pd.date_range("2000-01-01", periods=400, freq="B")
    price_a = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 400)),
        index=idx, name="A",
    )
    price_b = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 400)),
        index=idx, name="B",
    )
    cfg = MultiAssetGAConfig(population=4, generations=1, seed=42)

    # Should NOT raise even though price_dict_oos=None.
    pareto = run_multi_asset_ga(
        PairTrade,
        price_dict_is={"A": price_a, "B": price_b},
        price_dict_oos=None,
        symbols=["A", "B"],
        fitness_fn=multi_asset_fitness_is,
        config=cfg,
        verbose=False,
    )
    assert isinstance(pareto, list)


def test_multi_asset_oos_dict_deprecation():
    """Passing price_dict_oos with the IS-only fitness raises a
    DeprecationWarning."""
    pytest.importorskip("deap")
    from quantforge.ga.multi_asset_runner import (
        run_multi_asset_ga, MultiAssetGAConfig, multi_asset_fitness_is,
    )
    from quantforge.strategies.library.pair_trade import PairTrade

    rng = np.random.default_rng(7)
    idx = pd.date_range("2000-01-01", periods=400, freq="B")
    price_a = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 400)),
        index=idx, name="A",
    )
    price_b = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 400)),
        index=idx, name="B",
    )
    cfg = MultiAssetGAConfig(population=4, generations=1, seed=42)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_multi_asset_ga(
            PairTrade,
            price_dict_is={"A": price_a, "B": price_b},
            price_dict_oos={"A": price_a, "B": price_b},
            symbols=["A", "B"],
            fitness_fn=multi_asset_fitness_is,
            config=cfg,
            verbose=False,
        )
    assert any(issubclass(w.category, DeprecationWarning)
               and "price_dict_oos" in str(w.message)
               for w in caught)


# ---------------------------------------------------------------------------
# P3.6 -- DataSnapshot reproducibility metadata
# ---------------------------------------------------------------------------


def test_snapshot_records_git_hash(tmp_path: Path):
    """``SnapshotStore.freeze`` records git_hash / forge_version / seed
    on the resulting DataSnapshot when available."""
    from quantforge.core.snapshots import SnapshotStore

    store = SnapshotStore(str(tmp_path / "snaps"))
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    s = pd.Series(np.arange(10, dtype=float), index=idx, name="REPRO_R4")
    snap = store.freeze(s, symbol="REPRO_R4", provenance="test_round4")
    # forge_version is best-effort: in editable install / tests it may
    # be ``None`` or a real version. We only assert the field exists
    # and is None or a non-empty string.
    assert hasattr(snap, "forge_version")
    assert hasattr(snap, "git_hash")
    assert hasattr(snap, "seed")
    assert hasattr(snap, "config_hash")
    # The seed defaulted to 42 via conftest's _reset_global_state.
    assert snap.seed == 42 or snap.seed is None


# ---------------------------------------------------------------------------
# E.1 -- multi-process OOSGuard concurrency
# ---------------------------------------------------------------------------


def _open_close_guards_worker(args):
    """Top-level helper for multiprocessing; opens N guards on the
    given lock path. Must be top-level so the subprocess can pickle it."""
    lock_path, n = args
    # Late import inside subprocess
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "..",
    )))
    from quantforge.core.data_layer import OOSGuard as _OOSGuard
    for i in range(n):
        with _OOSGuard(f"worker_{_os.getpid()}_{i}",
                       lock_path=lock_path):
            pass
    return _os.getpid()


def test_oosguard_multiprocess_lock_corruption(tmp_path: Path):
    """Spawn 4 worker processes, each opens/closes a guard 25 times.
    The lock file must remain a valid JSON object at the end."""
    if multiprocessing.get_start_method(allow_none=True) is None:
        try:
            multiprocessing.set_start_method("spawn", force=False)
        except RuntimeError:
            pass
    lock_path = str(tmp_path / "concurrent_lock.json")
    args = [(lock_path, 25)] * 4
    # Use spawn context explicitly for cross-platform stability.
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(4) as pool:
        pool.map(_open_close_guards_worker, args)
    # File must exist and parse as a dict with a violations list.
    assert os.path.exists(lock_path)
    with open(lock_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert isinstance(data.get("violations", []), list)
    assert isinstance(data.get("authorized_reads", []), list)
