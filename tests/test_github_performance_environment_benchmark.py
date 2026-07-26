from __future__ import annotations

from aurora.infra.github_performance.environment_benchmark import (
    EnvironmentSetupSample,
    evaluate_environment_setup_samples,
)


def _sample(
    *,
    mode: str,
    temperature: str,
    repetition: int,
    seconds: float,
    environment_sha256: str = "a" * 64,
) -> EnvironmentSetupSample:
    return EnvironmentSetupSample(
        mode=mode,
        temperature=temperature,
        repetition=repetition,
        seconds=seconds,
        environment_sha256=environment_sha256,
        installed_packages_sha256="b" * 64,
    )


def test_environment_benchmark_accepts_equivalent_faster_wheelhouse() -> None:
    baseline = (
        _sample(
            mode="locked_network",
            temperature="cold",
            repetition=0,
            seconds=20.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=1,
            seconds=9.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=2,
            seconds=10.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=3,
            seconds=11.0,
        ),
    )
    optimized = (
        _sample(
            mode="wheelhouse",
            temperature="cold",
            repetition=0,
            seconds=8.0,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=1,
            seconds=4.0,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=2,
            seconds=5.0,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=3,
            seconds=6.0,
        ),
    )

    report = evaluate_environment_setup_samples(baseline, optimized)

    assert report.status == "success"
    assert report.dependency_environment_reproducible is True
    assert report.fast_path_selected is True
    assert report.baseline_cold_seconds == (20.0,)
    assert report.optimized_cold_seconds == (8.0,)
    assert report.baseline_warm_seconds == (9.0, 10.0, 11.0)
    assert report.optimized_warm_seconds == (4.0, 5.0, 6.0)
    assert report.cold_speedup == 2.5
    assert report.warm_speedup == 2.0
    assert report.failure_codes == ()


def test_environment_benchmark_rejects_environment_mismatch() -> None:
    baseline = (
        _sample(
            mode="locked_network",
            temperature="cold",
            repetition=0,
            seconds=20.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=1,
            seconds=10.0,
        ),
    )
    optimized = (
        _sample(
            mode="wheelhouse",
            temperature="cold",
            repetition=0,
            seconds=8.0,
            environment_sha256="c" * 64,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=1,
            seconds=5.0,
            environment_sha256="c" * 64,
        ),
    )

    report = evaluate_environment_setup_samples(baseline, optimized)

    assert report.status == "failed"
    assert report.dependency_environment_reproducible is False
    assert report.fast_path_selected is False
    assert "ENVIRONMENT_HASH_MISMATCH" in report.failure_codes


def test_environment_benchmark_rejects_slower_fast_path() -> None:
    baseline = (
        _sample(
            mode="locked_network",
            temperature="cold",
            repetition=0,
            seconds=10.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=1,
            seconds=5.0,
        ),
        _sample(
            mode="locked_network",
            temperature="warm",
            repetition=2,
            seconds=6.0,
        ),
    )
    optimized = (
        _sample(
            mode="wheelhouse",
            temperature="cold",
            repetition=0,
            seconds=12.0,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=1,
            seconds=7.0,
        ),
        _sample(
            mode="wheelhouse",
            temperature="warm",
            repetition=2,
            seconds=8.0,
        ),
    )

    report = evaluate_environment_setup_samples(baseline, optimized)

    assert report.status == "failed"
    assert report.dependency_environment_reproducible is True
    assert report.fast_path_selected is False
    assert "COLD_SETUP_SLOWER" in report.failure_codes
    assert "WARM_SETUP_SLOWER" in report.failure_codes
