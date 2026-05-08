"""Causal-style refutation tests for factor signals.

Implements DoWhy-style refutation tests on the hypothesis ``signal -> return``
without requiring DoWhy. Three refutations are supported:

  - **placebo**: replace the treatment (signal) with a permutation; the
    estimated causal effect should collapse to zero.
  - **subset**: re-estimate on a random subsample; the effect should be
    stable.
  - **add_random_common_cause**: inject a random nuisance regressor and
    re-estimate; the estimated effect should not move much.

The ``estimate_effect`` step is OLS regression of ``return ~ signal +
controls`` (when controls are passed). This is the simplest implementation of
back-door adjustment when ``controls`` block all back-door paths.

No optional deps; pure numpy/pandas. Works without scipy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _design_matrix(
    signal: pd.Series, controls: Optional[pd.DataFrame] = None
) -> np.ndarray:
    """Build [intercept, signal, *controls] matrix."""
    n = len(signal)
    cols = [np.ones(n), signal.to_numpy(dtype=float)]
    if controls is not None and not controls.empty:
        for c in controls.columns:
            cols.append(controls[c].to_numpy(dtype=float))
    return np.column_stack(cols)


def _ols_signal_coef(
    signal: pd.Series,
    target: pd.Series,
    controls: Optional[pd.DataFrame] = None,
) -> float:
    """Return the coefficient on ``signal`` from OLS y ~ X."""
    X = _design_matrix(signal, controls)
    y = target.to_numpy(dtype=float)
    # least squares
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coefs[1])  # index 0 is intercept, 1 is signal


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class RefutationResult:
    """Outcome of a single refutation test."""

    name: str
    estimated_effect: float
    refuted_effect: float
    delta: float
    passed: bool


@dataclass
class CausalReport:
    """Bundle of refutation outcomes for a single ``estimate_effect`` run."""

    estimated_effect: float
    refutations: List[RefutationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.refutations)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class CausalFactorAnalysis:
    """Run OLS-based effect estimation + refutation tests.

    Parameters
    ----------
    placebo_tolerance:
        Maximum |effect| in placebo refutation considered a pass.
    subset_tolerance:
        Maximum relative shift in effect estimated on a subsample.
    common_cause_tolerance:
        Maximum relative shift after injecting a random nuisance regressor.
    seed:
        RNG seed for reproducibility.
    """

    def __init__(
        self,
        placebo_tolerance: float = 0.05,
        subset_tolerance: float = 0.5,
        common_cause_tolerance: float = 0.5,
        seed: int = 42,
    ):
        if placebo_tolerance < 0 or subset_tolerance < 0 or common_cause_tolerance < 0:
            raise ValueError("tolerances must be non-negative")
        self.placebo_tolerance = placebo_tolerance
        self.subset_tolerance = subset_tolerance
        self.common_cause_tolerance = common_cause_tolerance
        self.seed = seed

    # ------------------------------------------------------------------ estimate

    def estimate_effect(
        self,
        signal: pd.Series,
        target: pd.Series,
        controls: Optional[pd.DataFrame] = None,
    ) -> float:
        """OLS coefficient on ``signal`` (the back-door-adjusted effect)."""
        if not isinstance(signal, pd.Series):
            raise TypeError("signal must be a Series")
        if not isinstance(target, pd.Series):
            raise TypeError("target must be a Series")
        joined = pd.concat([signal.rename("__s__"), target.rename("__y__")], axis=1)
        if controls is not None:
            if not isinstance(controls, pd.DataFrame):
                raise TypeError("controls must be a DataFrame")
            joined = joined.join(controls, how="left")
        joined = joined.dropna()
        if len(joined) < 10:
            raise ValueError("need at least 10 aligned non-null rows")
        s = joined["__s__"]
        y = joined["__y__"]
        c = joined.drop(columns=["__s__", "__y__"]) if controls is not None else None
        return _ols_signal_coef(s, y, c)

    # ------------------------------------------------------------------ refutations

    def refute_placebo(
        self,
        signal: pd.Series,
        target: pd.Series,
        controls: Optional[pd.DataFrame] = None,
    ) -> RefutationResult:
        rng = np.random.default_rng(self.seed)
        baseline = self.estimate_effect(signal, target, controls)
        permuted = pd.Series(
            rng.permutation(signal.to_numpy()), index=signal.index, name=signal.name
        )
        refuted = self.estimate_effect(permuted, target, controls)
        return RefutationResult(
            name="placebo",
            estimated_effect=baseline,
            refuted_effect=refuted,
            delta=abs(refuted),
            passed=abs(refuted) <= self.placebo_tolerance * (abs(baseline) + 1.0),
        )

    def refute_subset(
        self,
        signal: pd.Series,
        target: pd.Series,
        controls: Optional[pd.DataFrame] = None,
        sample_frac: float = 0.7,
    ) -> RefutationResult:
        if not (0.0 < sample_frac < 1.0):
            raise ValueError("sample_frac must be in (0, 1)")
        rng = np.random.default_rng(self.seed + 1)
        baseline = self.estimate_effect(signal, target, controls)
        n = len(signal)
        idx = rng.choice(n, size=max(10, int(n * sample_frac)), replace=False)
        sub_idx = signal.index[idx]
        sub_signal = signal.loc[sub_idx]
        sub_target = target.loc[sub_idx]
        sub_controls = controls.loc[sub_idx] if controls is not None else None
        refuted = self.estimate_effect(sub_signal, sub_target, sub_controls)
        denom = max(abs(baseline), 1e-9)
        rel = abs(refuted - baseline) / denom
        return RefutationResult(
            name="subset",
            estimated_effect=baseline,
            refuted_effect=refuted,
            delta=rel,
            passed=rel <= self.subset_tolerance,
        )

    def refute_add_random_common_cause(
        self,
        signal: pd.Series,
        target: pd.Series,
        controls: Optional[pd.DataFrame] = None,
    ) -> RefutationResult:
        rng = np.random.default_rng(self.seed + 2)
        baseline = self.estimate_effect(signal, target, controls)
        nuisance = pd.Series(
            rng.standard_normal(len(signal)), index=signal.index, name="__nuisance__"
        )
        if controls is not None:
            new_controls = controls.copy()
            new_controls["__nuisance__"] = nuisance
        else:
            new_controls = nuisance.to_frame()
        refuted = self.estimate_effect(signal, target, new_controls)
        denom = max(abs(baseline), 1e-9)
        rel = abs(refuted - baseline) / denom
        return RefutationResult(
            name="add_random_common_cause",
            estimated_effect=baseline,
            refuted_effect=refuted,
            delta=rel,
            passed=rel <= self.common_cause_tolerance,
        )

    # ------------------------------------------------------------------ run all

    def run(
        self,
        signal: pd.Series,
        target: pd.Series,
        controls: Optional[pd.DataFrame] = None,
    ) -> CausalReport:
        baseline = self.estimate_effect(signal, target, controls)
        return CausalReport(
            estimated_effect=baseline,
            refutations=[
                self.refute_placebo(signal, target, controls),
                self.refute_subset(signal, target, controls),
                self.refute_add_random_common_cause(signal, target, controls),
            ],
        )


__all__ = [
    "CausalFactorAnalysis",
    "CausalReport",
    "RefutationResult",
]
