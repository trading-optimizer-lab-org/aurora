"""Monte Carlo validation: block bootstrap + trade reorder.

Two distinct tests:

1. **Block bootstrap**: resample blocks of returns to test if MDD distribution
   is consistent with the strategy producing alpha (vs lucky paths).

2. **Trade reorder**: shuffle order of completed trades, recompute equity curve.
   Tests if observed MDD depends on a fortunate sequence.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

from aurora.core.metrics import compute_metrics
from aurora.core.seed import child_rng


def circular_block_bootstrap(returns: np.ndarray, length: int,
                             avg_block_len: float,
                             rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap with circular wrap.

    Block lengths are drawn iid from a geometric distribution with mean
    ``avg_block_len`` (i.e. p = 1 / avg_block_len). Each block starts at a
    uniformly random index in [0, T). When a block runs past index T-1 it
    wraps around to index 0 — the input series is treated as circular.

    Args:
        returns: 1D source array of length T (T >= 1).
        length: requested output length (>= 1).
        avg_block_len: expected geometric block length (> 0). Probability
            parameter is p = 1 / avg_block_len, clipped to (0, 1].
        rng: numpy Generator for reproducibility.

    Returns:
        np.ndarray of length ``length`` filled by concatenated wrapped blocks.
    """
    T = len(returns)
    if T < 1:
        raise ValueError("returns must be non-empty")
    if length < 1:
        raise ValueError("length must be >= 1")
    if avg_block_len <= 0:
        raise ValueError("avg_block_len must be > 0")

    p = 1.0 / float(avg_block_len)
    if p > 1.0:
        p = 1.0
    out = np.empty(length, dtype=returns.dtype)
    filled = 0
    while filled < length:
        start = int(rng.integers(0, T))
        # geometric on numpy returns >= 1
        block_len = int(rng.geometric(p))
        take = min(block_len, length - filled)
        # circular wrap via modulo indexing
        idx: np.ndarray = (start + np.arange(take)) % T
        out[filled:filled + take] = returns[idx]
        filled += take
    return out


@dataclass
class MCResult:
    real_mdd: float
    real_calmar: float
    p5_mdd: float    # 5th percentile of MC MDD distribution (worst 5%)
    p50_mdd: float   # median
    p95_mdd: float   # best 5%
    p5_calmar: float
    p50_calmar: float
    p95_calmar: float
    real_mdd_percentile: float  # where real_mdd falls in MC distribution
    n_paths: int

    def passes(self, min_percentile: float = 0.20, max_percentile: float = 0.80) -> bool:
        """Real MDD should be between percentiles min and max (i.e. typical, not lucky)."""
        return min_percentile <= self.real_mdd_percentile <= max_percentile


def monte_carlo_bootstrap(returns: np.ndarray, n_paths: int = 1000,
                          block_size: int = 21, ppy: int = 252,
                          seed_name: str = "mc_bootstrap",
                          method: str = "circular") -> MCResult:
    """Block bootstrap returns to estimate MDD distribution.

    Args:
        returns: np.array of strategy returns (1D)
        n_paths: number of MC paths
        block_size: bootstrap block length. For ``method="fixed"`` this is the
            exact block length; for ``method="circular"`` it is the geometric
            mean (Politis-Romano stationary bootstrap with circular wrap).
        ppy: periods/year
        seed_name: child RNG name for reproducibility
        method: ``"circular"`` (Politis-Romano stationary, default) or
            ``"fixed"`` (legacy fixed-size non-circular bootstrap, kept for
            backwards compatibility).

    Returns:
        MCResult with real metrics + MC distribution percentiles
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    T = len(r)
    if T < block_size * 2:
        raise ValueError(f"returns too short ({T}) for block size {block_size}")
    if method not in ("circular", "fixed"):
        raise ValueError(f"method must be 'circular'|'fixed', got {method!r}")

    real_metrics = compute_metrics(r, ppy=ppy)
    rng = child_rng(seed_name)

    mc_mdd = np.zeros(n_paths)
    mc_cal = np.zeros(n_paths)

    if method == "circular":
        for k in range(n_paths):
            path = circular_block_bootstrap(
                r, length=T, avg_block_len=float(block_size), rng=rng
            )
            m = compute_metrics(path, ppy=ppy)
            mc_mdd[k] = m.mdd
            mc_cal[k] = m.calmar
    else:  # fixed
        # Fixed-block bootstrap with circular wrap. Each block start is drawn
        # uniformly from [0, T) and the block of length ``block_size`` is read
        # circularly modulo T so the last partial block is no longer dropped
        # by ``[:T]`` truncation. Without circular wrap, blocks starting near
        # T - block_size + 1 had higher selection probability and the final
        # bars of the source series were always observed in their original
        # order, biasing the MDD distribution toward early-window draws.
        n_blocks = int(np.ceil(T / block_size))
        if n_blocks < 1:
            n_blocks = 1
        for k in range(n_paths):
            starts = rng.integers(0, T, size=n_blocks)
            blocks = [r[(s + np.arange(block_size)) % T] for s in starts]
            path = np.concatenate(blocks)[:T]
            m = compute_metrics(path, ppy=ppy)
            mc_mdd[k] = m.mdd
            mc_cal[k] = m.calmar

    # percentile of real MDD (note: MDD is negative; smaller = worse)
    pct = float(np.mean(mc_mdd <= real_metrics.mdd))

    return MCResult(
        real_mdd=real_metrics.mdd,
        real_calmar=real_metrics.calmar,
        p5_mdd=float(np.percentile(mc_mdd, 5)),
        p50_mdd=float(np.percentile(mc_mdd, 50)),
        p95_mdd=float(np.percentile(mc_mdd, 95)),
        p5_calmar=float(np.percentile(mc_cal, 5)),
        p50_calmar=float(np.percentile(mc_cal, 50)),
        p95_calmar=float(np.percentile(mc_cal, 95)),
        real_mdd_percentile=pct,
        n_paths=n_paths,
    )


def monte_carlo_trade_reorder(weights: np.ndarray, returns: np.ndarray,
                              n_paths: int = 1000, ppy: int = 252,
                              seed_name: str = "mc_reorder",
                              min_trades: int = 5) -> MCResult:
    """Trade reorder MC: identify trades (entries/exits), shuffle order,
    recompute equity curve.

    Trade detected as period of constant non-zero weight, bounded by weight
    changes. Strategies that rebalance every bar (vol-target, Kelly,
    continuous-weight) will not produce discrete trades under this definition;
    in that case the function raises with a helpful message instead of silently
    using a tiny sample.

    Args:
        weights: per-bar position weight (float array).
        returns: per-bar asset returns (float array of same length as ``weights``).
        n_paths: number of permutations.
        ppy: periods per year — used both to annualize the real CAGR and the
            bootstrap CAGRs from the reordered equity curves.
        seed_name: child RNG name (reproducibility).
        min_trades: minimum number of distinct trade segments required before
            running the MC. Strategies with fewer trades will raise with
            guidance to pick a different MC method.
    """
    w = np.asarray(weights, dtype=float)
    r = np.asarray(returns, dtype=float)
    n = len(w)
    if n != len(r):
        raise ValueError("weights and returns length mismatch")
    if min_trades < 2:
        raise ValueError(f"min_trades must be >= 2 (got {min_trades})")

    # Identify trade segments (runs of constant non-zero weight)
    trades = []
    i = 0
    while i < n:
        wi = w[i]
        if wi == 0:
            i += 1; continue
        j = i
        while j < n and w[j] == wi:
            j += 1
        # trade from i to j-1, return = sum or product of bars
        # Mirror engine convention weights[t-1] * returns[t]: weights spanning
        # bars [i, j-1] earn returns at bars [i+1, j].
        seg_rets = wi * r[i + 1:j + 1]
        cum = np.prod(1.0 + seg_rets) - 1.0
        trades.append((wi, cum, j - i))
        i = j

    if len(trades) < min_trades:
        raise ValueError(
            f"too few trades ({len(trades)} < min_trades={min_trades}) for MC "
            "reorder. Strategies that rebalance every bar (vol-target, Kelly, "
            "continuous-weight) do not produce discrete entries/exits — use "
            "monte_carlo_bootstrap on the return series instead."
        )

    # Use the same horizon convention for the real equity curve and the
    # bootstrap paths: years = len(r) / ppy. Earlier the bootstrap loop reused
    # ``years_proxy`` while a separate place inadvertently mixed in the trade
    # count; the explicit name and shared computation below avoid drift.
    years = len(r) / float(ppy) if ppy > 0 else 0.0

    real_eq = np.cumprod(1.0 + np.array([t[1] for t in trades]))
    real_mdd = float(((real_eq - np.maximum.accumulate(real_eq)) / np.maximum.accumulate(real_eq)).min())
    real_cagr = real_eq[-1] ** (1.0 / years) - 1.0 if years > 0 else 0.0
    real_cal = real_cagr / abs(real_mdd) if abs(real_mdd) > 1e-9 else 0.0

    rng = child_rng(seed_name)
    mc_mdd = np.zeros(n_paths)
    mc_cal = np.zeros(n_paths)
    trade_rets = np.array([t[1] for t in trades])
    for k in range(n_paths):
        perm = rng.permutation(trade_rets)
        eq = np.cumprod(1.0 + perm)
        mdd = float(((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min())
        # Use the same `years` horizon as the real path so percentile
        # comparisons are apples-to-apples.
        cagr = eq[-1] ** (1.0 / years) - 1.0 if years > 0 else 0.0
        mc_mdd[k] = mdd
        mc_cal[k] = cagr / abs(mdd) if abs(mdd) > 1e-9 else 0.0

    pct = float(np.mean(mc_mdd <= real_mdd))

    return MCResult(
        real_mdd=real_mdd * 100,
        real_calmar=real_cal,
        p5_mdd=float(np.percentile(mc_mdd, 5) * 100),
        p50_mdd=float(np.percentile(mc_mdd, 50) * 100),
        p95_mdd=float(np.percentile(mc_mdd, 95) * 100),
        p5_calmar=float(np.percentile(mc_cal, 5)),
        p50_calmar=float(np.percentile(mc_cal, 50)),
        p95_calmar=float(np.percentile(mc_cal, 95)),
        real_mdd_percentile=pct,
        n_paths=n_paths,
    )
