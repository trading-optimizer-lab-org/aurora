from __future__ import annotations

import json
from pathlib import Path

from aurora.infra.github_performance.engines import EngineTrial
from aurora.infra.github_performance.native_qualification import (
    HotPathProfile,
    qualify_native_candidate,
    write_native_qualification_artifacts,
)
from aurora.infra.github_performance.profiles import (
    build_timing_distribution,
)


OUTPUT_HASH = "a" * 64


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
        HotPathProfile.create(
            node_name="signal_kernel",
            node_seconds=9.0,
            workflow_seconds=100.0,
        ),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
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
        HotPathProfile.create(
            node_name="small_gain_kernel",
            node_seconds=20.0,
            workflow_seconds=100.0,
        ),
        (_reference(), candidate),
        candidate_engine="numpy",
    )

    assert qualification.qualified is False
    assert qualification.projected_end_to_end_gain < 0.05
    assert (
        "PROJECTED_END_TO_END_GAIN_BELOW_MINIMUM"
        in qualification.reason_codes
    )


def test_non_equivalent_candidate_never_replaces_python() -> None:
    qualification = qualify_native_candidate(
        HotPathProfile.create(
            node_name="wrong_kernel",
            node_seconds=40.0,
            workflow_seconds=100.0,
        ),
        (_reference(), _fast_candidate("b" * 64)),
        candidate_engine="numpy",
    )

    assert qualification.qualified is False
    assert qualification.scientific_outputs_equal is False
    assert qualification.selected_engine == "python_reference"
    assert "SCIENTIFIC_OUTPUT_MISMATCH" in qualification.reason_codes


def test_material_equivalent_candidate_is_qualified() -> None:
    qualification = qualify_native_candidate(
        HotPathProfile.create(
            node_name="bootstrap_kernel",
            node_seconds=40.0,
            workflow_seconds=100.0,
        ),
        (_reference(), _fast_candidate()),
        candidate_engine="numpy",
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
    qualification = qualify_native_candidate(
        HotPathProfile.create(
            node_name="rejected_kernel",
            node_seconds=40.0,
            workflow_seconds=100.0,
        ),
        trials,
        candidate_engine="numpy",
    )
    paths = write_native_qualification_artifacts(
        qualification,
        trials,
        tmp_path,
    )

    assert {path.name for path in paths} == {
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
    qualification = qualify_native_candidate(
        HotPathProfile.create(
            node_name="unmeasured_kernel",
            node_seconds=40.0,
            workflow_seconds=100.0,
        ),
        trials,
        candidate_engine="numpy",
    )

    assert qualification.qualified is False
    assert qualification.projected_end_to_end_gain == 0.0
    assert "TIMING_EVIDENCE_INCOMPLETE" in qualification.reason_codes
    write_native_qualification_artifacts(qualification, trials, tmp_path)
    json.loads((tmp_path / "native_benchmark.json").read_text())
