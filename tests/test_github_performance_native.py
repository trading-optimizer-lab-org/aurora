from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aurora.infra.github_performance.engines import EngineTrial
from aurora.infra.github_performance.native import (
    NATIVE_QUALIFICATION_OUTPUTS,
    HotPathQualificationContract,
    HotPathProfile,
    OptimizationStageEvidence,
    build_hot_path_profile,
    ensure_runtime_native_fallback_artifacts,
    qualify_native_candidate,
    validate_native_qualification_artifacts,
    write_native_qualification_artifacts,
)
from aurora.infra.github_performance.profiles import (
    build_timing_distribution,
)


OUTPUT_HASH = "a" * 64


def _profile(
    *,
    node_seconds: float = 40.0,
    workflow_seconds: float = 100.0,
    invocation_count: int = 100,
    pure_bounded_io: bool = True,
    network_access: bool = False,
    mutable_external_state: bool = False,
    python_reference_available: bool = True,
    frequently_changing_experimental_code: bool = False,
) -> HotPathProfile:
    return HotPathProfile.create(
        node_name="measured_kernel",
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


def _numpy_evidence(
    *,
    speedup: float = 2.5,
    equivalent: bool = True,
) -> tuple[OptimizationStageEvidence, ...]:
    return (
        OptimizationStageEvidence(
            stage="algorithm",
            disposition="rejected",
            reason_codes=("NO_BETTER_EQUIVALENT_ALGORITHM",),
        ),
        OptimizationStageEvidence(
            stage="shared_computation",
            disposition="rejected",
            reason_codes=("NO_ADDITIONAL_EXACT_REUSE",),
        ),
        OptimizationStageEvidence(
            stage="vectorization",
            disposition="rejected",
            reason_codes=("REFERENCE_ALREADY_VECTORIZED",),
        ),
        OptimizationStageEvidence(
            stage="numpy_arrow_duckdb",
            disposition="measured",
            reason_codes=(),
            measured_speedup=speedup,
            scientific_outputs_equal=equivalent,
        ),
        OptimizationStageEvidence(
            stage="numba",
            disposition="not_reached",
            reason_codes=(),
        ),
        OptimizationStageEvidence(
            stage="rust",
            disposition="not_reached",
            reason_codes=(),
        ),
    )


def _trial(
    engine: str,
    *,
    cold: tuple[float, ...],
    warm: tuple[float, ...],
    output_hash: str = OUTPUT_HASH,
) -> EngineTrial:
    return EngineTrial(
        engine=engine,
        capability_available=True,
        capability_reason=None,
        scientific_output_sha256=output_hash,
        cold=build_timing_distribution(
            condition="cold",
            samples_seconds=cold,
        ),
        warm=build_timing_distribution(
            condition="warm",
            samples_seconds=warm,
        ),
        end_to_end_includes_compilation=True,
        end_to_end_includes_warmup=True,
        failure_codes=(),
    )


def _reference() -> EngineTrial:
    return _trial(
        "python_reference",
        cold=(10.0, 10.2, 9.8, 10.1, 9.9),
        warm=(8.0, 8.2, 7.8, 8.1, 7.9),
    )


def _fast_candidate(output_hash: str = OUTPUT_HASH) -> EngineTrial:
    return _trial(
        "numpy",
        cold=(4.0, 4.2, 3.8, 4.1, 3.9),
        warm=(3.0, 3.2, 2.8, 3.1, 2.9),
        output_hash=output_hash,
    )


def test_native_candidate_requires_material_hot_path_share() -> None:
    qualification = qualify_native_candidate(
        _profile(
            node_seconds=9.0,
            workflow_seconds=100.0,
        ),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(),
    )

    assert qualification.qualified is False
    assert qualification.selected_engine == "python_reference"
    assert qualification.python_fallback_preserved is True
    assert "HOT_PATH_BELOW_MINIMUM_FRACTION" in qualification.reason_codes


def test_native_candidate_requires_five_percent_whole_workflow_gain() -> None:
    candidate = _trial(
        "numpy",
        cold=(8.0, 8.2, 7.8, 8.1, 7.9),
        warm=(6.4, 6.6, 6.2, 6.5, 6.3),
    )
    qualification = qualify_native_candidate(
        _profile(
            node_seconds=20.0,
            workflow_seconds=100.0,
        ),
        (_reference(), candidate),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(speedup=1.25),
    )

    assert qualification.qualified is False
    assert qualification.projected_end_to_end_gain < 0.05
    assert (
        "PROJECTED_END_TO_END_GAIN_BELOW_MINIMUM"
        in qualification.reason_codes
    )


def test_non_equivalent_candidate_never_replaces_python() -> None:
    qualification = qualify_native_candidate(
        _profile(),
        (_reference(), _fast_candidate("b" * 64)),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(equivalent=False),
    )

    assert qualification.qualified is False
    assert qualification.scientific_outputs_equal is False
    assert qualification.selected_engine == "python_reference"
    assert "SCIENTIFIC_OUTPUT_MISMATCH" in qualification.reason_codes


def test_material_equivalent_candidate_is_qualified() -> None:
    qualification = qualify_native_candidate(
        _profile(),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(),
    )

    assert qualification.qualified is True
    assert qualification.selected_engine == "numpy"
    assert qualification.scientific_outputs_equal is True
    assert qualification.projected_end_to_end_gain > 0.05
    assert qualification.reason_codes == ()


def test_qualification_writes_complete_fallback_artifacts(
    tmp_path: Path,
) -> None:
    trials = (_reference(), _fast_candidate("b" * 64))
    profile = _profile()
    qualification = qualify_native_candidate(
        profile,
        trials,
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(equivalent=False),
    )
    paths = write_native_qualification_artifacts(
        profile,
        qualification,
        trials,
        tmp_path,
    )

    assert {path.name for path in paths} == {
        "hot_path_profile.json",
        "native_candidate_report.json",
        "native_equivalence_report.json",
        "native_benchmark.json",
        "native_wheel_manifest.json",
        "native_fallback_audit.json",
    }
    fallback = json.loads(
        (tmp_path / "native_fallback_audit.json").read_text()
    )
    assert fallback["python_fallback_preserved"] is True
    assert fallback["selected_engine"] == "python_reference"
    assert (
        json.loads(
            (tmp_path / "native_wheel_manifest.json").read_text()
        )["wheel_built"]
        is False
    )


def test_incomplete_timing_evidence_stays_json_serializable(
    tmp_path: Path,
) -> None:
    candidate = EngineTrial(
        engine="numpy",
        capability_available=False,
        capability_reason="optional runtime unavailable",
        scientific_output_sha256=None,
        cold=None,
        warm=None,
        end_to_end_includes_compilation=True,
        end_to_end_includes_warmup=True,
        failure_codes=("CAPABILITY_MISSING",),
    )
    trials = (_reference(), candidate)
    profile = _profile()
    qualification = qualify_native_candidate(
        profile,
        trials,
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(speedup=0.0, equivalent=False),
    )

    assert qualification.qualified is False
    assert qualification.projected_end_to_end_gain == 0.0
    assert "TIMING_EVIDENCE_INCOMPLETE" in qualification.reason_codes
    write_native_qualification_artifacts(
        profile,
        qualification,
        trials,
        tmp_path,
    )
    json.loads((tmp_path / "native_benchmark.json").read_text())


def test_impure_or_external_hot_path_is_rejected() -> None:
    qualification = qualify_native_candidate(
        _profile(
            pure_bounded_io=False,
            network_access=True,
            mutable_external_state=True,
            frequently_changing_experimental_code=True,
        ),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(),
    )

    assert qualification.qualified is False
    assert {
        "HOT_PATH_NOT_PURE_BOUNDED_IO",
        "HOT_PATH_USES_NETWORK",
        "HOT_PATH_USES_MUTABLE_EXTERNAL_STATE",
        "HOT_PATH_CODE_NOT_STABLE",
    } <= set(qualification.reason_codes)


def test_missing_python_reference_is_blocked_without_crashing() -> None:
    qualification = qualify_native_candidate(
        _profile(python_reference_available=False),
        (_fast_candidate(),),
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(),
    )

    assert qualification.qualified is False
    assert qualification.selected_engine is None
    assert qualification.python_fallback_preserved is False
    assert "PYTHON_REFERENCE_MISSING" in qualification.reason_codes


def test_optimization_order_must_precede_native_measurement() -> None:
    evidence = list(_numpy_evidence())
    evidence[0] = OptimizationStageEvidence(
        stage="algorithm",
        disposition="not_reached",
        reason_codes=(),
    )
    qualification = qualify_native_candidate(
        _profile(),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
        optimization_evidence=tuple(evidence),
    )

    assert qualification.qualified is False
    assert "OPTIMIZATION_ORDER_INCOMPLETE" in qualification.reason_codes


def test_runtime_rows_build_exact_hot_path_share() -> None:
    profile = build_hot_path_profile(
        (
            {"phase": "compute_kernel", "duration_seconds": 30.0},
            {"phase": "compute_kernel", "duration_seconds": 10.0},
            {"phase": "setup", "duration_seconds": 60.0},
        ),
        node_name="compute_kernel",
        phase_names=("compute_kernel",),
        invocation_count=20,
        pure_bounded_io=True,
        network_access=False,
        mutable_external_state=False,
        python_reference_available=True,
    )

    assert profile.node_seconds == 40.0
    assert profile.workflow_seconds == 100.0
    assert profile.measured_fraction == 0.4


def test_hot_path_qualification_contract_rejects_string_booleans() -> None:
    with pytest.raises(ValidationError):
        HotPathQualificationContract.model_validate(
            {
                "pure_bounded_io": "false",
                "network_access": False,
                "mutable_external_state": False,
                "python_reference_available": True,
            }
        )


def test_runtime_fallback_publishes_complete_honest_native_surface(
    tmp_path: Path,
) -> None:
    paths = ensure_runtime_native_fallback_artifacts(
        (
            {"phase": "execute_shard", "duration_seconds": 20.0},
            {"phase": "execute_shard", "duration_seconds": 10.0},
            {"phase": "restore_runtime", "duration_seconds": 70.0},
        ),
        tmp_path,
    )

    assert {path.name for path in paths} == set(
        NATIVE_QUALIFICATION_OUTPUTS
    )
    profile = json.loads(
        (tmp_path / "hot_path_profile.json").read_text()
    )
    candidate = json.loads(
        (tmp_path / "native_candidate_report.json").read_text()
    )
    fallback = json.loads(
        (tmp_path / "native_fallback_audit.json").read_text()
    )
    assert profile["measured_fraction"] == 0.3
    assert candidate["qualified"] is False
    assert candidate["candidate_engine"] is None
    assert "NO_EQUIVALENT_ENGINE_TRIAL_SUPPLIED" in candidate[
        "reason_codes"
    ]
    assert fallback["selected_engine"] == "python_reference"
    assert fallback["python_fallback_preserved"] is True


def test_runtime_fallback_never_overwrites_measured_qualification(
    tmp_path: Path,
) -> None:
    trials = (_reference(), _fast_candidate())
    profile = _profile()
    qualification = qualify_native_candidate(
        profile,
        trials,
        candidate_engine="numpy",
        optimization_evidence=_numpy_evidence(),
    )
    expected = write_native_qualification_artifacts(
        profile,
        qualification,
        trials,
        tmp_path,
    )

    actual = ensure_runtime_native_fallback_artifacts(
        ({"phase": "execute_shard", "duration_seconds": 10.0},),
        tmp_path,
    )

    assert actual == expected
    fallback = json.loads(
        (tmp_path / "native_fallback_audit.json").read_text()
    )
    assert fallback["selected_engine"] == "numpy"


def test_runtime_fallback_rejects_partial_native_artifact_set(
    tmp_path: Path,
) -> None:
    (tmp_path / "hot_path_profile.json").write_text("{}")

    with pytest.raises(ValueError, match="artifact set is incomplete"):
        ensure_runtime_native_fallback_artifacts(
            ({"phase": "execute_shard", "duration_seconds": 10.0},),
            tmp_path,
        )


def test_native_artifact_validation_accepts_runtime_fallback(
    tmp_path: Path,
) -> None:
    ensure_runtime_native_fallback_artifacts(
        ({"phase": "execute_shard", "duration_seconds": 10.0},),
        tmp_path,
    )

    assert validate_native_qualification_artifacts(tmp_path) == ()


def test_native_artifact_validation_rejects_inconsistent_selection(
    tmp_path: Path,
) -> None:
    ensure_runtime_native_fallback_artifacts(
        ({"phase": "execute_shard", "duration_seconds": 10.0},),
        tmp_path,
    )
    fallback_path = tmp_path / "native_fallback_audit.json"
    fallback = json.loads(fallback_path.read_text())
    fallback["selected_engine"] = "numpy"
    fallback_path.write_text(json.dumps(fallback))

    failures = validate_native_qualification_artifacts(tmp_path)

    assert "NATIVE_REJECTED_CANDIDATE_SELECTED" in failures
    assert "NATIVE_SELECTED_ENGINE_MISMATCH" in failures
