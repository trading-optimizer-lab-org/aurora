"""Core public API with lightweight policy modules available without quant deps."""

from __future__ import annotations


__all__: list[str] = []

try:
    from aurora.core.costs import CostModel, IBKR_costs, ZERO_costs
    from aurora.core.data_layer import OOSGuard, load_asset, load_universe
    from aurora.core.engine import BacktestResult, run_backtest
    from aurora.core.metrics import compute_metrics
    from aurora.core.seed import set_global_seed
except ModuleNotFoundError:
    # GitHub preflight jobs intentionally install Aurora with --no-deps.
    # Their policy and contract modules must remain importable without loading
    # NumPy/Pandas, while a normal installation still exposes the full API.
    pass
else:
    __all__ = [
        "BacktestResult",
        "CostModel",
        "IBKR_costs",
        "OOSGuard",
        "ZERO_costs",
        "compute_metrics",
        "load_asset",
        "load_universe",
        "run_backtest",
        "set_global_seed",
    ]
