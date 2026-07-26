from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aurora.infra.github_performance.execution_planner import (
    PilotRequired,
    resolve_planning_pilot,
)
from aurora.infra.github_performance.profiles import (
    PerformanceProfile,
    PerformanceProfileKey,
    ProfileConflict,
    assess_profile_reuse,
    build_performance_profile,
    build_timing_distribution,
    load_performance_profile,
    performance_profile_key,
    write_performance_profile,
)
from github_performance_helpers import contract, pilot


def _key() -> PerformanceProfileKey:
    return PerformanceProfileKey(
        code_sha="a" * 40,
        workflow_sha256="b" * 64,
        spec_sha256="c" * 64,
        snapshot_sha256="d" * 64,
        dependency_lock_sha256="e" * 64,
        runner_contract_sha256="f" * 64,
    )


def _profile() -> PerformanceProfile:
    return PerformanceProfile.create(
        key=_key(),
        cold=build_timing_distribution(
            condition="cold",
            samples_seconds=(10.0, 10.4, 9.8, 10.2, 10.1),
        ),
        warm=build_timing_distribution(
            condition="warm",
            samples_seconds=(7.0, 7.3, 6.9, 7.1, 7.2),
        ),
        pilot_result=pilot(),
        source_run_id="123456",
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("code_sha", "1" * 40),
        ("workflow_sha256", "1" * 64),
        ("spec_sha256", "2" * 64),
        ("snapshot_sha256", "3" * 64),
        ("dependency_lock_sha256", "4" * 64),
        ("runner_contract_sha256", "5" * 64),
    ),
)
def test_profile_reuse_requires_every_key_field_to_match(
    field: str,
    replacement: str,
) -> None:
    profile = _profile()
    exact = assess_profile_reuse(profile, _key())
    mismatched_key = _key().model_copy(update={field: replacement})
    mismatched = assess_profile_reuse(profile, mismatched_key)

    assert exact.reuse_allowed is True
    assert exact.pilot_required is False
    assert exact.reason_codes == ()
    assert mismatched.reuse_allowed is False
    assert mismatched.pilot_required is True
    assert mismatched.reason_codes == ("PROFILE_KEY_MISMATCH",)


def test_profile_keeps_cold_warm_samples_and_uncertainty_separate() -> None:
    profile = _profile()

    assert profile.cold.condition == "cold"
    assert profile.warm.condition == "warm"
    assert profile.cold.sample_count == 5
    assert profile.warm.sample_count == 5
    assert profile.cold.samples_seconds != profile.warm.samples_seconds
    assert profile.cold.standard_error_seconds > 0
    assert (
        profile.cold.confidence_low_seconds
        < profile.cold.mean_seconds
        < profile.cold.confidence_high_seconds
    )
    assert (
        profile.cold.prediction_low_seconds
        < profile.cold.mean_seconds
        < profile.cold.prediction_high_seconds
    )


def test_profile_expires_outside_observed_confidence_band() -> None:
    profile = _profile()
    inside = assess_profile_reuse(
        profile,
        _key(),
        observed_seconds={
            "cold": profile.cold.mean_seconds,
            "warm": profile.warm.mean_seconds,
        },
    )
    outside = assess_profile_reuse(
        profile,
        _key(),
        observed_seconds={
            "cold": profile.cold.prediction_high_seconds + 0.01,
            "warm": profile.warm.mean_seconds,
        },
    )

    assert inside.reuse_allowed is True
    assert outside.reuse_allowed is False
    assert outside.pilot_required is True
    assert outside.reason_codes == (
        "PROFILE_OBSERVATION_OUTSIDE_CONFIDENCE_BAND",
    )


def test_profile_artifact_is_immutable_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "performance_profile.json"
    profile = _profile()

    first = write_performance_profile(profile, path)
    second = write_performance_profile(profile, path)

    assert first == path
    assert second == path
    assert load_performance_profile(path) == profile
    different = PerformanceProfile.create(
        key=_key(),
        cold=profile.cold,
        warm=profile.warm,
        pilot_result=profile.pilot_result.model_copy(
            update={"setup_seconds": 999.0}
        ),
        source_run_id="different",
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    with pytest.raises(ProfileConflict):
        write_performance_profile(different, path)


def test_planner_requires_fresh_pilot_for_stale_or_missing_profile() -> None:
    profile = _profile()
    historic = resolve_planning_pilot(
        profile=profile,
        requested_key=_key(),
        fresh_pilot=None,
    )
    mismatched = _key().model_copy(update={"code_sha": "1" * 40})

    assert historic.source == "historical_profile"
    assert historic.pilot_result == profile.pilot_result
    with pytest.raises(PilotRequired):
        resolve_planning_pilot(
            profile=profile,
            requested_key=mismatched,
            fresh_pilot=None,
        )

    current = pilot().model_copy(update={"setup_seconds": 77.0})
    fresh = resolve_planning_pilot(
        profile=profile,
        requested_key=mismatched,
        fresh_pilot=current,
    )
    assert fresh.source == "fresh_pilot"
    assert fresh.pilot_result == current
    assert fresh.profile_reused is False


def test_profile_contract_cannot_contain_candidate_quality() -> None:
    forbidden = {
        "candidate_id",
        "score",
        "sharpe",
        "sortino",
        "profit_factor",
        "validation_result",
    }

    assert forbidden.isdisjoint(PerformanceProfile.model_fields)
    assert forbidden.isdisjoint(PerformanceProfileKey.model_fields)


def test_profile_rejects_single_sample_uncertainty() -> None:
    with pytest.raises(ValueError, match="at least two"):
        build_timing_distribution(
            condition="cold",
            samples_seconds=(1.0,),
        )


def test_profile_rejects_nonfinite_sample() -> None:
    with pytest.raises(ValueError, match="finite"):
        build_timing_distribution(
            condition="warm",
            samples_seconds=(1.0, float("nan")),
        )


def test_profile_key_is_derived_from_every_frozen_runtime_identity() -> None:
    original = contract()
    key = performance_profile_key(original)

    assert key.code_sha == original.code_sha
    assert key.workflow_sha256 == original.workflow_sha256
    assert key.spec_sha256 == original.resolved_spec_sha256
    assert key.snapshot_sha256 == original.snapshot_hash
    assert (
        key.dependency_lock_sha256
        == original.dependency_lock_sha256
    )
    changed = original.model_copy(
        update={"environment_sha256": "9" * 64}
    )
    assert (
        performance_profile_key(changed).runner_contract_sha256
        != key.runner_contract_sha256
    )


def test_profile_builder_requires_repeated_cold_and_warm_evidence() -> None:
    report = {
        "dependency_environment_reproducible": True,
        "fast_path_selected": True,
        "failure_codes": [],
        "optimized_cold_seconds": [10.0, 10.5, 9.8],
        "optimized_warm_seconds": [7.0, 7.2, 6.9],
    }
    profile = build_performance_profile(
        contract=contract(),
        pilot_result=pilot(),
        environment_setup_benchmark=report,
        source_run_id="123",
        created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert profile.key == performance_profile_key(contract())
    assert profile.cold.sample_count == 3
    assert profile.warm.sample_count == 3
    assert profile.source_run_id == "123"
    with pytest.raises(ValueError, match="at least two"):
        build_performance_profile(
            contract=contract(),
            pilot_result=pilot(),
            environment_setup_benchmark={
                **report,
                "optimized_cold_seconds": [10.0],
            },
            source_run_id="123",
            created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        )
