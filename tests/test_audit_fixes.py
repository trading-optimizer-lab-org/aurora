"""Regression tests for the v1.3.1 deep-audit infrastructure / packaging /
documentation fixes.

These tests guard the structural improvements:
  * declared dependencies match what we import at runtime
  * subpackage ``__init__`` files re-export the documented public API
  * ``data_layer`` does not write inside the installed package directory
"""
from __future__ import annotations

import importlib
from pathlib import Path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _load_pyproject() -> dict:
    try:
        import tomllib  # 3.11+
    except ImportError:  # pragma: no cover - 3.10 fallback
        import tomli as tomllib  # type: ignore
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Issue 1 — pyproject.toml dependency hygiene
# ---------------------------------------------------------------------------


def test_imports_no_missing_deps():
    """Each declared base dependency should be importable from a top-level
    module of the package, and every base-imported symbol used by core
    modules should be in the dependency list.
    """
    data = _load_pyproject()
    deps = {d.split(">")[0].split("=")[0].strip() for d in data["project"]["dependencies"]}
    # core base deps that quantforge.core needs at import time
    for required in ("numpy", "pandas", "scipy", "matplotlib", "yfinance",
                     "pyarrow", "pyyaml", "numba", "pydantic"):
        assert required in deps, f"Missing base dependency: {required}"

    # symbols dropped from base deps in v1.3.1 (no runtime import)
    assert "pyportfolioopt" not in deps
    assert "click" not in deps

    extras = data["project"]["optional-dependencies"]
    assert "lumibot" in " ".join(extras["live"])
    assert "coinbase-advanced-py" in " ".join(extras["live"])
    assert "krakenex" in " ".join(extras["live"])
    assert "cvxpy" in " ".join(extras["portfolio"])
    assert "weasyprint" in " ".join(extras["report"])
    assert "mlfinlab" not in " ".join(extras["ml"])  # removed (unused)


def test_pyproject_addopts_strict_markers():
    data = _load_pyproject()
    pytest_cfg = data["tool"]["pytest"]["ini_options"]
    addopts = pytest_cfg.get("addopts", "")
    assert "--strict-markers" in addopts
    assert "--strict-config" in addopts


def test_pyproject_package_data_py_typed():
    data = _load_pyproject()
    pkg_data = data["tool"]["setuptools"]["package-data"]
    assert "py.typed" in pkg_data["quantforge"]


# ---------------------------------------------------------------------------
# Issues 2-8 — subpackage __init__ re-exports
# ---------------------------------------------------------------------------


def test_monitoring_drift_importable_from_package():
    mod = importlib.import_module("aurora.monitoring")
    for name in ("PageHinkleyDetector", "ADWINDetector", "KSDriftDetector",
                 "AutoRetrainController"):
        assert hasattr(mod, name), f"aurora.monitoring missing {name}"


def test_validation_re_exports():
    mod = importlib.import_module("aurora.validation")
    for name in ("purged_cv", "PurgedKFold", "tail_risk", "correlation_stress",
                 "scenarios", "KNOWN_CRASHES", "stress_test_all_known"):
        assert hasattr(mod, name), f"aurora.validation missing {name}"


def test_deployment_imports_all_documented():
    mod = importlib.import_module("aurora.deployment")
    # core (always available)
    for name in ("PaperBroker", "AlpacaAdapter", "IBAdapter", "CoinbaseAdapter",
                 "KrakenAdapter", "create_broker", "Order", "Position",
                 "BrokerConfig", "fixed_risk_size", "vol_target_size",
                 "kelly_size", "StrategyAllocator", "hrp_allocate",
                 "BlackLittermanModel", "ledoit_wolf_shrinkage", "oas_shrinkage",
                 "exponential_cov", "risk_parity", "compute_liquidity_profile",
                 "LiquidityAwarePortfolio", "run_preflight", "PreflightCheck",
                 "PreflightReport"):
        assert hasattr(mod, name), f"aurora.deployment missing {name}"


def test_analytics_re_exports_attribution_and_factor():
    mod = importlib.import_module("aurora.analytics")
    for name in ("attribution_by_factor", "BrinsonDecomposition",
                 "quantile_spread", "information_coefficient"):
        assert hasattr(mod, name), f"aurora.analytics missing {name}"


def test_registry_versioning_re_exports():
    mod = importlib.import_module("aurora.registry")
    for name in ("StrategyVersion", "register", "hash_strategy_code"):
        assert hasattr(mod, name), f"aurora.registry missing {name}"


def test_core_run_backtest_convenience():
    from aurora.core import run_backtest, BacktestResult, IBKR_costs
    assert callable(run_backtest)
    assert BacktestResult is not None
    assert IBKR_costs is not None


def test_top_level_convenience_exports():
    import aurora

    for name in ("run_backtest", "set_global_seed"):
        assert hasattr(aurora, name), f"aurora missing top-level {name}"
    # version comes from importlib.metadata or fallback
    assert isinstance(aurora.__version__, str) and aurora.__version__


# ---------------------------------------------------------------------------
# Issue 20 — XDG-compliant cache
# ---------------------------------------------------------------------------


def test_data_cache_does_not_write_into_site_packages(monkeypatch, tmp_path):
    """Resolving QF_CACHE under a clean env (no legacy in-tree cache) must
    yield a path outside ``site-packages``."""
    monkeypatch.delenv("QF_CACHE", raising=False)

    # Reload data_layer with a synthetic PROJ that has no legacy cache dir.
    fake_proj = tmp_path / "fake_proj"
    (fake_proj / "quantforge").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    import importlib

    data_layer = importlib.import_module("aurora.core.data_layer")
    monkeypatch.setattr(data_layer, "PROJ", str(fake_proj))
    resolved = data_layer._resolve_qf_cache()
    site_pkg_markers = ("site-packages", "dist-packages")
    norm = resolved.replace("\\", "/").lower()
    for marker in site_pkg_markers:
        assert marker not in norm, (
            f"QF_CACHE resolved into a packaged install location: {resolved!r}"
        )
    # And explicit env override always wins
    monkeypatch.setenv("QF_CACHE", str(tmp_path / "explicit"))
    assert data_layer._resolve_qf_cache() == str(tmp_path / "explicit")
