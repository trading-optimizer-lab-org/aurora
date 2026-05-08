"""Demo: multi-asset GA on PairTrade(SPY, QQQ).

Round-4 audit (P2.4): updated to use ``load_tier`` so the demo respects
the tier-ceremony rules. The GA runs strictly on IS_TRAIN bars; OOS
validation happens AFTER the Pareto front is selected.

Run:
    uv run --with vectorbt --with deap --with scipy --with pyarrow \\
        python quantforge/examples/demo_multi_asset_ga.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

from quantforge.core.seed import set_global_seed
from quantforge.core.data_tiers import load_tier
from quantforge.strategies.library import PairTrade
from quantforge.ga.multi_asset_runner import (
    run_multi_asset_ga, MultiAssetGAConfig, multi_asset_fitness_is,
    multi_asset_validate_oos,
)


def main():
    set_global_seed(42)
    symbols = ["SPY", "QQQ"]

    # P2.4 round-4 audit: load_tier per asset so the demo never even
    # constructs an OOS-bearing dict for the GA. multi_asset_fitness_is
    # only sees IS_TRAIN bars.
    price_is = {s: load_tier(s, tier="IS_TRAIN") for s in symbols}
    for s in symbols:
        print(f"{s}: IS_TRAIN bars={len(price_is[s])}")

    cfg = MultiAssetGAConfig(
        population=30, generations=5, seed=42,
        gross_leverage_cap=1.0, net_leverage_cap=2.0,
    )
    pareto = run_multi_asset_ga(
        PairTrade,
        price_dict_is=price_is,
        price_dict_oos=None,
        symbols=symbols,
        fitness_fn=multi_asset_fitness_is,
        config=cfg,
    )

    print(f"\nPareto front: {len(pareto)} individuals")
    print(f"{'Calmar':>8} {'Sharpe':>8} {'Robust':>8} {'MDDpen':>8}  Params")
    for params, fit in sorted(pareto, key=lambda x: -x[1][0])[:15]:
        print(f"{fit[0]:>8.3f} {fit[1]:>8.3f} {fit[2]:>8.3f} {fit[3]:>8.3f}  {params}")


if __name__ == "__main__":
    main()
