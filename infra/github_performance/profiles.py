"""Immutable prior-run performance profiles with exact reuse gates."""

from __future__ import annotations

import json
import math
import os
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    CodeSha,
    FrozenModel,
    PilotResult,
    Sha256,
    canonical_sha256,
    deep_thaw_json,
)


_CONFIDENCE_Z = 1.959963984540054


class ProfileConflict(RuntimeError):
    """Raised when an immutable profile path contains different evidence."""


class PerformanceProfileKey(FrozenModel):
    """Exact compatibility key required before historical reuse."""

    code_sha: CodeSha
    workflow_sha256: Sha256
    spec_sha256: Sha256
    snapshot_sha256: Sha256
    dependency_lock_sha256: Sha256
    runner_contract_sha256: Sha256


class TimingDistribution(FrozenModel):
    """Measured end-to-end timing with uncertainty for one cache condition."""

    condition: Literal["cold", "warm"]
    samples_seconds: tuple[float, ...]
    sample_count: int = Field(ge=2)
    mean_seconds: float = Field(ge=0)
    median_seconds: float = Field(ge=0)
    p95_seconds: float = Field(ge=0)
    standard_deviation_seconds: float = Field(ge=0)
    standard_error_seconds: float = Field(ge=0)
    confidence_low_seconds: float = Field(ge=0)
    confidence_high_seconds: float = Field(ge=0)
    prediction_low_seconds: float = Field(ge=0)
    prediction_high_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _validate_distribution(self) -> TimingDistribution:
        values = (
            *self.samples_seconds,
            self.mean_seconds,
            self.median_seconds,
            self.p95_seconds,
            self.standard_deviation_seconds,
            self.standard_error_seconds,
            self.confidence_low_seconds,
            self.confidence_high_seconds,
            self.prediction_low_seconds,
            self.prediction_high_seconds,
        )
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("timing values must be finite and nonnegative")
        if len(self.samples_seconds) != self.sample_count:
            raise ValueError("sample_count must match samples_seconds")
        if self.confidence_low_seconds > self.confidence_high_seconds:
            raise ValueError("confidence interval is reversed")
        if self.prediction_low_seconds > self.prediction_high_seconds:
            raise ValueError("prediction interval is reversed")
        return self


def _quantile_nearest_rank(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return float(ordered[rank - 1])


def build_timing_distribution(
    *,
    condition: Literal["cold", "warm"],
    samples_seconds: Sequence[float],
) -> TimingDistribution:
    """Build deterministic uncertainty evidence from measured samples."""

    samples = tuple(float(value) for value in samples_seconds)
    if len(samples) < 2:
        raise ValueError("timing distribution requires at least two samples")
    if not all(math.isfinite(value) and value >= 0 for value in samples):
        raise ValueError("timing samples must be finite and nonnegative")
    count = len(samples)
    mean = statistics.fmean(samples)
    deviation = statistics.stdev(samples)
    standard_error = deviation / math.sqrt(count)
    confidence_delta = _CONFIDENCE_Z * standard_error
    prediction_delta = (
        _CONFIDENCE_Z * deviation * math.sqrt(1.0 + 1.0 / count)
    )
    return TimingDistribution(
        condition=condition,
        samples_seconds=samples,
        sample_count=count,
        mean_seconds=mean,
        median_seconds=statistics.median(samples),
        p95_seconds=_quantile_nearest_rank(samples, 0.95),
        standard_deviation_seconds=deviation,
        standard_error_seconds=standard_error,
        confidence_low_seconds=max(0.0, mean - confidence_delta),
        confidence_high_seconds=mean + confidence_delta,
        prediction_low_seconds=max(0.0, mean - prediction_delta),
        prediction_high_seconds=mean + prediction_delta,
    )


class PerformanceProfile(FrozenModel):
    """Immutable operational profile, blind to all candidate quality."""

    schema_version: Literal["1"] = "1"
    key: PerformanceProfileKey
    cold: TimingDistribution
    warm: TimingDistribution
    pilot_result: PilotResult
    source_run_id: str = Field(min_length=1)
    created_at: datetime
    profile_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_identity(self) -> PerformanceProfile:
        if self.cold.condition != "cold" or self.warm.condition != "warm":
            raise ValueError("profile must contain distinct cold and warm data")
        if self.profile_sha256 != canonical_sha256(self._identity()):
            raise ValueError("performance profile hash is invalid")
        return self

    def _identity(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "key": self.key,
            "cold": self.cold,
            "warm": self.warm,
            "pilot_result": self.pilot_result,
            "source_run_id": self.source_run_id,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        *,
        key: PerformanceProfileKey,
        cold: TimingDistribution,
        warm: TimingDistribution,
        pilot_result: PilotResult,
        source_run_id: str,
        created_at: datetime,
    ) -> PerformanceProfile:
        identity = {
            "schema_version": "1",
            "key": key,
            "cold": cold,
            "warm": warm,
            "pilot_result": pilot_result,
            "source_run_id": source_run_id,
            "created_at": created_at,
        }
        return cls(
            **identity,
            profile_sha256=canonical_sha256(identity),
        )


class ProfileReuseDecision(FrozenModel):
    """Fail-closed decision over exact identity and observed timings."""

    reuse_allowed: bool
    pilot_required: bool
    reason_codes: tuple[str, ...]
    profile_sha256: Sha256 | None


def assess_profile_reuse(
    profile: PerformanceProfile,
    requested_key: PerformanceProfileKey,
    *,
    observed_seconds: Mapping[str, float] | None = None,
) -> ProfileReuseDecision:
    """Reuse only exact profiles whose observations remain in-band."""

    if profile.key != requested_key:
        return ProfileReuseDecision(
            reuse_allowed=False,
            pilot_required=True,
            reason_codes=("PROFILE_KEY_MISMATCH",),
            profile_sha256=profile.profile_sha256,
        )
    observations = dict(observed_seconds or {})
    unknown = set(observations).difference({"cold", "warm"})
    if unknown:
        raise ValueError(
            "unknown profile observation conditions: "
            + ",".join(sorted(unknown))
        )
    for condition, value in observations.items():
        measured = float(value)
        if not math.isfinite(measured) or measured < 0:
            raise ValueError("observed timing must be finite and nonnegative")
        distribution = (
            profile.cold if condition == "cold" else profile.warm
        )
        if not (
            distribution.prediction_low_seconds
            <= measured
            <= distribution.prediction_high_seconds
        ):
            return ProfileReuseDecision(
                reuse_allowed=False,
                pilot_required=True,
                reason_codes=(
                    "PROFILE_OBSERVATION_OUTSIDE_CONFIDENCE_BAND",
                ),
                profile_sha256=profile.profile_sha256,
            )
    return ProfileReuseDecision(
        reuse_allowed=True,
        pilot_required=False,
        reason_codes=(),
        profile_sha256=profile.profile_sha256,
    )


def _profile_bytes(profile: PerformanceProfile) -> bytes:
    return (
        json.dumps(
            deep_thaw_json(profile),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_performance_profile(
    profile: PerformanceProfile,
    path: Path,
) -> Path:
    """Publish an immutable profile atomically."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _profile_bytes(profile)
    if target.exists():
        if target.read_bytes() != payload:
            raise ProfileConflict(
                f"immutable performance profile conflicts: {target}"
            )
        return target
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    try:
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise ProfileConflict(
                    f"immutable performance profile conflicts: {target}"
                )
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_performance_profile(path: Path) -> PerformanceProfile:
    """Load and verify one immutable performance profile."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PerformanceProfile.model_validate(payload)
