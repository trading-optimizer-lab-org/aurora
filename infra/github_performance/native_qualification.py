"""Profile-gated native acceleration with a mandatory Python fallback."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.engines import (
    EngineDecision,
    EngineTrial,
    select_fastest_equivalent_engine,
)


class HotPathProfile(FrozenModel):
    schema_version: Literal["1"] = "1"
    node_name: str
    node_seconds: float = Field(gt=0)
    workflow_seconds: float = Field(gt=0)
    measured_fraction: float = Field(ge=0, le=1)
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
            "measured_fraction": self.measured_fraction,
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
    ) -> HotPathProfile:
        fraction = float(node_seconds) / float(workflow_seconds)
        identity = {
            "schema_version": "1",
            "node_name": node_name,
            "node_seconds": float(node_seconds),
            "workflow_seconds": float(workflow_seconds),
            "measured_fraction": fraction,
        }
        return cls(**identity, profile_sha256=canonical_sha256(identity))


class NativeQualification(FrozenModel):
    schema_version: Literal["1"] = "1"
    node_name: str
    candidate_engine: str
    qualified: bool
    selected_engine: str
    python_fallback_preserved: bool
    scientific_outputs_equal: bool
    hot_path_fraction: float = Field(ge=0, le=1)
    hot_path_min_fraction: float = Field(ge=0, le=1)
    cold_kernel_speedup: float = Field(ge=0)
    warm_kernel_speedup: float = Field(ge=0)
    projected_end_to_end_gain: float
    projected_gain_minimum: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...]
    engine_decision: Mapping[str, object]


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
    candidate_engine: str,
    hot_path_min_fraction: float = 0.10,
    projected_gain_minimum: float = 0.05,
) -> NativeQualification:
    """Qualify only a materially faster, equivalent measured hot path."""

    if not 0 <= hot_path_min_fraction <= 1:
        raise ValueError("hot_path_min_fraction must be between zero and one")
    if not 0 <= projected_gain_minimum <= 1:
        raise ValueError("projected_gain_minimum must be between zero and one")
    decision = select_fastest_equivalent_engine(trials)
    by_engine = {trial.engine: trial for trial in trials}
    if candidate_engine not in by_engine:
        raise ValueError(f"candidate engine was not trialled: {candidate_engine}")
    reference = by_engine.get("python_reference")
    candidate = by_engine[candidate_engine]
    reasons: list[str] = []
    if profile.measured_fraction < hot_path_min_fraction:
        reasons.append("HOT_PATH_BELOW_MINIMUM_FRACTION")
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
    qualified = not reasons
    return NativeQualification(
        node_name=profile.node_name,
        candidate_engine=candidate_engine,
        qualified=qualified,
        selected_engine=(
            candidate_engine if qualified else "python_reference"
        ),
        python_fallback_preserved=True,
        scientific_outputs_equal=scientific_equal,
        hot_path_fraction=profile.measured_fraction,
        hot_path_min_fraction=hot_path_min_fraction,
        cold_kernel_speedup=cold_speedup,
        warm_kernel_speedup=warm_speedup,
        projected_end_to_end_gain=projected_gain,
        projected_gain_minimum=projected_gain_minimum,
        reason_codes=tuple(dict.fromkeys(reasons)),
        engine_decision=deep_thaw_json(decision),
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
    qualification: NativeQualification,
    trials: tuple[EngineTrial, ...],
    output_dir: Path,
) -> tuple[Path, ...]:
    """Write the complete qualification and fallback audit surface."""

    root = Path(output_dir)
    engine_decision = EngineDecision.model_validate(
        qualification.engine_decision
    )
    payloads = {
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
            "qualified": qualification.qualified,
            "reason_codes": list(qualification.reason_codes),
        },
        "native_equivalence_report.json": {
            "schema_version": "1",
            "scientific_outputs_equal": (
                qualification.scientific_outputs_equal
            ),
            "reference_engine": engine_decision.reference_engine,
            "candidate_engine": qualification.candidate_engine,
        },
        "native_benchmark.json": {
            "schema_version": "1",
            "trials": [deep_thaw_json(trial) for trial in trials],
            "decision": deep_thaw_json(engine_decision),
            "qualification": deep_thaw_json(qualification),
        },
        "native_wheel_manifest.json": {
            "schema_version": "1",
            "wheel_built": False,
            "reason": (
                "candidate_not_qualified"
                if not qualification.qualified
                else "engine_candidate_does_not_require_rust_wheel"
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
