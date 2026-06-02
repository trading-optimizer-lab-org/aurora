"""Search-quality controls for strategy discovery.

This module is intentionally independent from current GitHub workflows. It
contains reusable gates for future runs: live deduplication, feature-history
filters, train-only memory, soft robustness, adaptive budgets, and portfolio
diversity.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SearchQualityConfig:
    near_duplicate_corr_threshold: float = 0.98
    return_fingerprint_decimals: int = 8
    history_start_year: int = 1995
    min_feature_weeks_per_year: int = 26
    min_partial_periods: int = 20
    min_partial_train_cagr: float = 0.0
    max_partial_mdd: float = 0.60
    min_partial_down_positive_pct: float = 0.25
    complexity_feature_soft_limit: int = 6
    min_jobs_per_bucket: int = 1
    soft_robust_min_periods: int = 40
    soft_robust_min_cagr: float = 0.0
    soft_robust_min_sharpe: float = 0.0
    soft_robust_max_mdd: float | None = None
    soft_robust_min_half_cagr: float = -0.10
    periods_per_year: int = 52
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "sharpe": 0.25,
            "calmar": 0.25,
            "cagr": 0.15,
            "mdd": 0.15,
            "positive_years": 0.10,
            "complexity": 0.05,
            "diversity": 0.05,
        }
    )


@dataclass(frozen=True)
class CandidateDecision:
    accepted: bool
    reason: str = ""
    duplicate_of: str = ""


class SearchQualityState:
    """Stateful live deduper for one search job or wave.

    It rejects exact rule clones and near-identical return streams before they
    keep consuming budget.
    """

    def __init__(self, config: SearchQualityConfig | None = None) -> None:
        self.config = config or SearchQualityConfig()
        self._rule_hash_to_candidate: dict[str, str] = {}
        self._return_streams: dict[str, pd.Series] = {}
        self._return_fingerprints: dict[str, str] = {}

    def accept(self, candidate: dict[str, Any], returns: pd.Series | np.ndarray | list[float]) -> CandidateDecision:
        candidate_id = str(candidate.get("candidate_id") or _stable_hash(candidate))
        rule_hash = _rule_hash(candidate)
        if rule_hash in self._rule_hash_to_candidate:
            return CandidateDecision(False, "duplicate_rule", self._rule_hash_to_candidate[rule_hash])

        series = _return_series(returns)
        fingerprint = _return_fingerprint(series, self.config.return_fingerprint_decimals)
        if fingerprint in self._return_fingerprints:
            return CandidateDecision(False, "duplicate_returns", self._return_fingerprints[fingerprint])

        for other_id, other in self._return_streams.items():
            corr = _safe_corr(series, other)
            if corr >= self.config.near_duplicate_corr_threshold:
                return CandidateDecision(False, "near_duplicate_returns", other_id)

        self._rule_hash_to_candidate[rule_hash] = candidate_id
        self._return_fingerprints[fingerprint] = candidate_id
        self._return_streams[candidate_id] = series
        return CandidateDecision(True)


class SearchWaveMemory:
    """Train-only memory passed between waves.

    Validation and locked fields are deliberately dropped. If a run wants to
    learn from previous waves, it must learn from train-only evidence.
    """

    _ALLOWED_KEYS = {
        "candidate_id",
        "method",
        "features",
        "rules",
        "assets",
        "train_score",
        "train_sharpe",
        "train_calmar",
        "train_cagr",
        "train_mdd",
        "train_min_year_return",
        "feature_family",
        "rule_hash",
        "return_fingerprint",
    }

    def __init__(self, max_candidates_per_method: int = 500) -> None:
        self.max_candidates_per_method = int(max_candidates_per_method)
        self._by_method: dict[str, list[dict[str, Any]]] = {}

    def add_candidate(self, *, method: str, candidate: dict[str, Any]) -> None:
        clean = {key: candidate[key] for key in self._ALLOWED_KEYS if key in candidate}
        clean["method"] = str(method)
        bucket = self._by_method.setdefault(str(method), [])
        bucket.append(clean)
        bucket.sort(key=lambda item: float(item.get("train_score", -math.inf)), reverse=True)
        del bucket[self.max_candidates_per_method :]

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {method: [dict(item) for item in rows] for method, rows in self._by_method.items()}


def filter_features_by_history(
    features: list[str] | tuple[str, ...],
    availability: pd.DataFrame,
    *,
    start_year: int,
    min_weeks_per_year: int,
) -> tuple[list[str], list[str]]:
    """Keep features with enough data in every full-enough year since start."""

    mask = pd.DataFrame(availability).copy()
    mask.index = pd.DatetimeIndex(mask.index)
    years = sorted({int(ts.year) for ts in mask.index if int(ts.year) >= int(start_year)})
    kept: list[str] = []
    rejected: list[str] = []
    for feature in features:
        if feature not in mask.columns:
            rejected.append(str(feature))
            continue
        ok = True
        available = mask[str(feature)].fillna(False).astype(bool)
        for year in years:
            year_mask = mask.index.year == year
            if int(year_mask.sum()) < int(min_weeks_per_year):
                continue
            if int(available.loc[year_mask].sum()) < int(min_weeks_per_year):
                ok = False
                break
        (kept if ok else rejected).append(str(feature))
    return kept, rejected


def assign_feature_family(feature: str) -> str:
    lower = str(feature).lower()
    if "vix" in lower or "vx" in lower:
        return "vix"
    if "hyg" in lower or "lqd" in lower or "credit" in lower or "spread" in lower:
        return "credit"
    if "__vol_" in lower or "volatility" in lower or "bb_width" in lower:
        return "volatility"
    if "ma_gap" in lower or "trend" in lower or "drawdown" in lower or "macd" in lower:
        return "trend"
    if "__ret_" in lower or "momentum" in lower or "rsi" in lower or "relative" in lower:
        return "momentum"
    if "sector" in lower or lower.startswith("xl"):
        return "sector"
    if "bond" in lower or "tlt" in lower or "ief" in lower or "shy" in lower:
        return "bond"
    return "other"


def split_features_by_family(features: list[str] | tuple[str, ...]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for feature in features:
        groups.setdefault(assign_feature_family(str(feature)), []).append(str(feature))
    return groups


def robust_train_score(row: dict[str, Any] | pd.Series, config: SearchQualityConfig | None = None) -> float:
    config = config or SearchQualityConfig()
    item = dict(row)
    sharpe = _bounded(float(item.get("train_sharpe", 0.0) or 0.0), -2.0, 3.0) / 3.0
    calmar = _bounded(float(item.get("train_calmar", 0.0) or 0.0), -2.0, 5.0) / 5.0
    cagr = _bounded(float(item.get("train_cagr", 0.0) or 0.0), -0.20, 0.50) / 0.50
    mdd = 1.0 - _bounded(abs(float(item.get("train_mdd", 0.0) or 0.0)), 0.0, 0.80) / 0.80
    positive_years = _bounded(float(item.get("train_positive_years_pct", 0.0) or 0.0), 0.0, 1.0)
    feature_count = int(float(item.get("feature_count", _feature_count(item)) or 0))
    complexity = 1.0 / (1.0 + max(0, feature_count - int(config.complexity_feature_soft_limit)))
    diversity = _bounded(float(item.get("diversity_score", 1.0) or 0.0), 0.0, 1.0)
    weights = config.score_weights
    return float(
        weights["sharpe"] * sharpe
        + weights["calmar"] * calmar
        + weights["cagr"] * cagr
        + weights["mdd"] * mdd
        + weights["positive_years"] * positive_years
        + weights["complexity"] * complexity
        + weights["diversity"] * diversity
    )


def early_prune_reason(metrics: dict[str, Any], config: SearchQualityConfig | None = None) -> str:
    config = config or SearchQualityConfig()
    periods = int(float(metrics.get("periods", 0) or 0))
    if periods < int(config.min_partial_periods):
        return ""
    if float(metrics.get("train_cagr", 0.0) or 0.0) < float(config.min_partial_train_cagr):
        return "negative_train_cagr"
    if abs(float(metrics.get("train_mdd", 0.0) or 0.0)) > float(config.max_partial_mdd):
        return "drawdown_too_deep"
    if float(metrics.get("train_down_positive_pct", 1.0) or 0.0) < float(config.min_partial_down_positive_pct):
        return "downside_hit_rate_too_low"
    return ""


def allocate_adaptive_budget(
    stats: pd.DataFrame,
    *,
    total_jobs: int,
    min_jobs_per_bucket: int = 1,
) -> dict[str, int]:
    """Allocate more jobs to buckets producing unique robust candidates."""

    frame = pd.DataFrame(stats).copy()
    if frame.empty:
        return {}
    buckets = [str(value) for value in frame["bucket"].tolist()]
    total_jobs = int(total_jobs)
    floor = max(0, int(min_jobs_per_bucket))
    if total_jobs <= len(buckets) * floor:
        allocation = {bucket: floor for bucket in buckets}
        return _normalise_allocation(allocation, total_jobs)

    frame["hours"] = pd.to_numeric(frame.get("hours", 0.0), errors="coerce").fillna(0.0).clip(lower=1e-9)
    frame["unique_robust"] = pd.to_numeric(frame.get("unique_robust", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
    frame["rate"] = (frame["unique_robust"] + 0.25) / frame["hours"]
    remaining = total_jobs - len(buckets) * floor
    rates = frame["rate"].to_numpy(dtype=float)
    shares = rates / rates.sum() if rates.sum() > 0.0 else np.full(len(rates), 1.0 / len(rates))
    allocation = {bucket: floor + int(math.floor(float(share) * remaining)) for bucket, share in zip(buckets, shares)}
    return _normalise_allocation(allocation, total_jobs, priority=list(frame.sort_values("rate", ascending=False)["bucket"]))


def simple_soft_robustness(
    returns: pd.Series | np.ndarray | list[float],
    config: SearchQualityConfig | None = None,
) -> dict[str, Any]:
    """Fast, loose robustness check for search-time filtering."""

    config = config or SearchQualityConfig()
    series = _return_series(returns).dropna()
    values = series.to_numpy(dtype=float)
    reasons: list[str] = []
    if len(values) < int(config.soft_robust_min_periods):
        reasons.append("too_few_periods")
    metrics = _metrics(values, int(config.periods_per_year))
    half = max(1, len(values) // 2)
    first = _metrics(values[:half], int(config.periods_per_year))
    second = _metrics(values[half:], int(config.periods_per_year))
    if metrics["cagr"] < float(config.soft_robust_min_cagr):
        reasons.append("cagr_too_low")
    if metrics["sharpe"] < float(config.soft_robust_min_sharpe):
        reasons.append("sharpe_too_low")
    if config.soft_robust_max_mdd is not None and abs(metrics["mdd"]) > float(config.soft_robust_max_mdd):
        reasons.append("mdd_too_deep")
    if min(first["cagr"], second["cagr"]) < float(config.soft_robust_min_half_cagr):
        reasons.append("one_half_too_weak")
    return {
        "soft_robust_pass": not reasons,
        "soft_robust_fail_reason": ";".join(reasons),
        "soft_robust_periods": int(len(values)),
        "soft_robust_cagr": float(metrics["cagr"]),
        "soft_robust_sharpe": float(metrics["sharpe"]),
        "soft_robust_mdd": float(metrics["mdd"]),
        "soft_robust_half1_cagr": float(first["cagr"]),
        "soft_robust_half2_cagr": float(second["cagr"]),
    }


def select_diverse_portfolio(
    candidates: pd.DataFrame,
    returns_by_candidate: dict[str, pd.Series],
    *,
    max_size: int,
    max_corr: float,
    score_column: str = "score",
) -> pd.DataFrame:
    frame = pd.DataFrame(candidates).copy()
    if frame.empty:
        return frame
    frame = frame.sort_values(score_column, ascending=False)
    selected_rows: list[pd.Series] = []
    selected_ids: list[str] = []
    for _, row in frame.iterrows():
        candidate_id = str(row["candidate_id"])
        series = returns_by_candidate.get(candidate_id)
        if series is None:
            continue
        if all(_safe_corr(_return_series(series), _return_series(returns_by_candidate[other])) < float(max_corr) for other in selected_ids):
            selected_rows.append(row)
            selected_ids.append(candidate_id)
        if len(selected_rows) >= int(max_size):
            break
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def _normalise_allocation(
    allocation: dict[str, int],
    total_jobs: int,
    priority: list[str] | None = None,
) -> dict[str, int]:
    priority = [str(item) for item in (priority or allocation.keys())]
    while sum(allocation.values()) < int(total_jobs):
        for bucket in priority:
            allocation[bucket] += 1
            if sum(allocation.values()) >= int(total_jobs):
                break
    while sum(allocation.values()) > int(total_jobs):
        for bucket in reversed(priority):
            if allocation[bucket] > 0:
                allocation[bucket] -= 1
            if sum(allocation.values()) <= int(total_jobs):
                break
    return allocation


def _rule_hash(candidate: dict[str, Any]) -> str:
    keys = ("rules", "features", "assets", "asset_weights", "signal_weights", "threshold", "method")
    payload = {key: candidate.get(key) for key in keys if key in candidate}
    return _stable_hash(payload)


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _return_fingerprint(series: pd.Series, decimals: int) -> str:
    rounded = np.round(series.to_numpy(dtype=float), int(decimals))
    return hashlib.sha256(rounded.tobytes()).hexdigest()[:16]


def _return_series(values: pd.Series | np.ndarray | list[float]) -> pd.Series:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce").astype(float).dropna().reset_index(drop=True)
    return pd.Series(values, dtype=float).dropna().reset_index(drop=True)


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    size = min(len(left), len(right))
    if size < 3:
        return 0.0
    a = left.iloc[:size].to_numpy(dtype=float)
    b = right.iloc[:size].to_numpy(dtype=float)
    if float(np.std(a)) <= 1e-12 or float(np.std(b)) <= 1e-12:
        return 1.0 if np.allclose(a, b) else 0.0
    corr = float(np.corrcoef(a, b)[0, 1])
    return corr if np.isfinite(corr) else 0.0


def _feature_count(item: dict[str, Any]) -> int:
    features = item.get("features", ())
    if isinstance(features, str):
        return len([part for part in features.split("|") if part])
    try:
        return len(features)
    except TypeError:
        return 0


def _bounded(value: float, low: float, high: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(min(max(value, low), high))


def _metrics(values: np.ndarray, ppy: int) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {"cagr": 0.0, "mdd": 0.0, "sharpe": 0.0}
    equity = np.cumprod(1.0 + values)
    years = max(len(values) / float(ppy), 1e-9)
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if equity[-1] > 0.0 else -1.0
    peak = np.maximum.accumulate(equity)
    mdd = float(np.min(equity / peak - 1.0))
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    sharpe = float(np.mean(values) / std * math.sqrt(float(ppy))) if std > 1e-12 else 0.0
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe}


__all__ = [
    "CandidateDecision",
    "SearchQualityConfig",
    "SearchQualityState",
    "SearchWaveMemory",
    "allocate_adaptive_budget",
    "assign_feature_family",
    "early_prune_reason",
    "filter_features_by_history",
    "robust_train_score",
    "select_diverse_portfolio",
    "simple_soft_robustness",
    "split_features_by_family",
]
