"""Aurora - quant research engine with militant anti-overfit pipeline."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
try:
    __version__ = _pkg_version("aurora")
except PackageNotFoundError:
    # Source-checkout fallback: a fixed string here would clash with the
    # next real release in pyproject.toml when someone imports the
    # package directly from a checkout. ``"0.0.0+local"`` (a valid PEP
    # 440 local-version identifier) makes the source-mode case obvious.
    __version__ = "0.0.0+local"

# Convenience top-level re-exports. Optional-dep paths are wrapped in
# try/except so an import failure on one symbol does not poison the package.
__all__: list[str] = ["__version__"]

try:
    from aurora.core.engine import run_backtest  # noqa: F401
    from aurora.core.seed import set_global_seed  # noqa: F401
    from aurora.core.costs import IBKR_costs  # noqa: F401
    __all__.extend(["IBKR_costs", "run_backtest", "set_global_seed"])
except ImportError:  # pragma: no cover - core deps should always be present
    pass

try:
    from aurora.core.engine_multi import MultiAssetEngine  # noqa: F401
    __all__.append("MultiAssetEngine")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.validation.pipeline import validate_pipeline  # noqa: F401
    __all__.append("validate_pipeline")
except ImportError:  # pragma: no cover
    pass
