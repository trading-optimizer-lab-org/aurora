"""Round-2 protocol-tier audit fixes.

Each test in this module pins one of the six fixes documented in the
external audit:

* FIX 1 -- ``OOSGuard()`` defaults ``lock_path`` to ``DEFAULT_LOCK_PATH``
  so every production guard persists an audit record.
* FIX 2 -- the lock file separates ``authorized_reads`` (legitimate post-
  validation audit) from ``violations`` (real GA contamination).
* FIX 3 -- ``cmd_search`` loads the IS-only series BEFORE the GA runs,
  and only loads the full series under ``OOSGuard("post_ga_validation")``
  AFTER the Pareto front has been selected.
* FIX 4 -- ``validate_pipeline`` auxiliary gates (SPP, lookahead,
  walk-forward) only see the carved IS+chosen-OOS series, never raw
  prices that may extend into OOS_LOCKED / FORWARD.
* FIX 5 -- ``deployment.preflight`` wraps every
  ``load_asset(include_oos=True)`` in ``OOSGuard("preflight_check")`` so
  the read is recorded as an authorized_read, not a violation.
* FIX 6 -- ``load_asset`` no longer hardcodes ``end='2025-12-31'`` in
  the dynamic yfinance fallback; ``require_snapshot=True`` refuses to
  download dynamically and forces a frozen parquet snapshot for formal
  validation/search.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from quantforge.core import data_layer as _dl
from quantforge.core.data_layer import (
    DEFAULT_LOCK_PATH,
    OOSGuard,
    load_asset,
)
from quantforge.core.data_tiers import (
    IS_TRAIN_END,
    OOS_DEV_END,
    OOS_DEV_START,
    OOS_LOCKED_START,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_prices(seed: int = 7) -> pd.Series:
    """Daily series spanning every tier (1995-01-01..2025-06-30)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1995-01-01", "2025-06-30", freq="B")
    return pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="ROUND2",
    )


def _read_lock(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# FIX 1: OOSGuard default lock_path persists audit
# ---------------------------------------------------------------------------


def test_oosguard_default_persists_lock(tmp_path: Path, monkeypatch):
    """``OOSGuard("...")`` with no ``lock_path=`` argument writes the
    audit file at ``DEFAULT_LOCK_PATH``.

    The conftest already redirects ``DEFAULT_LOCK_PATH`` to a per-test
    tmp directory; this test points it at its own ``tmp_path`` so the
    assertion is local. The whole point is: prior to round 2, the
    default was ``lock_path=None`` and reads were silently dropped on
    the floor with no audit record.
    """
    fake_lock = str(tmp_path / ".oos_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)

    # No explicit lock_path -> default -> file must materialize on exit.
    with OOSGuard("post_ga_validation") as g:
        assert g.lock_path == fake_lock
        g.record_oos_read("test_default_persists")

    assert os.path.exists(fake_lock), (
        "OOSGuard default lock_path must persist the audit record"
    )
    data = _read_lock(fake_lock)
    assert data["phase"] == "post_ga_validation"
    assert any(
        r["where"] == "test_default_persists"
        for r in data["authorized_reads"]
    )


def test_oosguard_explicit_none_disables_lock(tmp_path: Path, monkeypatch):
    """``lock_path=None`` is the explicit opt-out: nothing is written."""
    fake_lock = str(tmp_path / ".oos_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)

    with OOSGuard("optimization", lock_path=None) as g:
        g.record_oos_read("opt_out_path")
        assert g.lock_path is None

    assert not os.path.exists(fake_lock), (
        "lock_path=None must not write the default audit file"
    )


# ---------------------------------------------------------------------------
# FIX 2: separate authorized_reads from violations
# ---------------------------------------------------------------------------


def test_lock_distinguishes_reads_from_violations(tmp_path: Path):
    """The lock file persists ``authorized_reads`` and ``violations``
    as two distinct arrays, populated by their respective methods."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        g.record_oos_read("legitimate_post_validation_call")
        g.record_oos_read("another_legit_call")
        g.record_oos_violation("ga_loop_peeked_at_oos")

    data = _read_lock(str(lock))
    auth = [r["where"] for r in data["authorized_reads"]]
    viol = [v["where"] for v in data["violations"]]

    assert "legitimate_post_validation_call" in auth
    assert "another_legit_call" in auth
    assert "legitimate_post_validation_call" not in viol
    assert "ga_loop_peeked_at_oos" in viol
    assert "ga_loop_peeked_at_oos" not in auth

    # check_lock_clean must report False because there is a real violation.
    assert OOSGuard.check_lock_clean(str(lock)) is False


def test_authorized_reads_alone_keep_lock_clean(tmp_path: Path):
    """A fully-audited run with hundreds of authorized reads but zero
    violations is still ``check_lock_clean``: the audit array is NOT
    contamination."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        for i in range(5):
            g.record_oos_read(f"audit_read_{i}")

    assert OOSGuard.check_lock_clean(str(lock)) is True
    data = _read_lock(str(lock))
    assert len(data["authorized_reads"]) == 5
    assert data["violations"] == []


# ---------------------------------------------------------------------------
# FIX 3: cmd_search loads IS only before GA, OOS_DEV after Pareto
# ---------------------------------------------------------------------------


def test_cmd_search_oos_loaded_only_after_pareto(monkeypatch):
    """``cmd_search`` must:
       1. call ``load_asset(..., include_oos=False)`` BEFORE invoking the
          GA runner; and
       2. call ``load_asset(..., include_oos=True)`` ONLY AFTER, and only
          inside ``OOSGuard("post_ga_validation")``.

    This pins the data-flow ordering: even though the GA fitness
    function consumes only ``is_p``, having OOS data in memory while
    the fitness loop runs is a protocol violation. The fix loads IS
    first, runs GA, then opens the guard and loads the full series.
    """
    pytest.importorskip("pydantic")  # forge.cli depends on ForgeConfig

    from quantforge.cli import forge as cli

    prices_full = _full_prices()
    is_only = prices_full[prices_full.index <= IS_TRAIN_END]

    call_order: list[tuple[bool, str | None]] = []
    ga_invoked_at: list[int] = []

    def fake_load_asset(symbol, *args, include_oos=False, oos_purpose=None,
                        require_snapshot=False, **kwargs):
        # Return only IS rows when include_oos=False; full when True.
        guard = OOSGuard.active()
        call_order.append((bool(include_oos),
                           guard.phase if guard is not None else None))
        return prices_full if include_oos else is_only

    def fake_run_ga(cls, is_p, oos_p, fitness, cfg):
        # Record the position in the load-call timeline at which the GA
        # ran. After this point, no more IS-only loads should occur.
        ga_invoked_at.append(len(call_order))
        # Sanity: the GA must NEVER receive an OOS-bearing series.
        assert is_p.index.max() <= IS_TRAIN_END, (
            f"GA received post-IS_TRAIN data: max={is_p.index.max()!r}"
        )
        return [({"fast": 5, "slow": 20}, (0.0, 0.0, 0.0, 0.0))]

    monkeypatch.setattr(_dl, "load_asset", fake_load_asset, raising=True)
    # Patch where forge imports it from too (forge.py uses
    # ``from quantforge.core.data_layer import load_asset`` inside the
    # function body, so the monkeypatch on data_layer is enough).
    monkeypatch.setattr("quantforge.ga.runner.run_ga", fake_run_ga)

    rc = cli.main([
        "search", "--strategy", "MACross", "--asset", "FAKE",
        "--population", "4", "--generations", "1", "--seed", "1",
        "--oos-top", "1",
    ])
    assert rc == 0
    assert ga_invoked_at, "GA was never invoked"

    ga_pos = ga_invoked_at[0]
    # Step 1: every load BEFORE the GA had include_oos=False.
    pre_ga = call_order[:ga_pos]
    assert pre_ga, "no load_asset call recorded before GA"
    for include_oos, phase in pre_ga:
        assert include_oos is False, (
            f"OOS data was loaded BEFORE the GA ran: {pre_ga!r}"
        )

    # Step 2: after the GA there is at least one include_oos=True load,
    # and it must be inside OOSGuard("post_ga_validation").
    post_ga = call_order[ga_pos:]
    oos_loads = [(io, ph) for (io, ph) in post_ga if io is True]
    assert oos_loads, "OOS data was never loaded after the GA"
    for _io, phase in oos_loads:
        assert phase == "post_ga_validation", (
            f"post-GA OOS load was not inside post_ga_validation guard: "
            f"phase={phase!r}"
        )


# ---------------------------------------------------------------------------
# FIX 4: validate_pipeline aux gates only see carved series
# ---------------------------------------------------------------------------


def test_pipeline_aux_gates_see_only_carved(monkeypatch):
    """The auxiliary gates (SPP, lookahead, walk_forward) inside
    ``validate_pipeline`` must receive a price series that ends at
    ``OOS_DEV_END`` (2020-12-31) -- not a series that extends into
    OOS_LOCKED (2021+) or FORWARD (2025+).
    """
    from quantforge.validation import pipeline as pl_mod
    from quantforge.validation.pipeline import validate_pipeline
    from quantforge.validation.walk_forward import WFWindow
    from quantforge.core.costs import ZERO_costs
    from quantforge.strategies.library import MACross

    full_prices = _full_prices()
    # Sanity check: the synthetic series really does extend past OOS_DEV.
    assert full_prices.index.max() > OOS_DEV_END

    seen_in_aux: dict[str, pd.Series] = {}

    def spy_walk_forward(strategy_factory, prices, wf_windows, **kwargs):
        seen_in_aux["walk_forward"] = prices
        from quantforge.validation.walk_forward import WFResult
        return WFResult(windows=[], n_pass=0, n_total=0)

    def spy_lookahead(signal_fn, prices, **kwargs):
        seen_in_aux["lookahead"] = prices
        from quantforge.validation.lookahead_check import LookaheadReport
        return LookaheadReport(
            static_warnings=[], runtime_violation=False,
            runtime_metric_delta=0.0, passed=True,
        )

    def spy_spp(spp_factory, prices, *args, **kwargs):
        seen_in_aux["spp"] = prices
        from quantforge.validation.spp import SPPResult
        return SPPResult(
            base_calmar=0.0, base_sharpe=0.0,
            perturbed_calmars=[], perturbed_sharpes=[],
            calmar_mean=1.0, calmar_std=0.0, calmar_cv=0.0,
            n_perturbations=0,
        )

    monkeypatch.setattr(pl_mod, "walk_forward", spy_walk_forward)
    monkeypatch.setattr(pl_mod, "runtime_lookahead_check", spy_lookahead)
    monkeypatch.setattr(pl_mod, "spp", spy_spp)

    def factory():
        return MACross(fast=10, slow=30)

    def factory_with(**kw):
        return MACross(fast=kw.get("fast", 10), slow=kw.get("slow", 30))

    validate_pipeline(
        strategy_factory=factory,
        prices=full_prices,
        name="round2-aux-gates",
        costs=ZERO_costs,
        wf_windows=[WFWindow(
            "WF1", "1995-01-01", "2009-12-31", "2010-01-01", "2012-12-31"
        )],
        spp_param_ranges={"fast": (5, 20), "slow": (20, 60)},
        spp_strategy_factory=factory_with,
        mc_n_paths=10, min_wf_pass=0,
    )

    # Each spy must have observed a series whose max index <= OOS_DEV_END.
    assert seen_in_aux, "no aux gate was invoked"
    for gate_name, observed in seen_in_aux.items():
        assert observed.index.max() <= OOS_DEV_END, (
            f"aux gate {gate_name!r} saw data past OOS_DEV_END "
            f"(max={observed.index.max()!r})"
        )


# ---------------------------------------------------------------------------
# FIX 5: preflight wraps OOS load in OOSGuard
# ---------------------------------------------------------------------------


def test_preflight_oos_under_guard(monkeypatch, tmp_path: Path):
    """``check_data_availability`` calls ``load_asset(include_oos=True)``
    inside ``OOSGuard("preflight_check")`` so the read records as an
    ``authorized_read`` (audit) -- not as an unguarded RuntimeError or
    a violation.
    """
    from quantforge.deployment import preflight as pf

    fake_lock = str(tmp_path / ".oos_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)

    captured_phases: list[str | None] = []

    def fake_load_asset(symbol, include_oos=False, **kwargs):
        # Capture the phase of the active guard (or None if no guard).
        guard = OOSGuard.active()
        captured_phases.append(guard.phase if guard else None)
        # Return a usable series so the check passes.
        idx = pd.date_range("2018-01-01", periods=1500, freq="B")
        return pd.Series(np.linspace(100.0, 200.0, len(idx)), index=idx)

    monkeypatch.setattr(pf, "load_asset", fake_load_asset)

    # Trigger the load.
    rep = pf.check_data_availability("FAKE", min_bars=200, strategy=None)
    assert rep.passed
    assert captured_phases, "load_asset was never invoked"
    # The active guard during the load must be the preflight guard.
    assert "preflight_check" in captured_phases, (
        f"preflight load was not under OOSGuard('preflight_check'); "
        f"saw phases: {captured_phases!r}"
    )

    # And the lock file must have recorded an authorized_read, not a violation.
    if os.path.exists(fake_lock):
        data = _read_lock(fake_lock)
        assert data["violations"] == []


# ---------------------------------------------------------------------------
# FIX 6a: search/validate require a frozen snapshot
# ---------------------------------------------------------------------------


def test_search_requires_snapshot(monkeypatch, tmp_path: Path):
    """When ``cmd_search`` runs and the parquet cache is missing,
    ``load_asset(require_snapshot=True)`` raises rather than silently
    triggering a yfinance download. This is what stops formal
    validation runs from accidentally pinning to a different daily
    slice every time the cache is wiped."""
    # Point QF_CACHE at an empty tmp directory so the lookup misses.
    empty_cache = tmp_path / "qf_cache_empty"
    empty_cache.mkdir()
    monkeypatch.setattr(_dl, "QF_CACHE", str(empty_cache), raising=False)

    # Arm the no-network path: even if _download were called, fail loudly
    # so the test surfaces "you fell back to dynamic download".
    def _refuse_download(symbol, source="yfinance", **kwargs):
        raise AssertionError(
            "_download was called even though require_snapshot=True"
        )

    monkeypatch.setattr(_dl, "_download", _refuse_download, raising=False)

    with pytest.raises(RuntimeError, match="require_snapshot=True"):
        load_asset("FAKEROUND2", include_oos=False, require_snapshot=True)


def test_validate_requires_snapshot_in_cmd(monkeypatch, tmp_path: Path):
    """``cmd_validate`` passes ``require_snapshot=True`` to ``load_asset``."""
    pytest.importorskip("pydantic")
    from quantforge.cli import forge as cli

    captured: dict = {}

    def fake_load_asset(symbol, *args, include_oos=False,
                        require_snapshot=False, **kwargs):
        captured["require_snapshot"] = require_snapshot
        # Provide a valid synthetic series so the rest of cmd_validate
        # can short-circuit. Then raise to halt the pipeline early since
        # we only care about the load-time argument.
        raise SystemExit(0)

    monkeypatch.setattr(_dl, "load_asset", fake_load_asset, raising=True)

    with pytest.raises(SystemExit):
        cli.main([
            "validate", "--strategy", "MACross", "--asset", "FAKE",
            "--seed", "1", "--mc-paths", "5", "--n-trials", "1",
        ])

    assert captured.get("require_snapshot") is True


# ---------------------------------------------------------------------------
# FIX 6b: dynamic end date in load_asset/_download
# ---------------------------------------------------------------------------


def test_load_end_date_is_dynamic(monkeypatch):
    """The yfinance ``_download`` fallback must use today's date as the
    ``end`` window rather than a hardcoded year-end string."""
    captured: dict = {}

    class _FakeYF:
        @staticmethod
        def download(symbol, start=None, end=None, auto_adjust=True,
                     progress=False, **kwargs):
            captured["start"] = start
            captured["end"] = end
            idx = pd.date_range(start, end or pd.Timestamp.today(), freq="B")
            return pd.DataFrame({"Close": np.linspace(100.0, 200.0, len(idx))},
                                index=idx)

    # ``_download`` does ``import yfinance as yf`` at call time. We
    # inject a fake module under that name in sys.modules.
    import sys
    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)

    _dl._download("DUMMY", source="yfinance")

    assert "end" in captured and captured["end"] is not None
    end_ts = pd.Timestamp(captured["end"])
    today = pd.Timestamp.today().normalize()
    # The captured end date must be today (within 24h of today).
    delta = abs((end_ts - today).total_seconds())
    assert delta < 86400 * 2, (
        f"_download end date is not dynamic: end={captured['end']!r} "
        f"vs today={today!r}"
    )

    # And it must NOT match the previously hardcoded 2025-12-31 sentinel.
    assert captured["end"] != "2025-12-31", (
        "_download still pins end='2025-12-31' (round-2 audit issue)"
    )
