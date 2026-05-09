"""Multi-frequency Politis-Romano stationary bootstrap.

Runs the stationary bootstrap with multiple expected block lengths
simultaneously. Each block size targets a different temporal autocorrelation
horizon (intraday vs weekly vs monthly persistence). Aggregated metric
distributions are returned per block size so the caller can inspect
sensitivity of the conclusion to the resampling scale.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
import numpy as np
import pandas as pd

from aurora.core.metrics import compute_metrics
from aurora.core.seed import child_rng


def _stationary_bootstrap(returns: np.ndarray, length: int,
                          avg_block_len: float,
                          rng: np.random.Generator) -> np.ndarray:
    T = len(returns)
    p = 1.0 / float(avg_block_len)
    if p > 1.0:
        p = 1.0
    out = np.empty(length, dtype=returns.dtype)
    filled = 0
    while filled < length:
        start = int(rng.integers(0, T))
        block_len = int(rng.geometric(p))
        take = min(block_len, length - filled)
        idx: np.ndarray = (start + np.arange(take)) % T
        out[filled:filled + take] = returns[idx]
        filled += take
    return out


@dataclass
class MultiFrequencyBootstrap:
    block_sizes: tuple = (5, 20, 60)  # weekly, monthly, quarterly-ish
    n_paths: int = 200
    ppy: int = 252
    seed_name: str = "multi_freq_bootstrap"
    real_calmar: float = 0.0
    real_sharpe: float = 0.0
    # results[block_size] = dict with keys 'calmars' (np.ndarray), 'sharpes' (np.ndarray)
    results: Dict[int, Dict[str, np.ndarray]] = field(default_factory=dict)

    def run(self, returns: np.ndarray) -> "MultiFrequencyBootstrap":
        if not isinstance(returns, np.ndarray):
            returns = np.asarray(returns, dtype=float)
        if returns.ndim != 1:
            raise ValueError("returns must be 1-D")
        if len(returns) < 30:
            raise ValueError("need >=30 returns")
        if len(self.block_sizes) < 1:
            raise ValueError("block_sizes must be non-empty")
        if any(b < 1 for b in self.block_sizes):
            raise ValueError("block sizes must be >= 1")
        if self.n_paths < 1:
            raise ValueError("n_paths must be >= 1")

        T = len(returns)
        m = compute_metrics(returns, ppy=self.ppy)
        self.real_calmar = float(m.calmar)
        self.real_sharpe = float(m.sharpe)

        for bs in self.block_sizes:
            rng = child_rng(f"{self.seed_name}_{bs}")
            cals = np.zeros(self.n_paths)
            shrs = np.zeros(self.n_paths)
            for k in range(self.n_paths):
                boot = _stationary_bootstrap(returns, T, float(bs), rng)
                bm = compute_metrics(boot, ppy=self.ppy)
                cals[k] = float(bm.calmar)
                shrs[k] = float(bm.sharpe)
            self.results[int(bs)] = {"calmars": cals, "sharpes": shrs}
        return self

    def percentile(self, block_size: int, metric: str, q: float) -> float:
        if block_size not in self.results:
            raise KeyError(f"block_size {block_size} not in results")
        if metric not in ("calmars", "sharpes"):
            raise ValueError("metric must be 'calmars' or 'sharpes'")
        return float(np.percentile(self.results[block_size][metric], q))
