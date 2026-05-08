"""Parameter ranking stability across bootstrap resamples.

Take a set of parameter configurations and their fitness on the original
sample. Re-evaluate each configuration on N bootstrap resamples of the data
and compute Kendall tau between the original ranking and each resample
ranking. A stable parameter landscape produces high mean tau (>0.7) and
implies the ranking is not an artifact of one historical sample.

This module evaluates a *callable* fitness over user-supplied configurations
to stay decoupled from the GA module. The callable gets (config, sample) and
must return a float.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Sequence
import numpy as np
import pandas as pd
from scipy import stats

from quantforge.core.seed import child_rng


def _bootstrap_sample(rng: np.random.Generator, sample: pd.Series) -> pd.Series:
    n = len(sample)
    idx = rng.integers(0, n, n)
    return pd.Series(sample.values[idx], index=sample.index, name=sample.name)


@dataclass
class ParameterRankStability:
    n_resamples: int = 30
    seed_name: str = "param_rank_stability"
    base_fitnesses: np.ndarray = field(default_factory=lambda: np.array([]))
    base_ranks: np.ndarray = field(default_factory=lambda: np.array([]))
    resample_taus: np.ndarray = field(default_factory=lambda: np.array([]))
    mean_tau: float = 0.0
    median_tau: float = 0.0
    p5_tau: float = 0.0
    n_configs: int = 0

    def run(self, configs: Sequence[dict],
            fitness_fn: Callable[[dict, pd.Series], float],
            sample: pd.Series) -> "ParameterRankStability":
        if not isinstance(sample, pd.Series):
            raise TypeError("sample must be pd.Series")
        if len(configs) < 3:
            raise ValueError("need >=3 configs to rank meaningfully")
        if self.n_resamples < 1:
            raise ValueError("n_resamples must be >= 1")
        if not callable(fitness_fn):
            raise TypeError("fitness_fn must be callable")

        n_cfg = len(configs)
        self.n_configs = n_cfg

        # Base fitnesses on the original sample
        base = np.array([float(fitness_fn(c, sample)) for c in configs])
        self.base_fitnesses = base
        # rankdata: smallest rank for smallest value; we report ascending ranks
        self.base_ranks = stats.rankdata(base)

        rng = child_rng(self.seed_name)
        taus = np.zeros(self.n_resamples)
        for k in range(self.n_resamples):
            boot = _bootstrap_sample(rng, sample)
            fits_k = np.array([float(fitness_fn(c, boot)) for c in configs])
            ranks_k = stats.rankdata(fits_k)
            tau, _ = stats.kendalltau(self.base_ranks, ranks_k)
            # If ties or constant, tau may be NaN; treat as 0 (no information).
            taus[k] = 0.0 if (tau is None or np.isnan(tau)) else float(tau)
        self.resample_taus = taus
        self.mean_tau = float(np.mean(taus))
        self.median_tau = float(np.median(taus))
        self.p5_tau = float(np.percentile(taus, 5))
        return self
