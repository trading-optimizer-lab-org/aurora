"""Demo: GA search for best MACross params on SPY.

Requires an editable install:
    pip install -e .

Run:
    python quantforge/examples/demo_ga.py
"""
from __future__ import annotations

from quantforge.core.seed import set_global_seed
from quantforge.core.data_layer import load_asset, split_is_oos
from quantforge.strategies.library import MACross
from quantforge.ga.runner import run_ga, GAConfig
from quantforge.ga.fitness import multi_objective_fitness


def main():
    set_global_seed(42)
    prices = load_asset("SPY", include_oos=True)
    is_p, oos_p = split_is_oos(prices)
    print(f"IS bars: {len(is_p)}, OOS bars: {len(oos_p)}")

    cfg = GAConfig(population=50, generations=10, seed=42)
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness, cfg)

    print(f"\nPareto front: {len(pareto)} individuals")
    print(f"{'Calmar':>8} {'Sharpe':>8} {'Robust':>8} {'MDDpen':>8}  Params")
    for params, fit in sorted(pareto, key=lambda x: -x[1][0])[:15]:
        print(f"{fit[0]:>8.3f} {fit[1]:>8.3f} {fit[2]:>8.3f} {fit[3]:>8.3f}  {params}")


if __name__ == "__main__":
    main()
