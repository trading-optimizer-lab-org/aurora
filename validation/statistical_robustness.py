"""Statistical robustness gate for research candidates.

This module is intentionally generic: it works from a candidate weight series
and an asset-return series, so SPY long/short searches, GA candidates and future
research loops can all use the same final gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

import numpy as np
import pandas as pd
from scipy import stats

from aurora.core.costs import CostModel, IBKR_costs, apply_costs
from aurora.core.metrics import Metrics, compute_metrics
from aurora.validation.cscv_pbo import cscv
from aurora.validation.deflated_sharpe import deflated_sharpe_annualized
from aurora.validation.random_baseline import random_baseline_test


@dataclass(frozen=True)
class StatisticalRobustnessConfig:
    """Thresholds for the enhanced robustness gate."""

    target_calmar: float = 1.0
    alpha: float = 0.05
    min_dsr: float = 0.95
    min_psr: float = 0.95
    max_pbo: float = 0.20
    max_fdr_q: float = 0.10
    min_bootstrap_calmar_p05: float = 0.0
    min_bootstrap_excess_calmar_p05: float = 0.0
    n_bootstrap: int = 300
    bootstrap_block: int = 21
    n_random_shuffles: int = 300
    n_permutations: int = 300
    ppy: int = 252
    seed: int = 1729


@dataclass(frozen=True)
class RobustnessCheck:
    name: str
    passed: bool | None
    value: float | None = None
    threshold: float | None = None
    p_value: float | None = None
    details: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StatisticalRobustnessReport:
    candidate_metrics: Metrics
    benchmark_metrics: Metrics
    checks: tuple[RobustnessCheck, ...]
    p_values: Mapping[str, float]
    fdr_q_values: Mapping[str, float]
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_metrics": self.candidate_metrics.to_dict(),
            "benchmark_metrics": self.benchmark_metrics.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
            "p_values": dict(self.p_values),
            "fdr_q_values": dict(self.fdr_q_values),
            "passed": self.passed,
        }


def statistical_robustness_gate(
    weights: np.ndarray,
    asset_returns: np.ndarray,
    *,
    benchmark_weights: np.ndarray | None = None,
    costs: CostModel = IBKR_costs,
    n_trials: int = 1,
    peer_returns: pd.DataFrame | np.ndarray | None = None,
    feature_votes: np.ndarray | None = None,
    config: StatisticalRobustnessConfig | None = None,
) -> StatisticalRobustnessReport:
    """Run significance, multiplicity and destruction checks.

    Args:
        weights: candidate position per bar.
        asset_returns: matching traded-asset returns.
        benchmark_weights: benchmark position per bar. Defaults to always long.
        costs: transaction-cost model.
        n_trials: total candidates tried before this candidate was selected.
        peer_returns: optional matrix of candidate net returns for CSCV/PBO and
            White Reality Check / SPA-style max-test correction.
        feature_votes: optional matrix shaped (time, features), with each column
            voting -1/+1. Enables leave-one-feature-out and tie-sensitivity.
        config: gate thresholds.
    """

    cfg = config or StatisticalRobustnessConfig()
    weights = _as_1d(weights, "weights")
    asset_returns = _as_1d(asset_returns, "asset_returns")
    if len(weights) != len(asset_returns):
        raise ValueError("weights and asset_returns length mismatch")
    if benchmark_weights is None:
        benchmark_weights = np.ones_like(weights)
    benchmark_weights = _as_1d(benchmark_weights, "benchmark_weights")
    if len(benchmark_weights) != len(asset_returns):
        raise ValueError("benchmark_weights and asset_returns length mismatch")

    candidate_net = apply_costs(weights, asset_returns, costs)
    benchmark_net = apply_costs(benchmark_weights, asset_returns, costs)
    candidate_metrics = compute_metrics(candidate_net[1:], ppy=cfg.ppy)
    benchmark_metrics = compute_metrics(benchmark_net[1:], ppy=cfg.ppy)
    excess = candidate_net - benchmark_net

    checks: list[RobustnessCheck] = []
    p_values: dict[str, float] = {}

    checks.append(RobustnessCheck(
        name="target_calmar",
        passed=candidate_metrics.calmar >= cfg.target_calmar,
        value=float(candidate_metrics.calmar),
        threshold=float(cfg.target_calmar),
    ))
    checks.append(RobustnessCheck(
        name="beats_benchmark_calmar",
        passed=candidate_metrics.calmar > benchmark_metrics.calmar,
        value=float(candidate_metrics.calmar - benchmark_metrics.calmar),
        threshold=0.0,
    ))

    mean_p = _ttest_pvalue_greater(excess[1:])
    p_values["mean_excess_vs_benchmark"] = mean_p
    checks.append(RobustnessCheck(
        name="p_value_mean_excess_vs_benchmark",
        passed=mean_p <= cfg.alpha,
        p_value=mean_p,
        threshold=cfg.alpha,
    ))

    block = _block_bootstrap_summary(
        candidate_net[1:],
        benchmark_net[1:],
        n_paths=cfg.n_bootstrap,
        block_size=cfg.bootstrap_block,
        ppy=cfg.ppy,
        seed=cfg.seed,
    )
    p_values["bootstrap_excess_calmar"] = float(block["p_value_excess_calmar"])
    checks.extend([
        RobustnessCheck(
            name="bootstrap_calmar_p05",
            passed=float(block["candidate_calmar_p05"]) >= cfg.min_bootstrap_calmar_p05,
            value=float(block["candidate_calmar_p05"]),
            threshold=cfg.min_bootstrap_calmar_p05,
            details=block,
        ),
        RobustnessCheck(
            name="bootstrap_excess_calmar_p05",
            passed=float(block["excess_calmar_p05"]) >= cfg.min_bootstrap_excess_calmar_p05,
            value=float(block["excess_calmar_p05"]),
            threshold=cfg.min_bootstrap_excess_calmar_p05,
            p_value=float(block["p_value_excess_calmar"]),
            details=block,
        ),
    ])

    random_calmar = random_baseline_test(
        weights,
        asset_returns,
        metric_name="calmar",
        costs=costs,
        ppy=cfg.ppy,
        n_shuffles=cfg.n_random_shuffles,
        seed=cfg.seed + 1,
    )
    random_sharpe = random_baseline_test(
        weights,
        asset_returns,
        metric_name="sharpe",
        costs=costs,
        ppy=cfg.ppy,
        n_shuffles=cfg.n_random_shuffles,
        seed=cfg.seed + 2,
    )
    p_values["random_baseline_calmar"] = float(random_calmar.p_value_one_tail)
    p_values["random_baseline_sharpe"] = float(random_sharpe.p_value_one_tail)
    checks.extend([
        RobustnessCheck(
            name="random_baseline_calmar",
            passed=random_calmar.p_value_one_tail <= cfg.alpha,
            value=float(random_calmar.candidate_value),
            p_value=float(random_calmar.p_value_one_tail),
            threshold=cfg.alpha,
            details=asdict(random_calmar),
        ),
        RobustnessCheck(
            name="random_baseline_sharpe",
            passed=random_sharpe.p_value_one_tail <= cfg.alpha,
            value=float(random_sharpe.candidate_value),
            p_value=float(random_sharpe.p_value_one_tail),
            threshold=cfg.alpha,
            details=asdict(random_sharpe),
        ),
    ])

    dsr = deflated_sharpe_annualized(
        candidate_metrics.sharpe,
        max(1, int(n_trials)),
        max(2, int(candidate_metrics.n_periods)),
        cfg.ppy,
        skew=candidate_metrics.skew,
        kurtosis=candidate_metrics.kurtosis,
        min_dsr=cfg.min_dsr,
        min_psr=cfg.min_psr,
    )
    checks.extend([
        RobustnessCheck(
            name="deflated_sharpe",
            passed=bool(dsr.passed),
            value=float(dsr.dsr),
            threshold=cfg.min_dsr,
            details=asdict(dsr),
        ),
        RobustnessCheck(
            name="probabilistic_sharpe",
            passed=float(dsr.psr_vs_zero) >= cfg.min_psr,
            value=float(dsr.psr_vs_zero),
            threshold=cfg.min_psr,
            details=asdict(dsr),
        ),
    ])

    perm_p = _circular_shift_permutation_pvalue(
        weights,
        asset_returns,
        candidate_metrics.calmar,
        costs=costs,
        n_permutations=cfg.n_permutations,
        ppy=cfg.ppy,
        seed=cfg.seed + 3,
    )
    p_values["circular_shift_permutation_calmar"] = perm_p
    checks.append(RobustnessCheck(
        name="permutation_test_circular_shift",
        passed=perm_p <= cfg.alpha,
        p_value=perm_p,
        threshold=cfg.alpha,
    ))

    peer = _peer_frame(peer_returns)
    if peer is not None and peer.shape[1] >= 2:
        wrc = _white_reality_check(peer, benchmark_net[1:], cfg)
        p_values["white_reality_check"] = float(wrc["p_value"])
        checks.append(RobustnessCheck(
            name="white_reality_check",
            passed=float(wrc["p_value"]) <= cfg.alpha,
            p_value=float(wrc["p_value"]),
            threshold=cfg.alpha,
            details=wrc,
        ))
        spa = _spa_like_check(peer, benchmark_net[1:], cfg)
        p_values["spa_test"] = float(spa["p_value"])
        checks.append(RobustnessCheck(
            name="spa_test",
            passed=float(spa["p_value"]) <= cfg.alpha,
            p_value=float(spa["p_value"]),
            threshold=cfg.alpha,
            details=spa,
        ))
        try:
            pbo = cscv(peer, n_splits=8, max_combinations=200, seed_name="stat_robustness_pbo")
            checks.append(RobustnessCheck(
                name="cscv_pbo",
                passed=float(pbo.pbo) <= cfg.max_pbo,
                value=float(pbo.pbo),
                threshold=cfg.max_pbo,
                details={
                    "pbo": float(pbo.pbo),
                    "rank_correlation_mean": float(np.mean(pbo.rank_correlations)),
                    "n_combinations": int(pbo.n_combinations),
                },
            ))
        except ValueError as exc:
            checks.append(RobustnessCheck(
                name="cscv_pbo",
                passed=None,
                details={"skipped": str(exc)},
            ))
    else:
        checks.extend([
            RobustnessCheck(name="white_reality_check", passed=None, details={"skipped": "peer_returns missing"}),
            RobustnessCheck(name="spa_test", passed=None, details={"skipped": "peer_returns missing"}),
            RobustnessCheck(name="cscv_pbo", passed=None, details={"skipped": "peer_returns missing"}),
        ])

    if feature_votes is not None:
        destruction = _feature_destruction_checks(
            feature_votes,
            asset_returns,
            candidate_metrics.calmar,
            costs=costs,
            ppy=cfg.ppy,
        )
        checks.append(RobustnessCheck(
            name="leave_one_feature_out",
            passed=bool(destruction["leave_one_feature_out_passed"]),
            value=float(destruction["worst_leave_one_calmar"]),
            threshold=0.0,
            details=destruction,
        ))
        checks.append(RobustnessCheck(
            name="tie_sensitivity",
            passed=bool(destruction["tie_sensitivity_passed"]),
            value=float(destruction["tie_short_calmar"]),
            threshold=0.0,
            details=destruction,
        ))
    else:
        checks.extend([
            RobustnessCheck(name="leave_one_feature_out", passed=None, details={"skipped": "feature_votes missing"}),
            RobustnessCheck(name="tie_sensitivity", passed=None, details={"skipped": "feature_votes missing"}),
        ])

    fdr = benjamini_hochberg(p_values)
    checks.append(RobustnessCheck(
        name="fdr_correction",
        passed=all(q <= cfg.max_fdr_q for q in fdr.values() if np.isfinite(q)),
        value=max(fdr.values()) if fdr else None,
        threshold=cfg.max_fdr_q,
        details={"q_values": fdr},
    ))

    hard = [check.passed for check in checks if check.passed is not None]
    passed = bool(hard and all(hard))
    return StatisticalRobustnessReport(
        candidate_metrics=candidate_metrics,
        benchmark_metrics=benchmark_metrics,
        checks=tuple(checks),
        p_values=p_values,
        fdr_q_values=fdr,
        passed=passed,
    )


def benjamini_hochberg(p_values: Mapping[str, float]) -> dict[str, float]:
    """Return Benjamini-Hochberg q-values for named p-values."""

    finite = [(name, float(p)) for name, p in p_values.items() if np.isfinite(p)]
    if not finite:
        return {}
    finite.sort(key=lambda item: item[1])
    m = len(finite)
    raw: dict[str, float] = {}
    prev = 1.0
    for rank, (name, p_value) in reversed(list(enumerate(finite, start=1))):
        q = min(prev, p_value * m / rank)
        raw[name] = float(min(max(q, 0.0), 1.0))
        prev = q
    return {name: raw[name] for name, _ in finite}


def _as_1d(values: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1D")
    if len(arr) < 20:
        raise ValueError(f"{name} too short for statistical robustness")
    return arr


def _ttest_pvalue_greater(values: np.ndarray) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or np.std(x, ddof=1) <= 1e-12:
        return 1.0
    return float(stats.ttest_1samp(x, 0.0, alternative="greater").pvalue)


def _block_bootstrap_summary(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    *,
    n_paths: int,
    block_size: int,
    ppy: int,
    seed: int,
) -> dict[str, float]:
    candidate = np.asarray(candidate, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    if len(candidate) != len(benchmark):
        raise ValueError("candidate and benchmark returns length mismatch")
    rng = np.random.default_rng(seed)
    cand_calmar = np.empty(n_paths)
    bench_calmar = np.empty(n_paths)
    excess_calmar = np.empty(n_paths)
    for i in range(n_paths):
        idx = _circular_block_indices(len(candidate), block_size, rng)
        c = compute_metrics(candidate[idx], ppy=ppy).calmar
        b = compute_metrics(benchmark[idx], ppy=ppy).calmar
        cand_calmar[i] = c
        bench_calmar[i] = b
        excess_calmar[i] = c - b
    return {
        "candidate_calmar_p05": float(np.percentile(cand_calmar, 5)),
        "candidate_calmar_p50": float(np.percentile(cand_calmar, 50)),
        "candidate_calmar_p95": float(np.percentile(cand_calmar, 95)),
        "benchmark_calmar_p50": float(np.percentile(bench_calmar, 50)),
        "excess_calmar_p05": float(np.percentile(excess_calmar, 5)),
        "excess_calmar_p50": float(np.percentile(excess_calmar, 50)),
        "excess_calmar_p95": float(np.percentile(excess_calmar, 95)),
        "p_value_excess_calmar": float(np.mean(excess_calmar <= 0.0)),
        "n_paths": float(n_paths),
    }


def _circular_block_indices(n: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    if n <= 0:
        raise ValueError("n must be positive")
    block_size = max(1, int(block_size))
    out: list[np.ndarray] = []
    while sum(len(x) for x in out) < n:
        start = int(rng.integers(0, n))
        take = min(block_size, n - sum(len(x) for x in out))
        out.append((start + np.arange(take)) % n)
    return np.concatenate(out)


def _circular_shift_permutation_pvalue(
    weights: np.ndarray,
    asset_returns: np.ndarray,
    observed_calmar: float,
    *,
    costs: CostModel,
    n_permutations: int,
    ppy: int,
    seed: int,
) -> float:
    rng = np.random.default_rng(seed)
    n = len(weights)
    if n < 3:
        return 1.0
    samples = np.empty(n_permutations)
    for i in range(n_permutations):
        shift = int(rng.integers(1, n - 1))
        shifted = np.roll(weights, shift)
        samples[i] = compute_metrics(apply_costs(shifted, asset_returns, costs)[1:], ppy=ppy).calmar
    return float(np.mean(samples >= observed_calmar))


def _peer_frame(peer_returns: pd.DataFrame | np.ndarray | None) -> pd.DataFrame | None:
    if peer_returns is None:
        return None
    if isinstance(peer_returns, pd.DataFrame):
        frame = peer_returns.copy()
    else:
        arr = np.asarray(peer_returns, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        frame = pd.DataFrame(arr)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
    return frame if frame.shape[0] >= 20 and frame.shape[1] >= 2 else None


def _white_reality_check(
    peer_returns: pd.DataFrame,
    benchmark_returns: np.ndarray,
    cfg: StatisticalRobustnessConfig,
) -> dict[str, float]:
    peer = _align_peer(peer_returns, benchmark_returns)
    excess = peer.to_numpy(dtype=float) - benchmark_returns[-len(peer):, None]
    means = excess.mean(axis=0)
    observed = float(np.max(means))
    centered = excess - means[None, :]
    rng = np.random.default_rng(cfg.seed + 4)
    max_samples = np.empty(cfg.n_bootstrap)
    for i in range(cfg.n_bootstrap):
        idx = _circular_block_indices(centered.shape[0], cfg.bootstrap_block, rng)
        max_samples[i] = float(centered[idx].mean(axis=0).max())
    return {
        "observed_best_mean_excess": observed,
        "p_value": float(np.mean(max_samples >= observed)),
        "n_strategies": float(peer.shape[1]),
    }


def _spa_like_check(
    peer_returns: pd.DataFrame,
    benchmark_returns: np.ndarray,
    cfg: StatisticalRobustnessConfig,
) -> dict[str, float]:
    peer = _align_peer(peer_returns, benchmark_returns)
    excess = peer.to_numpy(dtype=float) - benchmark_returns[-len(peer):, None]
    means = excess.mean(axis=0)
    keep = means > 0.0
    if int(keep.sum()) < 1:
        return {"p_value": 1.0, "n_strategies": 0.0, "observed_best_mean_excess": float(np.max(means))}
    trimmed = excess[:, keep]
    return _white_reality_check(pd.DataFrame(trimmed), np.zeros(trimmed.shape[0]), cfg)


def _align_peer(peer_returns: pd.DataFrame, benchmark_returns: np.ndarray) -> pd.DataFrame:
    n = min(len(peer_returns), len(benchmark_returns))
    return peer_returns.iloc[-n:].reset_index(drop=True)


def _feature_destruction_checks(
    feature_votes: np.ndarray,
    asset_returns: np.ndarray,
    observed_calmar: float,
    *,
    costs: CostModel,
    ppy: int,
) -> dict[str, object]:
    votes = np.asarray(feature_votes, dtype=float)
    if votes.ndim != 2 or votes.shape[0] != len(asset_returns) or votes.shape[1] < 2:
        return {
            "leave_one_feature_out_passed": False,
            "tie_sensitivity_passed": False,
            "reason": "feature_votes must be shaped (time, features) with >=2 features",
            "worst_leave_one_calmar": float("-inf"),
            "tie_short_calmar": float("-inf"),
        }
    leave_one = []
    for col in range(votes.shape[1]):
        reduced = np.delete(votes, col, axis=1)
        w = np.where(reduced.sum(axis=1) >= 0.0, 1.0, -1.0)
        leave_one.append(compute_metrics(apply_costs(w, asset_returns, costs)[1:], ppy=ppy).calmar)
    tie_short = np.where(votes.sum(axis=1) > 0.0, 1.0, -1.0)
    tie_short_calmar = compute_metrics(apply_costs(tie_short, asset_returns, costs)[1:], ppy=ppy).calmar
    worst = float(np.min(leave_one))
    # Do not require perfection. This is a brittleness guard: losing any one
    # feature should not erase more than 75% of observed Calmar, nor go <= 0.
    leave_pass = worst > 0.0 and worst >= 0.25 * float(observed_calmar)
    tie_pass = tie_short_calmar > 0.0 and tie_short_calmar >= 0.25 * float(observed_calmar)
    return {
        "leave_one_feature_out_passed": bool(leave_pass),
        "tie_sensitivity_passed": bool(tie_pass),
        "leave_one_calmars": [float(x) for x in leave_one],
        "worst_leave_one_calmar": worst,
        "tie_short_calmar": float(tie_short_calmar),
    }


__all__ = [
    "RobustnessCheck",
    "StatisticalRobustnessConfig",
    "StatisticalRobustnessReport",
    "benjamini_hochberg",
    "statistical_robustness_gate",
]
