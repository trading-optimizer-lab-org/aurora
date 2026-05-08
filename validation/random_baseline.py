"""Random-baseline statistical significance test (R103).

For every approved strategy, generate N random-entry strategies with
the same shape (entry rate, hold period distribution) and compare the
candidate's Sharpe / Calmar / total return against the random
ensemble. A strategy whose metric falls inside the random distribution
is curve-fit, not skilled.

The implementation is deliberately simple: shuffle the strategy's
weight series N times to break any temporal alignment with prices,
re-run the cost / metrics pipeline on each shuffle, and report a
p-value over the random distribution.

Different from the existing ``noise_injection.py`` (which perturbs
prices) and ``cscv_pbo.py`` (which permutes folds): this targets the
weight-side null hypothesis "the entry timing is random".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from quantforge.core.costs import CostModel, ZERO_costs, apply_costs
from quantforge.core.metrics import compute_metrics


@dataclass(frozen=True)
class RandomBaselineResult:
    """One-tailed p-value of candidate metric vs random ensemble."""

    metric_name: str
    candidate_value: float
    random_mean: float
    random_std: float
    p_value_one_tail: float
    n_shuffles: int

    @property
    def is_significant(self) -> bool:
        """True iff p < 0.05 (candidate beats random ensemble)."""
        return np.isfinite(self.p_value_one_tail) and self.p_value_one_tail < 0.05


def _shuffled_weights(weights: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Return a permutation of ``weights`` with the same value distribution."""
    out = weights.copy()
    rng.shuffle(out)
    return out


def random_baseline_test(
    weights: np.ndarray,
    asset_returns: np.ndarray,
    *,
    metric_name: str = "sharpe",
    costs: CostModel = ZERO_costs,
    ppy: int = 252,
    n_shuffles: int = 500,
    seed: int = 42,
) -> RandomBaselineResult:
    """Run the random-baseline test for one metric.

    Args:
        weights: candidate strategy's weights array.
        asset_returns: matching asset return array.
        metric_name: which Metrics field to evaluate. Common choices:
            ``"sharpe"``, ``"calmar"``, ``"sortino"``, ``"cagr"``.
        costs: cost model to apply when computing strategy returns.
        ppy: periods per year.
        n_shuffles: random ensemble size. 500 default.
        seed: RNG seed for reproducibility.

    Returns:
        :class:`RandomBaselineResult` with the one-tailed p-value over
        the random distribution.
    """
    rng = np.random.default_rng(seed)
    weights = np.asarray(weights, dtype=float)
    asset_returns = np.asarray(asset_returns, dtype=float)
    if len(weights) != len(asset_returns):
        raise ValueError(
            f"length mismatch: weights {len(weights)} vs returns "
            f"{len(asset_returns)}"
        )

    # Candidate metric.
    cand_net = apply_costs(weights, asset_returns, costs)
    cand_metrics = compute_metrics(cand_net, ppy=ppy)
    cand_value = float(getattr(cand_metrics, metric_name))

    # Random ensemble.
    samples: list[float] = []
    for _ in range(n_shuffles):
        shuffled = _shuffled_weights(weights, rng)
        net = apply_costs(shuffled, asset_returns, costs)
        m = compute_metrics(net, ppy=ppy)
        samples.append(float(getattr(m, metric_name)))
    arr = np.asarray(samples)
    finite = arr[np.isfinite(arr)]
    if len(finite) < 2:
        return RandomBaselineResult(
            metric_name=metric_name,
            candidate_value=cand_value,
            random_mean=float("nan"),
            random_std=float("nan"),
            p_value_one_tail=float("nan"),
            n_shuffles=n_shuffles,
        )

    # One-tailed p-value: fraction of random outcomes >= candidate (for
    # higher-is-better metrics like Sharpe / Calmar / Sortino / CAGR).
    # Caller is expected to pass higher-is-better metric names.
    p_value = float((finite >= cand_value).sum() / len(finite))

    return RandomBaselineResult(
        metric_name=metric_name,
        candidate_value=cand_value,
        random_mean=float(finite.mean()),
        random_std=float(finite.std()),
        p_value_one_tail=p_value,
        n_shuffles=n_shuffles,
    )


__all__ = [
    "RandomBaselineResult",
    "random_baseline_test",
]
