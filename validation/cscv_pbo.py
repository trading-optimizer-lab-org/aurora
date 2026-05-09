"""Combinatorially Symmetric Cross-Validation (CSCV) and Probability of
Backtest Overfitting (PBO).

Reference: Bailey, Borwein, Lopez de Prado, Zhu (2014),
"The Probability of Backtest Overfitting".

Given a returns matrix (rows=time, cols=N candidate strategies/configs), CSCV
splits time into S equal slices and tests every combination of S/2 IS slices
vs the remaining S/2 OOS slices. For each split it picks the best strategy on
IS and computes its rank percentile on OOS. The PBO is the proportion of
splits where the IS-best strategy ranks below the OOS median (logit <= 0).

PBO interpretation:
  ~0.5  random selection (overfit, no real signal)
  <0.2  selection contains genuine signal
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Optional

import numpy as np
import pandas as pd

from quantforge.core.seed import child_rng


_MAX_COMBOS_DEFAULT = 20000


@dataclass
class CSCVResult:
    pbo: float
    logits: np.ndarray
    rank_correlations: np.ndarray
    performance_degradation_rate: float
    stochastic_dominance: float
    n_combinations: int
    # Per-block IS-usage count across the final combo set. Diagnostic for the
    # stratified sampler: the variance across this array tells callers whether
    # any time-block was systematically over- or under-represented in the IS
    # halves. A perfectly balanced sampling has std/mean << 1.
    block_usage: np.ndarray = None  # type: ignore[assignment]


def _sharpe_columns(arr: np.ndarray) -> np.ndarray:
    """Per-column Sharpe over rows. Constant columns -> 0.0."""
    if arr.shape[0] < 2:
        return np.zeros(arr.shape[1])
    mu = arr.mean(axis=0)
    sd = arr.std(axis=0, ddof=1)
    out = np.zeros_like(mu)
    nz = sd > 1e-12
    out[nz] = mu[nz] / sd[nz]
    return out


def _row_blocks(n_rows: int, n_splits: int) -> list[np.ndarray]:
    """Split row indices into n_splits near-equal blocks."""
    return [np.array(b) for b in np.array_split(np.arange(n_rows), n_splits)]


def _stratified_sample_combos(n_splits: int, half: int, n_target: int,
                              rng: np.random.Generator) -> list[tuple]:
    """Sample ``n_target`` size-``half`` IS-block combinations with balanced
    block coverage.

    Goal: each block index in [0, n_splits) appears as an IS-block in roughly
    the same number of sampled combinations. Achieved by greedy weighted
    sampling — at each draw, blocks with the lowest current usage have higher
    selection probability.

    Args:
        n_splits: number of time-blocks (S).
        half: combination size (S/2 for CSCV).
        n_target: number of unique combos to draw.
        rng: numpy Generator.

    Returns:
        List of ``n_target`` distinct sorted tuples of block indices.
    """
    seen: set[tuple] = set()
    combos: list[tuple] = []
    usage: np.ndarray = np.zeros(n_splits, dtype=np.int64)

    # Cap retries to avoid pathological loops on tiny S.
    max_attempts = n_target * 50
    attempts = 0
    while len(combos) < n_target and attempts < max_attempts:
        attempts += 1
        # Inverse-frequency weights: blocks used least are more likely.
        max_u = usage.max() if usage.size > 0 else 0
        # weight = (max_u + 1 - usage_i); never zero, and strongly biases
        # toward under-represented blocks.
        w: np.ndarray = (max_u + 1 - usage).astype(float)
        w = w / w.sum()
        pick = rng.choice(n_splits, size=half, replace=False, p=w)
        key = tuple(sorted(int(x) for x in pick))
        if key in seen:
            continue
        seen.add(key)
        combos.append(key)
        usage[list(key)] += 1

    if len(combos) < n_target:
        # Fall back: draw uniform-random size-``half`` combinations on the fly,
        # skipping duplicates. Materialising ``list(combinations(...))`` at
        # full S is OOM-risky — C(64, 32) is ~1.8e18 entries.
        fallback_attempts = 0
        max_fallback_attempts = (n_target - len(combos)) * 200
        while len(combos) < n_target and fallback_attempts < max_fallback_attempts:
            fallback_attempts += 1
            pick = rng.choice(n_splits, size=half, replace=False)
            key = tuple(sorted(int(x) for x in pick))
            if key in seen:
                continue
            seen.add(key)
            combos.append(key)
            usage[list(key)] += 1
    return combos


def cscv(returns_matrix: pd.DataFrame, n_splits: int = 16,
         seed_name: str = "cscv",
         max_combinations: int = _MAX_COMBOS_DEFAULT,
         stratify: bool = True) -> CSCVResult:
    """Combinatorially Symmetric Cross-Validation.

    Args:
        returns_matrix: rows=time, cols=N strategy return series.
        n_splits: must be EVEN. S=16 -> C(16,8)=12,870 combinations.
        seed_name: child RNG name (used if combos must be sampled).
        max_combinations: cap. If C(S, S/2) > cap, sample (uniformly or
            stratified depending on ``stratify``).
        stratify: if True (default), use balanced sampling so each time-block
            appears in roughly equal number of IS partitions across sampled
            combinations. If False, sample combos uniformly at random.

    Returns:
        CSCVResult with PBO and diagnostics.
    """
    if not isinstance(returns_matrix, pd.DataFrame):
        raise TypeError("returns_matrix must be a pandas DataFrame")
    if n_splits % 2 != 0:
        raise ValueError(f"n_splits must be even, got {n_splits}")
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    n_strats = returns_matrix.shape[1]
    if n_strats < 2:
        raise ValueError(f"need >= 2 strategies, got {n_strats}")
    n_rows = returns_matrix.shape[0]
    if n_rows < n_splits:
        raise ValueError(f"need >= {n_splits} rows, got {n_rows}")

    arr = returns_matrix.to_numpy(dtype=float, copy=False)
    blocks = _row_blocks(n_rows, n_splits)
    half = n_splits // 2

    all_idx = list(range(n_splits))
    all_combos = list(combinations(all_idx, half))
    n_total = len(all_combos)

    if n_total > max_combinations:
        rng = child_rng(seed_name)
        if stratify:
            combos = _stratified_sample_combos(
                n_splits, half, max_combinations, rng
            )
        else:
            sel = rng.choice(n_total, size=max_combinations, replace=False)
            combos = [all_combos[i] for i in sel]
    else:
        combos = all_combos

    logits = np.empty(len(combos))
    rank_corrs = np.empty(len(combos))
    is_best_sharpes = np.empty(len(combos))
    oos_best_sharpes = np.empty(len(combos))
    is_best_oos_sharpes = np.empty(len(combos))

    for k, is_set in enumerate(combos):
        is_set_arr = np.array(is_set, dtype=int)
        oos_mask: np.ndarray = np.ones(n_splits, dtype=bool)
        oos_mask[is_set_arr] = False
        oos_set = np.where(oos_mask)[0]

        is_rows = np.concatenate([blocks[i] for i in is_set_arr])
        oos_rows = np.concatenate([blocks[i] for i in oos_set])

        is_sharpes = _sharpe_columns(arr[is_rows])
        oos_sharpes = _sharpe_columns(arr[oos_rows])

        n_star = int(np.argmax(is_sharpes))

        oos_ranks = pd.Series(oos_sharpes).rank(method="average").to_numpy()
        rank_n_star = oos_ranks[n_star]
        w_c = rank_n_star / (n_strats + 1.0)
        w_c = np.clip(w_c, 1e-9, 1.0 - 1e-9)
        logits[k] = float(np.log(w_c / (1.0 - w_c)))

        is_ranks = pd.Series(is_sharpes).rank(method="average").to_numpy()
        if np.std(is_ranks) > 0 and np.std(oos_ranks) > 0:
            rank_corrs[k] = float(np.corrcoef(is_ranks, oos_ranks)[0, 1])
        else:
            rank_corrs[k] = 0.0

        is_best_sharpes[k] = is_sharpes[n_star]
        is_best_oos_sharpes[k] = oos_sharpes[n_star]
        oos_best_sharpes[k] = oos_sharpes.max()

    pbo = float(np.mean(logits <= 0.0))
    perf_degradation = float(np.mean(is_best_sharpes - is_best_oos_sharpes))
    stoch_dom = float(np.mean(is_best_oos_sharpes >= oos_best_sharpes))

    # Final IS-block usage tally so callers can audit the stratification
    # quality of whichever sampling mode was used.
    block_usage: np.ndarray = np.zeros(n_splits, dtype=np.int64)
    for c in combos:
        for b in c:
            block_usage[b] += 1

    return CSCVResult(
        pbo=pbo,
        logits=logits,
        rank_correlations=rank_corrs,
        performance_degradation_rate=perf_degradation,
        stochastic_dominance=stoch_dom,
        n_combinations=len(combos),
        block_usage=block_usage,
    )


def plot_pbo_distribution(result: CSCVResult,
                          output_path: Optional[str] = None) -> Optional[str]:
    """Histogram of logits with reference line at 0. Saves PNG if output_path."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(result.logits, bins=30, density=True, alpha=0.7,
            edgecolor="black", color="steelblue")
    ax.axvline(0.0, color="red", linestyle="--", linewidth=2,
               label=f"PBO threshold (PBO={result.pbo:.3f})")
    ax.set_xlabel("Logit")
    ax.set_ylabel("Density")
    ax.set_title(f"CSCV Logit Distribution (n={result.n_combinations})")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=120)
        plt.close(fig)
        return output_path
    plt.close(fig)
    return None


def cscv_summary_table(result: CSCVResult) -> pd.DataFrame:
    """Single-row DataFrame summary suitable for tear sheets."""
    return pd.DataFrame([{
        "pbo": result.pbo,
        "n_combinations": result.n_combinations,
        "logit_mean": float(np.mean(result.logits)),
        "logit_median": float(np.median(result.logits)),
        "rank_corr_mean": float(np.mean(result.rank_correlations)),
        "performance_degradation_rate": result.performance_degradation_rate,
        "stochastic_dominance": result.stochastic_dominance,
    }])
