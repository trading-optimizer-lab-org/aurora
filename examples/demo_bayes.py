"""Demo: Bayesian optimization for best MACross params on SPY.

Requires an editable install with the GA extras (which include scikit-optimize):
    pip install -e ".[ga]"

Run:
    python quantforge/examples/demo_bayes.py
"""
from __future__ import annotations

from quantforge.core.seed import set_global_seed
from quantforge.core.data_layer import load_asset, split_is_oos
from quantforge.strategies.library import MACross
from quantforge.ga.bayes_opt import bayes_optimize, BayesConfig
from quantforge.ga.fitness import multi_objective_fitness


def main():
    set_global_seed(42)
    prices = load_asset("SPY", include_oos=True)
    is_p, oos_p = split_is_oos(prices)
    print(f"IS bars: {len(is_p)}, OOS bars: {len(oos_p)}")

    cfg = BayesConfig(n_calls=30, n_random_starts=10, seed=42, acquisition="EI")
    out = bayes_optimize(
        MACross, is_p, oos_p,
        fitness_fn=multi_objective_fitness,
        config=cfg,
        scalar=False,
    )

    print(f"\nBO best score (scalarized): {out['best_score']:.4f}")
    print(f"BO best params: {out['best_params']}")
    print(f"Trials evaluated: {len(out['all_trials'])}")
    print(f"Convergence (last 5): {[round(v, 4) for v in out['convergence'][-5:]]}")


if __name__ == "__main__":
    main()
