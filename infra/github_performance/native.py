"""Profile-gated acceleration with ordered evidence and a safe fallback."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.engines import (
    EngineDecision,
    EngineName,
    EngineTrial,
    select_fastest_equivalent_engine,
)


OptimizationStage = Literal[
    "algorithm",
    "shared_computation",
    "vectorization",
    "numpy_arrow_duckdb",
    "numba",
    "rust",
]
OptimizationDisposition = Literal[
    "rejected",
    "not_applicable",
    "measured",
    "selected",
    "not_reached",
]
_OPTIMIZATION_ORDER: tuple[OptimizationStage, ...] = (
    "algorithm",
    "shared_computation",
    "vectorization",
    "numpy_arrow_duckdb",
    "numba",
    "rust",
)


class HotPathQualificationContract(FrozenModel):
    """Strict safety properties supplied by the measured workload owner."""

    schema_version: Literal["1"] = "1"
    pure_bounded_io: StrictBool
    network_access: StrictBool
    mutable_external_state: StrictBool
    python_reference_available: StrictBool
    frequently_changing_experimental_code: StrictBool = False


class OptimizationStageEvidence(FrozenModel):
    """One immutable step in the mandatory optimization order."""

    stage: OptimizationStage
    disposition: OptimizationDisposition
    reason_codes: tuple[str, ...]
    measured_speedup: float | None = Field(default=None, ge=0)
    scientific_outputs_equal: bool | None = None

    @model_validator(mode="after")
    def _validate_measurement(self) -> OptimizationStageEvidence:
        measured = self.disposition in {"measured", "selected"}
        if measured and (
            self.measured_speedup is None
            or self.scientific_outputs_equal is None
        ):
            raise ValueError(
                "measured optimization evidence requires speed and equivalence"
            )
        if not measured and self.measured_speedup is not None:
            raise ValueError(
                "unmeasured optimization evidence cannot contain speed"
            )
        if self.disposition in {"rejected", "not_applicable"} and not (
            self.reason_codes
        ):
            raise ValueError(
                "rejected or inapplicable optimization requires a reason"
            )
        return self


class HotPathProfile(FrozenModel):
    schema_version: Literal["1"] = "1"
    node_name: str
    node_seconds: float = Field(gt=0)
    workflow_seconds: float = Field(gt=0)
    invocation_count: int = Field(ge=1)
    measured_fraction: float = Field(ge=0, le=1)
    pure_bounded_io: bool
    network_access: bool
    mutable_external_state: bool
    python_reference_available: bool
    frequently_changing_experimental_code: bool
    profile_sha256: Sha256

    @model_validator(mode="after")
    def _validate_identity(self) -> HotPathProfile:
        expected_fraction = self.node_seconds / self.workflow_seconds
        if not math.isclose(
            self.measured_fraction,
            expected_fraction,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("hot-path fraction does not match measured time")
        identity = {
            "schema_version": self.schema_version,
            "node_name": self.node_name,
            "node_seconds": self.node_seconds,
            "workflow_seconds": self.workflow_seconds,
            "invocation_count": self.invocation_count,
            "measured_fraction": self.measured_fraction,
            "pure_bounded_io": self.pure_bounded_io,
            "network_access": self.network_access,
            "mutable_external_state": self.mutable_external_state,
            "python_reference_available": self.python_reference_available,
            "frequently_changing_experimental_code": (
                self.frequently_changing_experimental_code
            ),
        }
        if self.profile_sha256 != canonical_sha256(identity):
            raise ValueError("hot-path profile hash is invalid")
        return self

    @classmethod
    def create(
        cls,
        *,
        node_name: str,
        node_seconds: float,
        workflow_seconds: float,
        invocation_count: int,
        pure_bounded_io: bool,
        network_access: bool,
        mutable_external_state: bool,
        python_reference_available: bool,
        frequently_changing_experimental_code: bool = False,
    ) -> HotPathProfile:
        fraction = float(node_seconds) / float(workflow_seconds)
        identity = {
            "schema_version": "1",
            "node_name": node_name,
            "node_seconds": float(node_seconds),
            "workflow_seconds": float(workflow_seconds),
            "invocation_count": int(invocation_count),
            "measured_fraction": fraction,
            "pure_bounded_io": pure_bounded_io,
            "network_access": network_access,
            "mutable_external_state": mutable_external_state,
            "python_reference_available": python_reference_available,
            "frequently_changing_experimental_code": (
                frequently_changing_experimental_code
            ),
        }
        return cls(**identity, profile_sha256=canonical_sha256(identity))


class NativeQualification(FrozenModel):
    schema_version: Literal["1"] = "1"
    node_name: str
    candidate_engine: EngineName
    qualified: bool
    selected_engine: EngineName | None
    python_fallback_preserved: bool
    scientific_outputs_equal: bool
    invocation_count: int = Field(ge=1)
    invocation_count_minimum: int = Field(ge=1)
    hot_path_fraction: float = Field(ge=0, le=1)
    hot_path_min_fraction: float = Field(ge=0, le=1)
    cold_kernel_speedup: float = Field(ge=0)
    warm_kernel_speedup: float = Field(ge=0)
    projected_end_to_end_gain: float
    projected_gain_minimum: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...]
    optimization_evidence: tuple[OptimizationStageEvidence, ...]
    engine_decision: Mapping[str, object] | None

    @model_validator(mode="after")
    def _validate_optimization_order(self) -> NativeQualification:
        stages = tuple(item.stage for item in self.optimization_evidence)
        if stages != _OPTIMIZATION_ORDER:
            raise ValueError("optimization evidence is not in mandatory order")
        if self.qualified and (
            self.selected_engine != self.candidate_engine
            or not self.python_fallback_preserved
            or not self.scientific_outputs_equal
        ):
            raise ValueError("qualified native path lacks mandatory evidence")
        return self


def _projected_gain(
    hot_path_fraction: float,
    cold_speedup: float,
    warm_speedup: float,
) -> float:
    conservative_speedup = min(cold_speedup, warm_speedup)
    if conservative_speedup <= 0:
        return 0.0
    return hot_path_fraction * (1.0 - 1.0 / conservative_speedup)


def qualify_native_candidate(
    profile: HotPathProfile,
    trials: tuple[EngineTrial, ...],
    *,
    candidate_engine: EngineName,
    optimization_evidence: tuple[OptimizationStageEvidence, ...],
    hot_path_min_fraction: float = 0.10,
    projected_gain_minimum: float = 0.05,
    invocation_count_minimum: int = 2,
) -> NativeQualification:
    """Qualify only a materially faster, equivalent measured hot path."""

    if not 0 <= hot_path_min_fraction <= 1:
        raise ValueError("hot_path_min_fraction must be between zero and one")
    if not 0 <= projected_gain_minimum <= 1:
        raise ValueError("projected_gain_minimum must be between zero and one")
    if invocation_count_minimum < 1:
        raise ValueError("invocation_count_minimum must be positive")
    if tuple(item.stage for item in optimization_evidence) != (
        _OPTIMIZATION_ORDER
    ):
        raise ValueError("optimization evidence is not in mandatory order")
    by_engine = {trial.engine: trial for trial in trials}
    if candidate_engine not in by_engine:
        raise ValueError(f"candidate engine was not trialled: {candidate_engine}")
    reference = by_engine.get("python_reference")
    candidate = by_engine[candidate_engine]
    reasons: list[str] = []
    if not profile.pure_bounded_io:
        reasons.append("HOT_PATH_NOT_PURE_BOUNDED_IO")
    if profile.network_access:
        reasons.append("HOT_PATH_USES_NETWORK")
    if profile.mutable_external_state:
        reasons.append("HOT_PATH_USES_MUTABLE_EXTERNAL_STATE")
    if profile.frequently_changing_experimental_code:
        reasons.append("HOT_PATH_CODE_NOT_STABLE")
    if profile.invocation_count < invocation_count_minimum:
        reasons.append("HOT_PATH_NOT_FREQUENT")
    if not profile.python_reference_available or reference is None:
        reasons.append("PYTHON_REFERENCE_MISSING")
    if profile.measured_fraction < hot_path_min_fraction:
        reasons.append("HOT_PATH_BELOW_MINIMUM_FRACTION")
    candidate_stage = _candidate_stage(candidate_engine)
    candidate_stage_index = _OPTIMIZATION_ORDER.index(candidate_stage)
    prior = optimization_evidence[:candidate_stage_index]
    if any(
        item.disposition not in {"rejected", "not_applicable"}
        for item in prior
    ):
        reasons.append("OPTIMIZATION_ORDER_INCOMPLETE")
    candidate_evidence = optimization_evidence[candidate_stage_index]
    if candidate_evidence.disposition not in {"measured", "selected"}:
        reasons.append("CANDIDATE_STAGE_NOT_MEASURED")
    try:
        decision = select_fastest_equivalent_engine(trials)
    except ValueError:
        decision = None
    if (
        reference is None
        or reference.cold is None
        or reference.warm is None
        or candidate.cold is None
        or candidate.warm is None
    ):
        cold_speedup = 0.0
        warm_speedup = 0.0
        reasons.append("TIMING_EVIDENCE_INCOMPLETE")
    else:
        if (
            candidate.cold.mean_seconds <= 0
            or candidate.warm.mean_seconds <= 0
        ):
            cold_speedup = 0.0
            warm_speedup = 0.0
            reasons.append("NONPOSITIVE_CANDIDATE_TIMING")
        else:
            cold_speedup = (
                reference.cold.mean_seconds / candidate.cold.mean_seconds
            )
            warm_speedup = (
                reference.warm.mean_seconds / candidate.warm.mean_seconds
            )
    projected_gain = _projected_gain(
        profile.measured_fraction,
        cold_speedup,
        warm_speedup,
    )
    if projected_gain < projected_gain_minimum:
        reasons.append("PROJECTED_END_TO_END_GAIN_BELOW_MINIMUM")
    if decision is None:
        reasons.append("ENGINE_DECISION_UNAVAILABLE")
    else:
        outcome = next(
            item
            for item in decision.outcomes
            if item.engine == candidate_engine
        )
        if outcome.status != "selected":
            reasons.extend(
                code
                for code in outcome.reason_codes
                if code not in reasons
            )
    scientific_equal = (
        candidate.scientific_output_sha256 is not None
        and reference is not None
        and candidate.scientific_output_sha256
        == reference.scientific_output_sha256
    )
    if not scientific_equal and "SCIENTIFIC_OUTPUT_MISMATCH" not in reasons:
        reasons.append("SCIENTIFIC_OUTPUT_MISMATCH")
    if (
        candidate_evidence.scientific_outputs_equal is not None
        and candidate_evidence.scientific_outputs_equal != scientific_equal
    ):
        reasons.append("OPTIMIZATION_EQUIVALENCE_EVIDENCE_MISMATCH")
    conservative_speedup = min(cold_speedup, warm_speedup)
    if (
        candidate_evidence.measured_speedup is not None
        and not math.isclose(
            candidate_evidence.measured_speedup,
            conservative_speedup,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        reasons.append("OPTIMIZATION_SPEED_EVIDENCE_MISMATCH")
    if any(
        item.disposition in {"measured", "selected"}
        for item in optimization_evidence[candidate_stage_index + 1 :]
    ):
        reasons.append("LATER_OPTIMIZATION_PREMATURELY_MEASURED")
    qualified = not reasons
    return NativeQualification(
        node_name=profile.node_name,
        candidate_engine=candidate_engine,
        qualified=qualified,
        selected_engine=(
            candidate_engine
            if qualified
            else ("python_reference" if reference is not None else None)
        ),
        python_fallback_preserved=reference is not None,
        scientific_outputs_equal=scientific_equal,
        invocation_count=profile.invocation_count,
        invocation_count_minimum=invocation_count_minimum,
        hot_path_fraction=profile.measured_fraction,
        hot_path_min_fraction=hot_path_min_fraction,
        cold_kernel_speedup=cold_speedup,
        warm_kernel_speedup=warm_speedup,
        projected_end_to_end_gain=projected_gain,
        projected_gain_minimum=projected_gain_minimum,
        reason_codes=tuple(dict.fromkeys(reasons)),
        optimization_evidence=optimization_evidence,
        engine_decision=(
            deep_thaw_json(decision) if decision is not None else None
        ),
    )


def _candidate_stage(engine: EngineName) -> OptimizationStage:
    if engine in {"numpy", "arrow", "duckdb", "processes", "threads"}:
        return "numpy_arrow_duckdb"
    if engine == "numba":
        return "numba"
    if engine == "rust":
        return "rust"
    raise ValueError("python_reference is not a native candidate")


def build_hot_path_profile(
    runtime_rows: Sequence[Mapping[str, object]],
    *,
    node_name: str,
    phase_names: Sequence[str],
    invocation_count: int,
    pure_bounded_io: bool,
    network_access: bool,
    mutable_external_state: bool,
    python_reference_available: bool,
    frequently_changing_experimental_code: bool = False,
) -> HotPathProfile:
    """Aggregate measured runner seconds into one auditable hot-path profile."""

    selected_phases = frozenset(str(value) for value in phase_names)
    if not selected_phases:
        raise ValueError("at least one measured phase is required")
    workflow_seconds = 0.0
    node_seconds = 0.0
    for row in runtime_rows:
        raw_seconds = row["duration_seconds"]
        if (
            isinstance(raw_seconds, bool)
            or not isinstance(raw_seconds, (int, float))
        ):
            raise ValueError("runtime duration must be numeric")
        seconds = float(raw_seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("runtime duration must be finite and nonnegative")
        workflow_seconds += seconds
        if str(row["phase"]) in selected_phases:
            node_seconds += seconds
    if workflow_seconds <= 0:
        raise ValueError("runtime profile contains no measured runner time")
    if node_seconds <= 0:
        raise ValueError("selected hot path has no measured runner time")
    return HotPathProfile.create(
        node_name=node_name,
        node_seconds=node_seconds,
        workflow_seconds=workflow_seconds,
        invocation_count=invocation_count,
        pure_bounded_io=pure_bounded_io,
        network_access=network_access,
        mutable_external_state=mutable_external_state,
        python_reference_available=python_reference_available,
        frequently_changing_experimental_code=(
            frequently_changing_experimental_code
        ),
    )


def _atomic_json(path: Path, payload: object) -> Path:
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


def write_native_qualification_artifacts(
    profile: HotPathProfile,
    qualification: NativeQualification,
    trials: tuple[EngineTrial, ...],
    output_dir: Path,
) -> tuple[Path, ...]:
    """Write the complete qualification and fallback audit surface."""

    root = Path(output_dir)
    engine_decision = (
        EngineDecision.model_validate(qualification.engine_decision)
        if qualification.engine_decision is not None
        else None
    )
    payloads = {
        "hot_path_profile.json": profile,
        "native_candidate_report.json": {
            "schema_version": "1",
            "node_name": qualification.node_name,
            "candidate_engine": qualification.candidate_engine,
            "hot_path_fraction": qualification.hot_path_fraction,
            "hot_path_min_fraction": qualification.hot_path_min_fraction,
            "projected_end_to_end_gain": (
                qualification.projected_end_to_end_gain
            ),
            "projected_gain_minimum": qualification.projected_gain_minimum,
            "invocation_count": qualification.invocation_count,
            "invocation_count_minimum": (
                qualification.invocation_count_minimum
            ),
            "qualified": qualification.qualified,
            "reason_codes": list(qualification.reason_codes),
            "optimization_evidence": qualification.optimization_evidence,
        },
        "native_equivalence_report.json": {
            "schema_version": "1",
            "scientific_outputs_equal": (
                qualification.scientific_outputs_equal
            ),
            "reference_engine": (
                engine_decision.reference_engine
                if engine_decision is not None
                else None
            ),
            "candidate_engine": qualification.candidate_engine,
        },
        "native_benchmark.json": {
            "schema_version": "1",
            "trials": [deep_thaw_json(trial) for trial in trials],
            "decision": (
                deep_thaw_json(engine_decision)
                if engine_decision is not None
                else None
            ),
            "qualification": deep_thaw_json(qualification),
        },
        "native_wheel_manifest.json": {
            "schema_version": "1",
            "wheel_built": False,
            "wheel_required": (
                qualification.qualified
                and qualification.candidate_engine == "rust"
            ),
            "reason": (
                "candidate_not_qualified"
                if not qualification.qualified
                else (
                    "qualified_rust_build_required"
                    if qualification.candidate_engine == "rust"
                    else "engine_candidate_does_not_require_rust_wheel"
                )
            ),
            "wheel_sha256": None,
        },
        "native_fallback_audit.json": {
            "schema_version": "1",
            "python_fallback_preserved": (
                qualification.python_fallback_preserved
            ),
            "selected_engine": qualification.selected_engine,
            "fallback_engine": "python_reference",
            "reason_codes": list(qualification.reason_codes),
        },
    }
    return tuple(
        _atomic_json(root / name, payload)
        for name, payload in payloads.items()
    )
