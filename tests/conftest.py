"""Shared pytest fixtures for QuantForge tests.

Centralized synthetic data and journal builders. Tests should prefer these
over local helpers to keep generated series consistent and reduce duplication.

Test data contract
------------------
Tests use synthetic Geometric Brownian Motion (GBM) data by default, generated
from a seeded ``numpy.random.default_rng(42)`` so runs are deterministic and
reproducible across machines and CI environments.

Tests requiring live or cached vendor data (yfinance pulls, the SPY parquet
cache under ``quantforge/data_cache_qf/``, broker APIs, etc.) MUST be marked
with ``@pytest.mark.integration`` and MUST skip when the underlying data file
or network resource is unavailable. The CI fast suite runs ``-m "not slow and
not integration"``, so any unmarked live-data test would silently break CI on
machines without that cache.

Conventions:

- ``synthetic_prices_daily``: 500 business days, ~12.5% annualized drift,
  ~16% annualized vol. Use for daily-frequency strategy tests.
- ``synthetic_ohlcv_minute``: 1000 1-min bars with realistic OHLCV envelope.
  Use for intraday / microstructure tests.
- ``temp_journal_db``: throwaway SQLite-backed ``TradeJournal`` per test.

When a test genuinely needs live SPY parquet, follow this pattern::

    @pytest.mark.integration
    def test_with_live_spy(...):
        path = Path(...)
        if not path.exists():
            pytest.skip("SPY parquet cache missing")
"""
from __future__ import annotations

import importlib.util
import logging
import multiprocessing
import os
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _prime_mutmut_runtime() -> None:
    """Import mutmut safely before generated trampolines need it."""
    if not os.environ.get("MUTANT_UNDER_TEST"):
        return
    original = multiprocessing.set_start_method

    def safe_set_start_method(method, *args, **kwargs):
        try:
            return original(method, *args, **kwargs)
        except RuntimeError as exc:
            if "context has already been set" in str(exc):
                return None
            raise

    multiprocessing.set_start_method = safe_set_start_method
    try:
        import mutmut.__main__  # noqa: F401
    finally:
        multiprocessing.set_start_method = original


def _bootstrap_layout_b_mutmut() -> None:
    """Make the mutmut copy importable for QuantForge's flat package layout."""
    root = Path(__file__).resolve().parents[1]
    init_file = root / "__init__.py"
    if root.name != "mutants" or "quantforge" in sys.modules or not init_file.exists():
        return
    spec = importlib.util.spec_from_file_location(
        "quantforge",
        init_file,
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["quantforge"] = module
    spec.loader.exec_module(module)


_prime_mutmut_runtime()
_bootstrap_layout_b_mutmut()
import pytest


# Module-level optional imports cached once per test session. Repeating
# ``import torch`` per-test pays the import cost on every fixture invocation
# (and torch is not cheap). Cache None when missing.
try:
    import torch as _torch  # type: ignore
except ImportError:
    _torch = None  # type: ignore[assignment]

try:
    from aurora.core import seed as _qf_seed  # type: ignore
except ImportError:  # pragma: no cover - core ships with the package
    _qf_seed = None  # type: ignore[assignment]

try:
    from aurora.ga import fitness as _ga_fitness  # type: ignore
except ImportError:  # pragma: no cover - ga extras may be missing
    _ga_fitness = None  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Hypothesis profiles (roadmap item #11 -- property-based testing)
# --------------------------------------------------------------------------
#
# Three profiles. Per-test ``@settings(max_examples=...)`` decorators OVERRIDE
# the profile, so this only kicks in for tests that don't set their own.
#
#   - ``dev`` (default): max_examples=15, no deadline. Fast local feedback.
#   - ``ci``: max_examples=25, derandomize=True, fixed database. Reproducible.
#   - ``thorough``: max_examples=200, no deadline. Stress sweep for nightly.
#
# Select with: ``pytest --hypothesis-profile=ci`` or ``HYPOTHESIS_PROFILE=ci``.
try:
    from hypothesis import HealthCheck as _HC, settings as _hyp_settings

    _hyp_settings.register_profile(
        "dev",
        max_examples=15,
        deadline=None,
        suppress_health_check=[_HC.too_slow, _HC.function_scoped_fixture],
    )
    _hyp_settings.register_profile(
        "ci",
        max_examples=25,
        deadline=None,
        derandomize=True,
        suppress_health_check=[_HC.too_slow, _HC.function_scoped_fixture],
    )
    _hyp_settings.register_profile(
        "thorough",
        max_examples=200,
        deadline=None,
        suppress_health_check=[_HC.too_slow, _HC.function_scoped_fixture],
    )
    import os as _os

    _hyp_settings.load_profile(_os.environ.get("HYPOTHESIS_PROFILE", "dev"))
except ImportError:  # pragma: no cover - hypothesis is optional
    pass


@pytest.fixture(autouse=True)
def _isolate_default_oos_lock(tmp_path_factory, monkeypatch):
    """Redirect ``DEFAULT_LOCK_PATH`` to a per-session tmp directory.

    Round-2 of the protocol audit makes ``OOSGuard`` persist its audit
    record to ``DEFAULT_LOCK_PATH`` by default. Without this fixture,
    every test that constructs ``OOSGuard("...")`` (no explicit
    lock_path) would mutate the developer's real ``~/.cache/quantforge``
    file -- noisy, racy, and a cross-test contamination vector.

    This fixture redirects the constant for the duration of each test
    so the round-2 default writes land in a throwaway directory.
    """
    try:
        from aurora.core import data_layer as _dl
    except ImportError:  # pragma: no cover - core ships with the package
        return
    tmp_dir = tmp_path_factory.mktemp("oos_lock_iso")
    fake_lock = str(tmp_dir / ".oos_lock.json")
    monkeypatch.setattr(_dl, "DEFAULT_LOCK_PATH", fake_lock, raising=False)


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset module-level mutable globals between tests.

    Prevents state pollution when tests run in suite order:
      * RNG seeds (python ``random``, numpy, torch) -> deterministic per-test.
      * ``quantforge`` logger ``propagate`` flag -> caplog can intercept records
        even after :func:`aurora.core.logging.configure_logging` ran.
      * ``_DEPRECATION_WARNED`` flags in :mod:`quantforge.ga.fitness` -> tests
        that assert on the warning don't see "already warned".
    """
    # --- pre-test: seed everything deterministically ---
    random.seed(42)
    np.random.seed(42)
    if _torch is not None:
        _torch.manual_seed(42)
        if _torch.cuda.is_available():  # pragma: no cover - no GPU on CI
            _torch.cuda.manual_seed_all(42)
    # Reset quantforge GLOBAL_SEED so any module that re-seeds via
    # get_seed() (e.g. LSTMForecaster._build) sees a deterministic value
    # instead of whatever a previous test left there.
    if _qf_seed is not None:
        _qf_seed.GLOBAL_SEED = 42

    # --- pre-test: ensure quantforge logger propagates so caplog sees records ---
    qf_logger = logging.getLogger("aurora")
    qf_logger.propagate = True

    # --- pre-test: reset deprecation-warning flags ---
    if _ga_fitness is not None and hasattr(_ga_fitness, "_DEPRECATION_WARNED"):
        for k in list(_ga_fitness._DEPRECATION_WARNED.keys()):
            _ga_fitness._DEPRECATION_WARNED[k] = False

    yield
    # The pre-test branch already forces ``qf_logger.propagate = True`` for
    # every test, so a post-test reassignment to the same value is a no-op.
    # Removed to avoid implying that something inside the test could
    # otherwise leave the propagate flag in a different state.


@pytest.fixture
def synthetic_prices_daily() -> pd.Series:
    """Daily synthetic close series with 500 business days.

    Deterministic via seed=42. Geometric Brownian-ish, drift 5bps, sigma 100bps.
    Index name omitted; series name is 'close'.
    """
    rng = np.random.default_rng(42)
    n = 500
    returns = rng.normal(0.0005, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(returns))
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(prices, index=idx, name="close")


@pytest.fixture
def synthetic_ohlcv_minute() -> pd.DataFrame:
    """Minute-bar OHLCV DataFrame with 1000 bars.

    Columns: open, high, low, close, volume. Deterministic via seed=42.
    """
    rng = np.random.default_rng(42)
    n = 1000
    rets = rng.normal(0.0, 0.0005, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    # open is previous close (with first bar = first close)
    open_ = np.concatenate([[close[0]], close[:-1]])
    # high/low envelope around open/close
    spread = np.abs(rng.normal(0.0, 0.0008, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    # ensure non-negative volume
    volume = np.abs(rng.normal(10000.0, 2000.0, n)).astype(float)

    idx = pd.date_range("2020-01-01 09:30", periods=n, freq="1min")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


@pytest.fixture
def temp_journal_db(tmp_path):
    """Yield a TradeJournal pointing at a fresh sqlite file under tmp_path."""
    from aurora.registry.journal import TradeJournal

    db = tmp_path / "test_journal.db"
    j = TradeJournal(db_path=str(db))
    yield j
    # tmp_path teardown is handled by pytest; nothing else to release.
