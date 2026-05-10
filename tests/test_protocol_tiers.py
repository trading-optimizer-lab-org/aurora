"""Tests pinning the protocol-tier behaviour added in the data-tiers refactor.

Coverage:
  * `split_by_tier` boundary correctness
  * `validate_pipeline` defaults to OOS_DEV (never sees OOS_LOCKED / FORWARD)
  * `validate_pipeline(oos_tier="OOS_LOCKED")` requires the matching guard
  * `cmd_search` defaults to IS_TRAIN, with --is-tier=is_all opt-in
  * `cmd_run` (and other analysis commands) work with full prices when
    wrapped in OOSGuard("post_validation_analysis")
  * `pyproject.toml` lists every v2/v3 package
"""
from __future__ import annotations

import io
import os
import sys
import tomllib
import contextlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.cli import forge as cli
from aurora.core.costs import ZERO_costs
from aurora.core.data_layer import OOSGuard

# CLI-driven tests only run when pydantic is importable; ``forge`` loads
# ``quantforge.core.config`` (which requires pydantic) before any subcommand.
_pydantic_required = pytest.importorskip.__self__ if False else None
try:
    import pydantic  # noqa: F401
    _HAVE_PYDANTIC = True
except ImportError:
    _HAVE_PYDANTIC = False
from aurora.core.data_tiers import (
    FORWARD_START,
    IS_TRAIN_END,
    IS_VALID_END,
    IS_VALID_START,
    OOS_DEV_END,
    OOS_DEV_START,
    OOS_LOCKED_END,
    OOS_LOCKED_START,
    split_by_tier,
)
from aurora.strategies.library import MACross
from aurora.validation.pipeline import validate_pipeline
from aurora.validation.walk_forward import WFWindow


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------


def _full_prices(seed: int = 11) -> pd.Series:
    """Daily series spanning every tier (1995-01-01..2025-06-30)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1995-01-01", "2025-06-30", freq="B")
    return pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, len(idx))),
        index=idx, name="SYNTH",
    )


def _patch_load_asset(monkeypatch, prices: pd.Series):
    """Patch every ``load_asset`` call site used by the CLI."""
    fake = lambda *a, **kw: prices
    monkeypatch.setattr(
        "aurora.core.data_layer.load_asset", fake, raising=True,
    )
    import aurora.deployment.preflight as pf
    monkeypatch.setattr(pf, "load_asset", fake, raising=True)


# ---------------------------------------------------------------------------
# 1. split_by_tier boundary correctness
# ---------------------------------------------------------------------------


def test_split_by_tier_boundaries():
    """Every tier slice respects its inclusive [lo, hi] window."""
    prices = _full_prices()
    out = split_by_tier(prices)

    assert out.is_train.index.max() <= IS_TRAIN_END
    assert out.is_valid.index.min() >= IS_VALID_START
    assert out.is_valid.index.max() <= IS_VALID_END
    assert out.oos_dev.index.min() >= OOS_DEV_START
    assert out.oos_dev.index.max() <= OOS_DEV_END
    assert out.oos_locked.index.min() >= OOS_LOCKED_START
    assert out.oos_locked.index.max() <= OOS_LOCKED_END
    assert out.forward.index.min() >= FORWARD_START

    # disjoint partition: total == input length
    total = (
        len(out.is_train)
        + len(out.is_valid)
        + len(out.oos_dev)
        + len(out.oos_locked)
        + len(out.forward)
    )
    assert total == len(prices)


# ---------------------------------------------------------------------------
# 2. validate_pipeline defaults to OOS_DEV ONLY
# ---------------------------------------------------------------------------


def test_validate_pipeline_uses_oos_dev_only():
    """Default pipeline invocation must slice OOS to OOS_DEV (2013-2020).

    Capture the strategy.signals call arg seen during OOS evaluation: if
    OOS_LOCKED data leaks in, the index would extend past 2020-12-31.
    """
    prices = _full_prices()
    seen_oos: list[pd.Series] = []

    real_signals = MACross().signals

    def factory():
        s = MACross()
        orig = s.signals

        def spy(p):
            # the OOS run is the SECOND ``run_backtest`` call inside the
            # pipeline (IS first, OOS second). Capture every input so we
            # can later identify the largest-index call as OOS.
            seen_oos.append(p)
            return orig(p)

        s.signals = spy
        return s

    wf = [
        WFWindow("WF1", "1995-01-01", "2007-12-31", "2008-01-01", "2010-12-31"),
        WFWindow("WF2", "1995-01-01", "2009-12-31", "2010-01-01", "2012-12-31"),
    ]
    rep = validate_pipeline(
        factory, prices, name="default-oos-dev",
        costs=ZERO_costs, wf_windows=wf, mc_n_paths=20, min_wf_pass=0,
    )
    # The OOS run is the one whose first index >= OOS_DEV_START.
    oos_calls = [s for s in seen_oos if s.index.min() >= OOS_DEV_START]
    assert oos_calls, "validate_pipeline never invoked the OOS leg"
    for oos in oos_calls:
        assert oos.index.max() <= OOS_DEV_END, (
            f"OOS slice leaked past OOS_DEV_END: {oos.index.max()!r}"
        )


def test_validate_pipeline_oos_locked_requires_ceremony():
    """oos_tier='OOS_LOCKED' without the matching OOSGuard raises."""
    prices = _full_prices()

    def factory():
        return MACross()

    with pytest.raises(RuntimeError, match="explicit_unlock_oos_locked"):
        validate_pipeline(
            factory, prices, name="locked-no-ceremony",
            costs=ZERO_costs, mc_n_paths=20, min_wf_pass=0,
            oos_tier="OOS_LOCKED",
        )

    # With the right guard the validation runs (we don't need it to PASS,
    # only to not raise on the gate). Use min_wf_pass=0 + ZERO_costs.
    with OOSGuard("explicit_unlock_oos_locked"):
        rep = validate_pipeline(
            factory, prices, name="locked-with-ceremony",
            costs=ZERO_costs, mc_n_paths=20, min_wf_pass=0,
            wf_windows=[WFWindow(
                "WF1", "1995-01-01", "2009-12-31", "2010-01-01", "2012-12-31"
            )],
            oos_tier="OOS_LOCKED",
        )
        assert rep.strategy_name == "locked-with-ceremony"


def test_validate_pipeline_forward_requires_ceremony():
    """oos_tier='FORWARD' without OOSGuard('explicit_unlock_forward') raises."""
    prices = _full_prices()

    with pytest.raises(RuntimeError, match="explicit_unlock_forward"):
        validate_pipeline(
            lambda: MACross(), prices, name="forward-no-ceremony",
            costs=ZERO_costs, mc_n_paths=20, min_wf_pass=0,
            oos_tier="FORWARD",
        )


# ---------------------------------------------------------------------------
# 3. cmd_search default tier semantics
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_PYDANTIC, reason="pydantic missing")
def test_cmd_search_uses_is_train_default(monkeypatch, capsys):
    """`forge search` with no flag passes the IS_TRAIN slice to the GA."""
    prices = _full_prices()
    captured: dict = {}

    def fake_run_ga(cls, is_p, oos_p, fitness, cfg):
        captured["is_p"] = is_p
        captured["oos_p"] = oos_p
        # return a single-individual Pareto front so the rest of the
        # command body completes without exercising real fitness.
        return [({"fast": 5, "slow": 20}, (0.0, 0.0, 0.0, 0.0))]

    monkeypatch.setattr("aurora.ga.runner.run_ga", fake_run_ga)
    _patch_load_asset(monkeypatch, prices)

    rc = cli.main([
        "search", "--strategy", "MACross", "--asset", "FAKE",
        "--population", "4", "--generations", "1", "--seed", "1",
        "--skip-oos",
    ])
    assert rc == 0
    is_p = captured["is_p"]
    assert is_p.index.max() <= IS_TRAIN_END, (
        f"default cmd_search must use IS_TRAIN, got max={is_p.index.max()!r}"
    )


@pytest.mark.skipif(not _HAVE_PYDANTIC, reason="pydantic missing")
def test_cmd_search_is_all_with_flag(monkeypatch, capsys):
    """`forge search --is-tier is_all` extends the GA fit to IS_VALID."""
    prices = _full_prices()
    captured: dict = {}

    def fake_run_ga(cls, is_p, oos_p, fitness, cfg):
        captured["is_p"] = is_p
        return [({"fast": 5, "slow": 20}, (0.0, 0.0, 0.0, 0.0))]

    monkeypatch.setattr("aurora.ga.runner.run_ga", fake_run_ga)
    _patch_load_asset(monkeypatch, prices)

    rc = cli.main([
        "search", "--strategy", "MACross", "--asset", "FAKE",
        "--population", "4", "--generations", "1", "--seed", "1",
        "--skip-oos", "--is-tier", "is_all",
    ])
    assert rc == 0
    is_p = captured["is_p"]
    # IS_ALL spans past 2010-12-31 up to 2012-12-31
    assert is_p.index.max() <= IS_VALID_END
    assert is_p.index.max() > IS_TRAIN_END


# ---------------------------------------------------------------------------
# 4. cmd_run still works with full prices under the new guard
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_PYDANTIC, reason="pydantic missing")
def test_cli_run_works_with_full_prices_under_guard(monkeypatch, capsys):
    """cmd_run wraps the load_asset call in OOSGuard("post_validation_analysis")
    so a full-history series can be backtested without the include_oos guard
    error."""
    prices = _full_prices()
    _patch_load_asset(monkeypatch, prices)

    rc = cli.main([
        "run", "--strategy", "MACross", "--asset", "FAKE",
        "--costs", "zero", "--seed", "42",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Strategy: MACross on FAKE" in out


# ---------------------------------------------------------------------------
# 5. pyproject lists every v2/v3 package
# ---------------------------------------------------------------------------


_REQUIRED_V2_V3_PACKAGES = [
    "aurora.altdata",
    "aurora.signals",
    "aurora.infra",
    "aurora.experimental",
    "aurora.marketdata",
    "aurora.markets",
    "aurora.risk",
    "aurora.execution",
    "aurora.compliance",
    "aurora.dataeng",
]


def test_pyproject_lists_all_v2_v3_packages():
    """Every v2/v3 package directory must appear in the pyproject packages
    list and the matching package-dir mapping."""
    pyproject = (
        Path(__file__).resolve().parent.parent / "pyproject.toml"
    )
    assert pyproject.exists(), pyproject
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    setuptools_cfg = data["tool"]["setuptools"]
    packages = setuptools_cfg["packages"]
    package_dir = setuptools_cfg["package-dir"]
    for name in _REQUIRED_V2_V3_PACKAGES:
        assert name in packages, f"{name} missing from packages list"
        assert name in package_dir, f"{name} missing from package-dir map"
