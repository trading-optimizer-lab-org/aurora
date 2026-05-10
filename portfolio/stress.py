# ruff: noqa: N806, N803
"""Stress testing for portfolio allocators.

Compare an allocator's behaviour under perturbed inputs:
- noise injection on returns
- transaction-cost multiplier
- asset removal (set its column to NaN/zero)
- correlation boost (shrink sample correlation matrix toward 1)

Each scenario runs the allocator on the perturbed matrix and reports
weight delta vs the baseline plus a summary metric.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from aurora.portfolio.allocation import PortfolioOptimizer
from aurora.portfolio.risk_measures import (
    max_drawdown,
    turnover_aware_net_return,
    variance,
)


@dataclass(frozen=True)
class StressScenario:
    """Parameters for a single stress scenario.

    Parameters
    ----------
    name
        Free-form label.
    noise_std
        Std-dev of zero-mean Gaussian noise added to each return entry.
        Drives the *noisy-covariance* scenario when > 0.
    cost_bps_multiplier
        Multiplier on the base transaction cost (in bps). 1.0 = baseline.
        Drives the *higher-cost* scenario when > 1.
    drop_assets
        Indices (0-based) of assets to zero out before fitting. Drives
        the *missing-asset* scenario.
    correlation_boost
        Shrinkage toward an all-ones correlation matrix; 0 = unchanged,
        1 = perfect correlation. Applied to the empirical correlation
        before re-imposing the original variances.
    drawdown_shock
        Magnitude (positive number) of an additional simultaneous loss
        applied to every asset on a contiguous block of bars at the end
        of the sample. Drives the *correlated-drawdown* scenario.
    drawdown_window_frac
        Fraction of T over which to apply ``drawdown_shock``. Defaults
        to 0.05 (last 5% of bars).
    liquidity_haircut
        Fraction in [0, 1] applied to the *level* of all returns to
        simulate widening spreads / liquidity drying. ``0.5`` halves
        every per-period return. Drives the *liquidity-shock* scenario.
    concentration_floor
        If > 0, all assets except the most-concentrated cluster have
        their returns scaled down by this fraction (forcing the
        allocator into a concentrated regime). Drives the
        *concentration-shock* scenario.
    seed
        Optional RNG seed for noise reproducibility. ALL stochastic
        operations use ``np.random.default_rng(seed)``.
    """
    name: str
    noise_std: float = 0.0
    cost_bps_multiplier: float = 1.0
    drop_assets: tuple[int, ...] = ()
    correlation_boost: float = 0.0
    drawdown_shock: float = 0.0
    drawdown_window_frac: float = 0.05
    liquidity_haircut: float = 0.0
    concentration_floor: float = 0.0
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.noise_std < 0:
            raise ValueError("noise_std must be >= 0")
        if self.cost_bps_multiplier < 0:
            raise ValueError("cost_bps_multiplier must be >= 0")
        if not (0.0 <= self.correlation_boost <= 1.0):
            raise ValueError("correlation_boost must be in [0, 1]")
        if self.drawdown_shock < 0:
            raise ValueError("drawdown_shock must be >= 0")
        if not (0.0 < self.drawdown_window_frac <= 1.0):
            raise ValueError(
                "drawdown_window_frac must be in (0, 1]"
            )
        if not (0.0 <= self.liquidity_haircut <= 1.0):
            raise ValueError("liquidity_haircut must be in [0, 1]")
        if not (0.0 <= self.concentration_floor <= 1.0):
            raise ValueError("concentration_floor must be in [0, 1]")


@dataclass
class StressResult:
    """Output of a single stress run."""
    scenario: StressScenario
    weights: np.ndarray
    baseline_weights: np.ndarray
    weight_delta_l1: float
    metric_baseline: dict[str, float]
    metric_stressed: dict[str, float]
    metric_delta: dict[str, float] = field(default_factory=dict)


def stress_test(
    allocator: PortfolioOptimizer,
    returns: np.ndarray,
    scenarios: Sequence[StressScenario],
    base_costs_bps: float = 0.0,
) -> list[StressResult]:
    """Run ``allocator`` against each scenario and return per-scenario results.

    The allocator must be fresh / refittable: ``stress_test`` calls
    ``fit`` on a fresh allocator clone for each scenario by deep-copying
    via ``__class__(**)``-style is too brittle, so callers pass an
    already-constructed allocator and we just call ``fit`` on it. To keep
    the baseline deterministic, baseline weights are computed once at
    the top.
    """
    R = np.asarray(returns, dtype=float)
    if R.ndim != 2:
        raise ValueError("returns must be 2-D")
    T, N = R.shape

    # Baseline fit
    allocator.fit(R)
    baseline_w = allocator.predict()
    baseline_metric = _portfolio_metric(baseline_w, R, base_costs_bps)

    results: list[StressResult] = []
    for s in scenarios:
        R_s = _apply_scenario(R, s)
        # Fit a fresh copy: re-instantiating the allocator generically is
        # not safe, so we re-fit the same instance. Each baseline allocator
        # in this package is stateless w.r.t. fit (the previous weights
        # are simply overwritten) so this is fine.
        allocator.fit(R_s)
        w_s = allocator.predict()

        cost_bps = base_costs_bps * s.cost_bps_multiplier
        metric_s = _portfolio_metric(w_s, R_s, cost_bps)

        # Pad shapes if drop_assets removed columns -- here we kept N fixed
        # (set columns to 0) so the shapes match. Compute L1 delta.
        if w_s.shape != baseline_w.shape:
            delta = float("nan")
        else:
            delta = float(np.sum(np.abs(w_s - baseline_w)))

        m_delta = {
            k: metric_s[k] - baseline_metric[k]
            for k in metric_s
            if k in baseline_metric
        }
        results.append(
            StressResult(
                scenario=s,
                weights=w_s,
                baseline_weights=baseline_w,
                weight_delta_l1=delta,
                metric_baseline=baseline_metric,
                metric_stressed=metric_s,
                metric_delta=m_delta,
            )
        )
    return results


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _apply_scenario(R: np.ndarray, s: StressScenario) -> np.ndarray:
    """Return a perturbed copy of ``R`` per the scenario."""
    out = R.copy()
    T, N = out.shape

    if s.noise_std > 0:
        rng = np.random.default_rng(s.seed)
        out = out + rng.normal(0.0, s.noise_std, size=out.shape)

    if s.drop_assets:
        for j in s.drop_assets:
            if 0 <= j < N:
                out[:, j] = 0.0

    if s.correlation_boost > 0 and N > 1:
        # Shrink sample correlation toward all-ones (rho=1) while keeping
        # marginal variances. This boosts pairwise correlations.
        std = np.std(out, axis=0, ddof=1)
        std = np.where(std > 0, std, 1.0)
        Z = (out - out.mean(axis=0)) / std
        # Empirical correlation
        C = np.corrcoef(Z, rowvar=False) if N > 1 else np.eye(N)
        ones = np.ones_like(C)
        C_new = (1.0 - s.correlation_boost) * C + s.correlation_boost * ones
        # Cholesky-like reshape: project rows onto new corr structure.
        # Use eigen-decomposition for a stable transform.
        try:
            L_old = np.linalg.cholesky(C + 1e-10 * np.eye(N))
            L_new = np.linalg.cholesky(C_new + 1e-10 * np.eye(N))
            # Z' = L_new @ L_old^{-1} @ Z'
            transform = L_new @ np.linalg.inv(L_old)
            Z_new = (transform @ Z.T).T
            out = Z_new * std + out.mean(axis=0)
        except np.linalg.LinAlgError:
            pass  # leave unchanged if matrix is degenerate

    if s.drawdown_shock > 0 and T > 0:
        # Correlated drawdown: subtract a uniform per-bar loss across
        # all assets in the trailing ``drawdown_window_frac`` fraction
        # of bars. Shock split evenly across the window so total loss
        # equals ``drawdown_shock``.
        win = max(1, int(round(T * s.drawdown_window_frac)))
        per_bar = float(s.drawdown_shock) / float(win)
        out[T - win:, :] = out[T - win:, :] - per_bar

    if s.liquidity_haircut > 0:
        # Liquidity shock: shrink magnitude of every per-period return
        # by ``1 - haircut``. A haircut of 0.5 halves every return so
        # gains shrink and losses do too -- the optimiser sees a
        # weakened-edge environment with the same correlation structure.
        out = out * (1.0 - s.liquidity_haircut)

    if s.concentration_floor > 0 and N > 1:
        # Concentration shock: pick the asset with the highest mean
        # return (deterministic given input) and scale down all OTHER
        # assets by ``1 - floor``. This pushes the allocator into a
        # concentrated regime where the dominant asset's relative edge
        # widens.
        mean_assets = np.mean(out, axis=0)
        winner = int(np.argmax(mean_assets))
        scale = 1.0 - float(s.concentration_floor)
        for j in range(N):
            if j != winner:
                out[:, j] = out[:, j] * scale

    return out


def _portfolio_metric(
    w: np.ndarray,
    R: np.ndarray,
    cost_bps: float,
) -> dict[str, float]:
    """Compute summary stats for a portfolio path under given costs."""
    if w.size == 0 or R.size == 0:
        return {
            "gross_return": 0.0,
            "net_return": 0.0,
            "variance": 0.0,
            "max_drawdown": 0.0,
        }
    # Build a (T, N) weight matrix held constant for the whole path.
    W = np.tile(w, (R.shape[0], 1))
    cost_summary = turnover_aware_net_return(W, R, cost_bps)
    # Variance / max drawdown of the per-period gross portfolio return
    port_gross = R @ w
    return {
        "gross_return": cost_summary["gross_return"],
        "net_return": cost_summary["net_return"],
        "variance": variance(port_gross),
        "max_drawdown": max_drawdown(port_gross),
    }


# --------------------------------------------------------------------------- #
# Named scenario factories (R172)                                             #
# --------------------------------------------------------------------------- #
def noisy_covariance_scenario(
    noise_std: float = 0.005,
    seed: int = 0,
    name: str = "noisy_cov",
) -> StressScenario:
    """Inject Gaussian noise to perturb the sample covariance."""
    return StressScenario(name=name, noise_std=noise_std, seed=seed)


def higher_cost_scenario(
    multiplier: float = 5.0,
    seed: int = 0,
    name: str = "higher_cost",
) -> StressScenario:
    """Multiply the base transaction cost by ``multiplier``."""
    return StressScenario(
        name=name, cost_bps_multiplier=multiplier, seed=seed,
    )


def missing_asset_scenario(
    drop_assets: tuple[int, ...] = (0,),
    seed: int = 0,
    name: str = "missing_asset",
) -> StressScenario:
    """Zero out one or more asset columns (forced delisting)."""
    return StressScenario(name=name, drop_assets=drop_assets, seed=seed)


def correlated_drawdown_scenario(
    shock: float = 0.2,
    window_frac: float = 0.05,
    correlation_boost: float = 0.5,
    seed: int = 0,
    name: str = "correlated_drawdown",
) -> StressScenario:
    """Apply a synchronised drawdown across all assets at the tail."""
    return StressScenario(
        name=name,
        drawdown_shock=shock,
        drawdown_window_frac=window_frac,
        correlation_boost=correlation_boost,
        seed=seed,
    )


def liquidity_shock_scenario(
    haircut: float = 0.5,
    cost_multiplier: float = 3.0,
    seed: int = 0,
    name: str = "liquidity_shock",
) -> StressScenario:
    """Shrink return magnitudes + raise costs (liquidity dries up)."""
    return StressScenario(
        name=name,
        liquidity_haircut=haircut,
        cost_bps_multiplier=cost_multiplier,
        seed=seed,
    )


def concentration_shock_scenario(
    floor: float = 0.6,
    seed: int = 0,
    name: str = "concentration_shock",
) -> StressScenario:
    """Force the optimiser into a concentrated regime."""
    return StressScenario(
        name=name, concentration_floor=floor, seed=seed,
    )
