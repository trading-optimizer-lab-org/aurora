"""Independent metric formulas used to verify final scientific outputs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from aurora.infra.github_performance.contracts import FrozenModel


class MetricFieldResult(FrozenModel):
    field: str
    reported: float | int | None
    recomputed: float | int | None
    absolute_error: float | None
    relative_error: float | None
    absolute_tolerance: float
    relative_tolerance: float
    passed: bool
    reason: str


class MetricEquivalenceReport(FrozenModel):
    passed: bool
    fields: tuple[MetricFieldResult, ...]
    mismatched_fields: tuple[str, ...]


def _undefined_metrics(
    raw_count: int,
    finite_count: int,
) -> dict[str, float | int | None]:
    names = (
        "total_return_pct",
        "cagr_pct",
        "annualized_return_pct",
        "annualized_volatility_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "calmar",
        "profit_factor",
        "win_rate",
        "average_return_pct",
        "median_return_pct",
        "final_nav",
    )
    values: dict[str, float | int | None] = {
        name: None for name in names
    }
    values["period_count_raw"] = raw_count
    values["period_count"] = finite_count
    return values


def recompute_metrics(
    returns: Sequence[float] | np.ndarray,
    *,
    periods_per_year: int,
    undefined_policy: str,
) -> Mapping[str, float | int | None]:
    """Recompute the canonical metric suite without Aurora metric helpers."""

    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if undefined_policy != "null":
        raise ValueError("only the fail-closed null undefined policy is supported")
    raw = np.asarray(returns, dtype=np.float64)
    if raw.ndim != 1:
        raise ValueError("returns must be one-dimensional")
    finite = raw[~np.isnan(raw)]
    if len(finite) < 2 or not np.all(np.isfinite(finite)):
        return _undefined_metrics(len(raw), len(finite))

    nav = np.cumprod(1.0 + finite)
    final_nav = float(nav[-1])
    years = len(raw) / float(periods_per_year)
    if final_nav > 0.0:
        cagr = final_nav ** (1.0 / years) - 1.0
    else:
        cagr = -1.0
    running_peak = np.maximum.accumulate(nav)
    drawdown = nav / running_peak - 1.0
    max_drawdown = float(np.min(drawdown))
    if abs(max_drawdown) < 1e-9:
        if cagr > 0.0:
            calmar = float("inf")
        elif cagr < 0.0:
            calmar = float("-inf")
        else:
            calmar = 0.0
    else:
        calmar = cagr / abs(max_drawdown)
    mean = float(np.mean(finite))
    standard_deviation = float(np.std(finite, ddof=0))
    sharpe = (
        mean / standard_deviation * math.sqrt(periods_per_year)
        if standard_deviation > 1e-12
        else 0.0
    )
    downside = finite[finite < 0.0]
    downside_deviation = (
        float(np.std(downside, ddof=0))
        if len(downside) > 1
        else standard_deviation
    )
    sortino = (
        mean / downside_deviation * math.sqrt(periods_per_year)
        if downside_deviation > 1e-12
        else 0.0
    )
    wins = finite[finite > 0.0]
    losses = finite[finite < 0.0]
    loss_sum = float(np.sum(losses))
    profit_factor = (
        float(np.sum(wins)) / abs(loss_sum)
        if len(losses) and loss_sum != 0.0
        else 0.0
    )
    return {
        "total_return_pct": (final_nav - 1.0) * 100.0,
        "cagr_pct": cagr * 100.0,
        "annualized_return_pct": cagr * 100.0,
        "annualized_volatility_pct": (
            standard_deviation * math.sqrt(periods_per_year) * 100.0
        ),
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown_pct": max_drawdown * 100.0,
        "calmar": calmar,
        "profit_factor": profit_factor,
        "win_rate": len(wins) / len(finite),
        "average_return_pct": mean * 100.0,
        "median_return_pct": float(np.median(finite)) * 100.0,
        "period_count_raw": len(raw),
        "period_count": len(finite),
        "final_nav": final_nav,
    }


def _numeric(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("boolean is not a metric value")
    if isinstance(value, (int, np.integer)):
        return int(value)
    return float(value)


def _compare(
    reported: float | int | None,
    recomputed: float | int | None,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[bool, float | None, float | None, str]:
    if reported is None or recomputed is None:
        passed = reported is None and recomputed is None
        return passed, None, None, "both_null" if passed else "null_mismatch"
    left = float(reported)
    right = float(recomputed)
    if math.isnan(left) or math.isnan(right):
        return False, None, None, "nan_not_comparable"
    if math.isinf(left) or math.isinf(right):
        passed = left == right
        return passed, None, None, "same_infinity" if passed else "infinity_mismatch"
    if left == 0.0 and right == 0.0:
        passed = math.copysign(1.0, left) == math.copysign(1.0, right)
        return passed, 0.0, 0.0, "equal" if passed else "signed_zero_mismatch"
    absolute_error = abs(left - right)
    scale = max(abs(left), abs(right))
    relative_error = absolute_error / scale if scale else 0.0
    passed = (
        absolute_error <= absolute_tolerance
        or relative_error <= relative_tolerance
    )
    return passed, absolute_error, relative_error, (
        "within_tolerance" if passed else "outside_tolerance"
    )


def verify_metric_table(
    reported: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    *,
    tolerances: Mapping[str, Mapping[str, float]],
) -> MetricEquivalenceReport:
    """Compare one reported metric mapping against independent values."""

    fields: list[MetricFieldResult] = []
    for field in sorted(tolerances):
        tolerance = tolerances[field]
        absolute = float(tolerance.get("absolute", 0.0))
        relative = float(tolerance.get("relative", 0.0))
        if absolute < 0.0 or relative < 0.0:
            raise ValueError("metric tolerances must be non-negative")
        reported_value = _numeric(reported.get(field))
        recomputed_value = _numeric(recomputed.get(field))
        passed, absolute_error, relative_error, reason = _compare(
            reported_value,
            recomputed_value,
            absolute,
            relative,
        )
        fields.append(
            MetricFieldResult(
                field=field,
                reported=reported_value,
                recomputed=recomputed_value,
                absolute_error=absolute_error,
                relative_error=relative_error,
                absolute_tolerance=absolute,
                relative_tolerance=relative,
                passed=passed,
                reason=reason,
            )
        )
    mismatched = tuple(item.field for item in fields if not item.passed)
    return MetricEquivalenceReport(
        passed=not mismatched,
        fields=tuple(fields),
        mismatched_fields=mismatched,
    )

