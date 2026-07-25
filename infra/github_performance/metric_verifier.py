"""Independent metric formulas used to verify final scientific outputs."""

from __future__ import annotations

import math
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, field_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    deep_freeze_json,
    deep_thaw_json,
)
from aurora.infra.github_performance.shard_planner import sha256_file


METRIC_INPUT_SCHEMA = pa.schema(
    [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field(
            "returns",
            pa.list_(pa.field("item", pa.float64(), nullable=True)),
            nullable=False,
        ),
        pa.field("periods_per_year", pa.int32(), nullable=False),
        pa.field("undefined_policy", pa.string(), nullable=False),
        pa.field("reported_json", pa.string(), nullable=False),
    ],
    metadata={b"schema_version": b"1"},
)

DEFAULT_METRIC_TOLERANCES: Mapping[str, Mapping[str, float]] = {
    "total_return_pct": {"absolute": 0.0001, "relative": 1e-12},
    "cagr_pct": {"absolute": 0.000051, "relative": 1e-12},
    "annualized_return_pct": {"absolute": 0.000051, "relative": 1e-12},
    "annualized_volatility_pct": {
        "absolute": 0.000051,
        "relative": 1e-12,
    },
    "sharpe": {"absolute": 0.000051, "relative": 1e-12},
    "sortino": {"absolute": 0.000051, "relative": 1e-12},
    "max_drawdown_pct": {"absolute": 0.000051, "relative": 1e-12},
    "calmar": {"absolute": 0.000051, "relative": 1e-12},
    "profit_factor": {"absolute": 0.000051, "relative": 1e-12},
    "win_rate": {"absolute": 0.000051, "relative": 1e-12},
    "average_return_pct": {"absolute": 1e-12, "relative": 1e-12},
    "median_return_pct": {"absolute": 1e-12, "relative": 1e-12},
    "period_count_raw": {"absolute": 0.0, "relative": 0.0},
    "period_count": {"absolute": 0.0, "relative": 0.0},
    "final_nav": {"absolute": 0.00000051, "relative": 1e-12},
}


class MetricInputRecord(FrozenModel):
    """Raw scientific inputs plus values reported by the primary engine."""

    unit_key: str
    split: str
    returns: tuple[float, ...]
    periods_per_year: int = Field(ge=1)
    undefined_policy: str
    reported: Mapping[str, float | int | None]

    @field_validator("reported", mode="after")
    @classmethod
    def _freeze_reported(
        cls,
        value: Mapping[str, float | int | None],
    ) -> Mapping[str, float | int | None]:
        return deep_freeze_json(value)

    @field_validator("undefined_policy")
    @classmethod
    def _known_undefined_policy(cls, value: str) -> str:
        if value != "null":
            raise ValueError("only the fail-closed null policy is supported")
        return value


class MetricMismatch(FrozenModel):
    unit_key: str
    split: str
    field: str
    reported: float | int | None
    recomputed: float | int | None
    absolute_error: float | None
    relative_error: float | None
    absolute_tolerance: float
    relative_tolerance: float
    reason: str


class IndependentMetricVerification(FrozenModel):
    schema_version: str = "1"
    passed: bool
    records_verified: int = Field(ge=0)
    fields_compared: int = Field(ge=0)
    mismatches: tuple[MetricMismatch, ...]


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


def _encode_metric_value(value: float | int | None) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("boolean is not a metric value")
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    if math.isnan(number):
        return {"nonfinite": "nan"}
    if math.isinf(number):
        return {"nonfinite": "+inf" if number > 0.0 else "-inf"}
    return number


def _decode_metric_value(value: Any) -> float | int | None:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, Mapping):
        marker = value.get("nonfinite")
        if marker == "nan":
            return float("nan")
        if marker == "+inf":
            return float("inf")
        if marker == "-inf":
            return float("-inf")
    raise ValueError("invalid encoded metric value")


def _reported_json(
    reported: Mapping[str, float | int | None],
) -> str:
    payload = {
        str(field): _encode_metric_value(value)
        for field, value in sorted(reported.items())
    }
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _read_reported_json(value: str) -> Mapping[str, float | int | None]:
    payload = json.loads(value)
    if not isinstance(payload, Mapping):
        raise ValueError("reported metrics must be a mapping")
    return {
        str(field): _decode_metric_value(metric)
        for field, metric in payload.items()
    }


def write_metric_inputs(
    path: Path,
    records: Sequence[MetricInputRecord],
) -> Path:
    """Write deterministic, independently reusable metric evidence."""

    ordered = tuple(
        sorted(records, key=lambda item: (item.unit_key, item.split))
    )
    identities = [(item.unit_key, item.split) for item in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate metric input identity")
    rows = [
        {
            "unit_key": record.unit_key,
            "split": record.split,
            "returns": list(record.returns),
            "periods_per_year": record.periods_per_year,
            "undefined_policy": record.undefined_policy,
            "reported_json": _reported_json(record.reported),
        }
        for record in ordered
    ]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    table = pa.Table.from_pylist(rows, schema=METRIC_INPUT_SCHEMA)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        version="2.6",
    )
    temporary.replace(destination)
    return destination


def read_metric_inputs(path: Path) -> tuple[MetricInputRecord, ...]:
    table = pq.read_table(Path(path), schema=METRIC_INPUT_SCHEMA)
    records = tuple(
        MetricInputRecord(
            unit_key=str(row["unit_key"]),
            split=str(row["split"]),
            returns=tuple(float(value) for value in row["returns"]),
            periods_per_year=int(row["periods_per_year"]),
            undefined_policy=str(row["undefined_policy"]),
            reported=_read_reported_json(str(row["reported_json"])),
        )
        for row in table.to_pylist()
    )
    identities = [(item.unit_key, item.split) for item in records]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate metric input identity")
    return records


def _normalise_undefined(
    metrics: Mapping[str, float | int | None],
    undefined_policy: str,
) -> Mapping[str, float | int | None]:
    if undefined_policy != "null":
        raise ValueError("only the fail-closed null policy is supported")
    normalised: dict[str, float | int | None] = {}
    for field, value in metrics.items():
        if (
            isinstance(value, (float, np.floating))
            and not math.isfinite(float(value))
        ):
            normalised[field] = None
        else:
            normalised[field] = value
    return normalised


def verify_metric_inputs(
    records: Sequence[MetricInputRecord],
    *,
    tolerances: Mapping[str, Mapping[str, float]] = (
        DEFAULT_METRIC_TOLERANCES
    ),
) -> IndependentMetricVerification:
    """Recompute every declared field from raw returns."""

    mismatches: list[MetricMismatch] = []
    fields_compared = 0
    for record in records:
        unknown = sorted(set(record.reported) - set(tolerances))
        if unknown:
            raise ValueError(
                "metric inputs contain fields without a tolerance: "
                + ", ".join(unknown)
            )
        recomputed = _normalise_undefined(
            recompute_metrics(
                record.returns,
                periods_per_year=record.periods_per_year,
                undefined_policy=record.undefined_policy,
            ),
            record.undefined_policy,
        )
        selected_tolerances = {
            field: tolerances[field] for field in record.reported
        }
        comparison = verify_metric_table(
            record.reported,
            recomputed,
            tolerances=selected_tolerances,
        )
        fields_compared += len(comparison.fields)
        for field in comparison.fields:
            if field.passed:
                continue
            mismatches.append(
                MetricMismatch(
                    unit_key=record.unit_key,
                    split=record.split,
                    field=field.field,
                    reported=field.reported,
                    recomputed=field.recomputed,
                    absolute_error=field.absolute_error,
                    relative_error=field.relative_error,
                    absolute_tolerance=field.absolute_tolerance,
                    relative_tolerance=field.relative_tolerance,
                    reason=field.reason,
                )
            )
    return IndependentMetricVerification(
        passed=not mismatches,
        records_verified=len(records),
        fields_compared=fields_compared,
        mismatches=tuple(mismatches),
    )


def independent_metric_verification_payload(
    report: IndependentMetricVerification,
    metric_inputs_path: Path,
) -> Mapping[str, Any]:
    report_payload = deep_thaw_json(report)
    for mismatch in report_payload["mismatches"]:
        mismatch["reported"] = _encode_metric_value(
            mismatch["reported"]
        )
        mismatch["recomputed"] = _encode_metric_value(
            mismatch["recomputed"]
        )
    return {
        **report_payload,
        "metric_inputs_path": Path(metric_inputs_path).name,
        "metric_inputs_sha256": sha256_file(Path(metric_inputs_path)),
    }


def write_independent_metric_verification(
    report: IndependentMetricVerification,
    metric_inputs_path: Path,
    path: Path,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            independent_metric_verification_payload(
                report,
                Path(metric_inputs_path),
            ),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
