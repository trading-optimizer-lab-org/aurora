"""Measured selection among scientifically equivalent execution engines."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.profiles import TimingDistribution


EngineName = Literal[
    "python_reference",
    "numpy",
    "numba",
    "arrow",
    "duckdb",
    "processes",
    "threads",
]


class EngineTrial(FrozenModel):
    """One equal-input, end-to-end engine measurement."""

    schema_version: Literal["1"] = "1"
    engine: EngineName
    capability_available: bool
    capability_reason: str | None
    scientific_output_sha256: Sha256 | None
    cold: TimingDistribution | None
    warm: TimingDistribution | None
    end_to_end_includes_compilation: bool
    end_to_end_includes_warmup: bool
    failure_codes: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_evidence(self) -> EngineTrial:
        if self.capability_available:
            if self.scientific_output_sha256 is None:
                raise ValueError(
                    "available engine requires scientific output hash"
                )
            if self.cold is None or self.warm is None:
                raise ValueError(
                    "available engine requires cold and warm measurements"
                )
            if not self.end_to_end_includes_compilation:
                raise ValueError(
                    "end-to-end engine timing must include compilation"
                )
            if not self.end_to_end_includes_warmup:
                raise ValueError(
                    "end-to-end engine timing must include warm-up"
                )
            if self.cold.condition != "cold" or self.warm.condition != "warm":
                raise ValueError(
                    "engine trial timing conditions are inconsistent"
                )
        else:
            if not self.capability_reason:
                raise ValueError(
                    "unavailable engine requires capability_reason"
                )
            if (
                self.scientific_output_sha256 is not None
                or self.cold is not None
                or self.warm is not None
            ):
                raise ValueError(
                    "unavailable engine cannot contain timing evidence"
                )
        return self


class EngineOutcome(FrozenModel):
    """Auditable disposition of one measured or unavailable engine."""

    engine: EngineName
    status: Literal[
        "selected",
        "reference",
        "reference_fallback",
        "rejected",
        "equivalent_not_selected",
        "capability_missing",
    ]
    equivalent: bool
    reason_codes: tuple[str, ...]
    cold_mean_seconds: float | None
    warm_mean_seconds: float | None


class EngineDecision(FrozenModel):
    """Fastest proven equivalent engine with explicit Python fallback."""

    schema_version: Literal["1"] = "1"
    selected_engine: EngineName
    reference_engine: Literal["python_reference"]
    reference_fallback_preserved: bool
    scientific_outputs_equal: bool
    cold_speedup: float
    warm_speedup: float
    outcomes: tuple[EngineOutcome, ...]
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _validate_identity(self) -> EngineDecision:
        identity = {
            "schema_version": self.schema_version,
            "selected_engine": self.selected_engine,
            "reference_engine": self.reference_engine,
            "reference_fallback_preserved": (
                self.reference_fallback_preserved
            ),
            "scientific_outputs_equal": self.scientific_outputs_equal,
            "cold_speedup": self.cold_speedup,
            "warm_speedup": self.warm_speedup,
            "outcomes": self.outcomes,
        }
        if self.decision_sha256 != canonical_sha256(identity):
            raise ValueError("engine decision hash is invalid")
        return self


def _speed_reasons(
    trial: EngineTrial,
    reference: EngineTrial,
) -> tuple[str, ...]:
    if trial.cold is None or trial.warm is None:
        raise ValueError("available trial is missing timing evidence")
    if reference.cold is None or reference.warm is None:
        raise ValueError("reference trial is missing timing evidence")
    reasons: list[str] = []
    for name, measured, baseline in (
        ("COLD", trial.cold, reference.cold),
        ("WARM", trial.warm, reference.warm),
    ):
        if measured.mean_seconds >= baseline.mean_seconds:
            reasons.append(f"{name}_NOT_FASTER")
        elif (
            measured.confidence_high_seconds
            >= baseline.confidence_low_seconds
        ):
            reasons.append(f"{name}_UNCERTAINTY_OVERLAP")
    return tuple(reasons)


def _outcome(
    trial: EngineTrial,
    *,
    status: str,
    equivalent: bool,
    reason_codes: tuple[str, ...],
) -> EngineOutcome:
    return EngineOutcome(
        engine=trial.engine,
        status=status,
        equivalent=equivalent,
        reason_codes=reason_codes,
        cold_mean_seconds=(
            trial.cold.mean_seconds if trial.cold is not None else None
        ),
        warm_mean_seconds=(
            trial.warm.mean_seconds if trial.warm is not None else None
        ),
    )


def select_fastest_equivalent_engine(
    trials: Sequence[EngineTrial],
) -> EngineDecision:
    """Select only a faster engine with equal scientific output bytes."""

    ordered = tuple(trials)
    references = tuple(
        trial
        for trial in ordered
        if trial.engine == "python_reference"
    )
    if len(references) != 1 or not references[0].capability_available:
        raise ValueError(
            "exactly one available python_reference trial is mandatory"
        )
    reference = references[0]
    if reference.cold is None or reference.warm is None:
        raise ValueError("python_reference lacks timing evidence")
    candidates: list[EngineTrial] = []
    provisional: dict[str, EngineOutcome] = {}
    for trial in ordered:
        if trial.engine == "python_reference":
            continue
        if not trial.capability_available:
            provisional[trial.engine] = _outcome(
                trial,
                status="capability_missing",
                equivalent=False,
                reason_codes=trial.failure_codes
                or ("CAPABILITY_MISSING",),
            )
            continue
        equivalent = (
            trial.scientific_output_sha256
            == reference.scientific_output_sha256
        )
        if not equivalent:
            provisional[trial.engine] = _outcome(
                trial,
                status="rejected",
                equivalent=False,
                reason_codes=("SCIENTIFIC_OUTPUT_MISMATCH",),
            )
            continue
        reasons = _speed_reasons(trial, reference)
        if reasons:
            provisional[trial.engine] = _outcome(
                trial,
                status="rejected",
                equivalent=True,
                reason_codes=reasons,
            )
            continue
        candidates.append(trial)

    selected = min(
        candidates,
        key=lambda trial: (
            trial.cold.mean_seconds + trial.warm.mean_seconds,
            trial.engine,
        ),
        default=reference,
    )
    outcomes: list[EngineOutcome] = []
    for trial in ordered:
        if trial.engine == "python_reference":
            outcomes.append(
                _outcome(
                    trial,
                    status=(
                        "reference_fallback"
                        if selected is reference
                        else "reference"
                    ),
                    equivalent=True,
                    reason_codes=(),
                )
            )
        elif trial.engine == selected.engine:
            outcomes.append(
                _outcome(
                    trial,
                    status="selected",
                    equivalent=True,
                    reason_codes=(),
                )
            )
        elif trial.engine in provisional:
            outcomes.append(provisional[trial.engine])
        else:
            outcomes.append(
                _outcome(
                    trial,
                    status="equivalent_not_selected",
                    equivalent=True,
                    reason_codes=("FASTER_EQUIVALENT_NOT_FASTEST",),
                )
            )
    if selected.cold is None or selected.warm is None:
        raise ValueError("selected engine lacks timing evidence")
    identity = {
        "schema_version": "1",
        "selected_engine": selected.engine,
        "reference_engine": "python_reference",
        "reference_fallback_preserved": True,
        "scientific_outputs_equal": True,
        "cold_speedup": (
            reference.cold.mean_seconds / selected.cold.mean_seconds
            if selected.cold.mean_seconds > 0
            else 1.0
        ),
        "warm_speedup": (
            reference.warm.mean_seconds / selected.warm.mean_seconds
            if selected.warm.mean_seconds > 0
            else 1.0
        ),
        "outcomes": tuple(outcomes),
    }
    return EngineDecision(
        **identity,
        decision_sha256=canonical_sha256(identity),
    )


def detect_engine_capabilities() -> Mapping[EngineName, bool]:
    """Report capabilities without installing optional dependencies."""

    return {
        "python_reference": True,
        "numpy": importlib.util.find_spec("numpy") is not None,
        "numba": importlib.util.find_spec("numba") is not None,
        "arrow": importlib.util.find_spec("pyarrow") is not None,
        "duckdb": importlib.util.find_spec("duckdb") is not None,
        "processes": True,
        "threads": True,
    }


def _write_json(path: Path, payload: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def write_engine_trials(
    trials: Sequence[EngineTrial],
    path: Path,
) -> Path:
    """Publish every measured and missing-capability outcome."""

    return _write_json(
        Path(path),
        {
            "schema_version": "1",
            "trials": tuple(trials),
        },
    )


def write_engine_decision(
    decision: EngineDecision,
    path: Path,
) -> Path:
    """Publish the auditable engine decision."""

    return _write_json(Path(path), decision)
