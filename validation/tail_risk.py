"""Tail risk scenarios via block bootstrap of historical tail events.

Task L.3 (QuantForge v1.2). Provides:
- extract_tail_blocks: identify worst N% rolling-return blocks
- tail_aware_bootstrap: block bootstrap that oversamples tail blocks
- tail_var_estimation: VaR/CVaR comparison base vs tail-stressed paths
- synthetic_tail_paths: paths with tail events injected at random positions
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.seed import child_rng


@dataclass
class TailRiskResult:
    base_var_p99: float
    base_var_p999: float
    tail_var_p99: float
    tail_var_p999: float
    base_cvar_p99: float
    tail_cvar_p99: float
    n_paths: int
    tail_amplification_factor: float


def extract_tail_blocks(returns: pd.Series, percentile: float = 1.0,
                        block_size: int = 5) -> list[np.ndarray]:
    """Identify worst N% periods, return list of consecutive bad-return blocks.

    Worst events identified by rolling-sum of `block_size`. The bottom
    `percentile`% of those windows are returned as np.array slices of length
    `block_size`.

    Args:
        returns: historical returns (pd.Series)
        percentile: tail percentile (1.0 = worst 1%)
        block_size: block length around each tail event

    Returns:
        list of np.ndarray, each of length `block_size`
    """
    if not isinstance(returns, pd.Series):
        returns = pd.Series(np.asarray(returns, dtype=float))
    r = returns.dropna().to_numpy(dtype=float)
    n = len(r)
    if n < block_size * 2:
        raise ValueError(f"returns too short ({n}) for block size {block_size}")

    # rolling cumulative return per window of length block_size
    # window i covers r[i:i+block_size], for i in [0, n - block_size]
    cumsum = np.cumsum(r)
    # window_sum[i] = r[i] + ... + r[i + block_size - 1]
    window_sum = np.empty(n - block_size + 1, dtype=float)
    window_sum[0] = cumsum[block_size - 1]
    if len(window_sum) > 1:
        window_sum[1:] = cumsum[block_size:] - cumsum[:-block_size]

    # worst windows: lowest cumulative return
    n_keep = max(1, int(np.ceil(len(window_sum) * (percentile / 100.0))))
    # sort ascending, take first n_keep
    worst_idx = np.argsort(window_sum)[:n_keep]

    blocks = [r[i:i + block_size].copy() for i in worst_idx]
    return blocks


def tail_aware_bootstrap(returns: np.ndarray, n_paths: int = 1000,
                         path_length: Optional[int] = None,
                         tail_oversample: float = 3.0,
                         block_size: int = 21,
                         seed_name: str = "tail_bootstrap") -> np.ndarray:
    """Block bootstrap that oversamples tail blocks.

    Each candidate block of length `block_size` gets a sampling weight.
    Tail blocks (worst 10% by cumulative return) get weight `tail_oversample`,
    others get weight 1.0.

    Args:
        returns: source returns (1D)
        n_paths: number of synthetic paths
        path_length: length of each path (default = len(returns))
        tail_oversample: factor to upweight worst blocks
        block_size: bootstrap block size

    Returns:
        np.ndarray of shape (n_paths, path_length)
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if path_length is None:
        path_length = n
    if n < block_size * 2:
        raise ValueError(f"returns too short ({n}) for block size {block_size}")

    rng = child_rng(seed_name)

    # candidate block starts: 0..n - block_size
    n_starts = n - block_size + 1
    cumsum = np.cumsum(r)
    window_sum = np.empty(n_starts, dtype=float)
    window_sum[0] = cumsum[block_size - 1]
    if n_starts > 1:
        window_sum[1:] = cumsum[block_size:] - cumsum[:-block_size]

    # tail = worst 10% windows
    n_tail = max(1, int(np.ceil(n_starts * 0.10)))
    tail_threshold = np.partition(window_sum, n_tail - 1)[n_tail - 1]
    weights = np.where(window_sum <= tail_threshold,
                       float(tail_oversample), 1.0)
    # Explicit normalization: numpy.random.Generator.choice requires a
    # probability vector that sums to exactly 1.0. Computing weights / sum
    # in float64 leaves a tiny residual (~1e-16) that some BLAS paths reject.
    # Renormalize a second time after enforcing non-negativity for safety.
    if (weights < 0).any():
        raise ValueError("internal: tail-aware bootstrap weights must be non-negative")
    total = float(weights.sum())
    if total <= 0.0:
        raise ValueError("internal: tail-aware bootstrap weights sum to 0")
    probs = weights / total
    # Final safety renormalize (correct trailing FP error, then verify).
    probs = probs / probs.sum()
    if not np.isclose(probs.sum(), 1.0, atol=1e-12):
        raise ValueError(f"internal: tail-aware bootstrap probs sum != 1.0 ({probs.sum()})")

    n_blocks = (path_length + block_size - 1) // block_size
    # Identify the tail-block start indices once. Within a single path we draw
    # tail-block picks with ``replace=False`` so the same extreme block does
    # not appear multiple times in one synthetic path (the previous behaviour
    # ``replace=True`` could pick the worst block 5+ times in a row, which
    # gave a degenerate "amplified" path that overstated tail risk). Non-tail
    # blocks remain replace=True since there are many of them.
    tail_start_idx = np.where(window_sum <= tail_threshold)[0]
    paths = np.empty((n_paths, path_length), dtype=float)
    for k in range(n_paths):
        # Decide which slots draw from the tail subset vs the full population
        # using the same probability split (probs already reflect oversample).
        u = rng.random(n_blocks)
        # Threshold: probability that any single draw lands on a tail block.
        tail_prob = float(probs[tail_start_idx].sum()) if len(tail_start_idx) > 0 else 0.0
        is_tail = u < tail_prob
        n_tail_draw = int(is_tail.sum())
        # Cap tail draws by the available distinct tail blocks. After capping,
        # only the first ``n_tail_draw`` True positions in ``is_tail`` will be
        # assigned a tail pick; the rest fall through to the "other" pool so
        # the iterators below cannot run dry.
        n_tail_draw = min(n_tail_draw, len(tail_start_idx))

        starts = np.empty(n_blocks, dtype=int)
        if n_tail_draw > 0:
            tail_picks = rng.choice(tail_start_idx, size=n_tail_draw, replace=False)
        else:
            tail_picks = np.array([], dtype=int)
        # Compute n_other AFTER the cap so it matches the number of slots that
        # will not be served from tail_picks. Earlier this used the pre-cap
        # is_tail.sum() count and the iterator could exhaust mid-path.
        n_other = n_blocks - len(tail_picks)
        if n_other > 0:
            other_picks = rng.choice(n_starts, size=n_other, replace=True, p=probs)
        else:
            other_picks = np.array([], dtype=int)
        # Interleave tail picks into is_tail positions, but only up to the
        # capped count; remaining True slots draw from the "other" iterator.
        tail_iter = iter(tail_picks)
        other_iter = iter(other_picks)
        tail_remaining = n_tail_draw
        for j in range(n_blocks):
            if is_tail[j] and tail_remaining > 0:
                starts[j] = next(tail_iter)
                tail_remaining -= 1
            else:
                starts[j] = next(other_iter)
        path = np.concatenate([r[s:s + block_size] for s in starts])[:path_length]
        paths[k] = path
    return paths


def tail_var_estimation(strategy_factory: Callable[[pd.Series], np.ndarray],
                        prices: pd.Series,
                        n_paths: int = 500, ppy: int = 252,
                        seed_name: str = "tail_var") -> TailRiskResult:
    """Estimate strategy VaR/CVaR under tail-stressed scenarios.

    Procedure:
    1. Compute base returns from prices, record VaR p99, p999, CVaR p99.
    2. Generate tail-amplified bootstrap return paths.
    3. For each path: rebuild a synthetic price series, run strategy via
       `strategy_factory(prices)` -> returns array, collect tail metrics.
    4. Return base vs tail-stressed comparison.

    `strategy_factory(prices: pd.Series) -> np.ndarray of returns`.
    """
    if not isinstance(prices, pd.Series):
        prices = pd.Series(np.asarray(prices, dtype=float))
    p = prices.dropna()
    if len(p) < 50:
        raise ValueError(f"price series too short ({len(p)})")

    base_returns = p.pct_change().dropna().to_numpy(dtype=float)

    base_strat = np.asarray(strategy_factory(p), dtype=float)
    base_strat = base_strat[~np.isnan(base_strat)]

    base_var_p99 = float(np.percentile(base_strat, 1.0))
    if len(base_strat) < 1000:
        # Same small-sample guard as the per-path branch below.
        base_var_p999 = float("nan")
    else:
        base_var_p999 = float(np.percentile(base_strat, 0.1))
    base_tail = base_strat[base_strat <= base_var_p99]
    base_cvar_p99 = float(base_tail.mean()) if len(base_tail) > 0 else base_var_p99

    paths = tail_aware_bootstrap(base_returns, n_paths=n_paths,
                                  path_length=len(base_returns),
                                  tail_oversample=3.0,
                                  block_size=21,
                                  seed_name=seed_name)

    p0 = float(p.iloc[0])

    tail_var_p99_samples = []
    tail_var_p999_samples = []
    tail_cvar_p99_samples = []

    for k in range(n_paths):
        nav = p0 * np.cumprod(1.0 + paths[k])
        synth_prices = pd.Series(np.concatenate([[p0], nav]),
                                  index=p.index[:paths.shape[1] + 1])
        try:
            strat_rets = np.asarray(strategy_factory(synth_prices), dtype=float)
        except Exception:
            continue
        strat_rets = strat_rets[~np.isnan(strat_rets)]
        if len(strat_rets) < 10:
            continue
        v99 = float(np.percentile(strat_rets, 1.0))
        # p999 needs at least 1000 samples to be statistically meaningful;
        # below that np.percentile interpolates between very few extreme
        # observations and returns nearly arbitrary values. Report NaN so
        # callers can see the threshold was not estimable.
        if len(strat_rets) < 1000:
            v999 = float("nan")
        else:
            v999 = float(np.percentile(strat_rets, 0.1))
        tail = strat_rets[strat_rets <= v99]
        cv99 = float(tail.mean()) if len(tail) > 0 else v99
        tail_var_p99_samples.append(v99)
        tail_var_p999_samples.append(v999)
        tail_cvar_p99_samples.append(cv99)

    if len(tail_var_p99_samples) == 0:
        # fallback: bootstrap returns directly without strategy
        tail_var_p99 = float(np.percentile(paths, 1.0))
        if paths.size < 1000:
            tail_var_p999 = float("nan")
        else:
            tail_var_p999 = float(np.percentile(paths, 0.1))
        tail_cvar_p99 = float(paths[paths <= tail_var_p99].mean())
    else:
        tail_var_p99 = float(np.mean(tail_var_p99_samples))
        # tail_var_p999_samples may contain NaN entries when individual paths
        # had < 1000 samples. If every path was below threshold all entries
        # are NaN — short-circuit to NaN to avoid a numpy "Mean of empty
        # slice" RuntimeWarning from nanmean over an all-NaN array.
        finite_p999 = [v for v in tail_var_p999_samples if np.isfinite(v)]
        tail_var_p999 = float(np.mean(finite_p999)) if finite_p999 else float("nan")
        tail_cvar_p99 = float(np.mean(tail_cvar_p99_samples))

    amp = abs(tail_var_p99) / abs(base_var_p99) if abs(base_var_p99) > 1e-12 else 0.0

    return TailRiskResult(
        base_var_p99=base_var_p99,
        base_var_p999=base_var_p999,
        tail_var_p99=tail_var_p99,
        tail_var_p999=tail_var_p999,
        base_cvar_p99=base_cvar_p99,
        tail_cvar_p99=tail_cvar_p99,
        n_paths=n_paths,
        tail_amplification_factor=float(amp),
    )


def synthetic_tail_paths(returns: pd.Series, n_paths: int = 100,
                         tail_event_count: int = 3,
                         seed_name: str = "tail_paths") -> np.ndarray:
    """Generate paths with tail events injected at random positions.

    Each output path is a permutation/bootstrap of the input returns with
    `tail_event_count` worst-block segments spliced in at random offsets.

    Args:
        returns: historical returns (pd.Series)
        n_paths: number of paths
        tail_event_count: number of tail blocks to inject per path

    Returns:
        np.ndarray of shape (n_paths, len(returns))
    """
    if not isinstance(returns, pd.Series):
        returns = pd.Series(np.asarray(returns, dtype=float))
    r = returns.dropna().to_numpy(dtype=float)
    n = len(r)
    if n < 30:
        raise ValueError(f"returns too short ({n})")

    block_size = max(2, n // 50)
    blocks = extract_tail_blocks(returns, percentile=5.0, block_size=block_size)
    if len(blocks) == 0:
        raise ValueError("no tail blocks extracted")

    rng = child_rng(seed_name)
    paths = np.empty((n_paths, n), dtype=float)
    for k in range(n_paths):
        # base path: random bootstrap of returns
        base = rng.choice(r, size=n, replace=True)
        # inject tail blocks at random non-overlapping positions
        positions = rng.choice(n - block_size + 1,
                                size=min(tail_event_count, n // block_size),
                                replace=False)
        for pos in positions:
            blk = blocks[rng.integers(0, len(blocks))]
            base[pos:pos + len(blk)] = blk
        paths[k] = base
    return paths
