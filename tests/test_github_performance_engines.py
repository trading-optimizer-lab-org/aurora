from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.engines import (
    EngineTrial,
    select_fastest_equivalent_engine,
    write_engine_trials,
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


def _unavailable(engine: str) -> EngineTrial:
    return EngineTrial(
        engine=engine,
        capability_available=False,
        capability_reason="optional dependency is not installed",
        scientific_output_sha256=None,
        cold=None,
        warm=None,
        end_to_end_includes_compilation=False,
        end_to_end_includes_warmup=False,
        failure_codes=("CAPABILITY_MISSING",),
    )


def test_selects_only_fastest_equivalent_engine_with_clear_uncertainty() -> None:
    trials = (
        _trial(
            "python_reference",
            cold=(10.0, 10.2, 9.8, 10.1, 10.0),
            warm=(8.0, 8.2, 7.9, 8.1, 8.0),
        ),
        _trial(
            "numpy",
            cold=(5.0, 5.2, 4.9, 5.1, 5.0),
            warm=(4.0, 4.2, 3.9, 4.1, 4.0),
        ),
        _trial(
            "numba",
            cold=(12.0, 12.2, 11.8, 12.1, 12.0),
            warm=(2.0, 2.2, 1.9, 2.1, 2.0),
        ),
        _trial(
            "arrow",
            cold=(6.0, 6.2, 5.9, 6.1, 6.0),
            warm=(9.0, 9.2, 8.9, 9.1, 9.0),
        ),
        _unavailable("duckdb"),
        _trial(
            "processes",
            cold=(4.0, 4.2, 3.9, 4.1, 4.0),
            warm=(3.0, 3.2, 2.9, 3.1, 3.0),
            output_hash="b" * 64,
        ),
        _trial(
            "threads",
            cold=(11.0, 11.2, 10.9, 11.1, 11.0),
            warm=(9.0, 9.2, 8.9, 9.1, 9.0),
        ),
    )

    decision = select_fastest_equivalent_engine(trials)
    outcomes = {item.engine: item for item in decision.outcomes}

    assert decision.selected_engine == "numpy"
    assert decision.reference_engine == "python_reference"
    assert decision.reference_fallback_preserved is True
    assert decision.scientific_outputs_equal is True
    assert decision.cold_speedup > 1.0
    assert decision.warm_speedup > 1.0
    assert outcomes["numpy"].status == "selected"
    assert outcomes["numba"].reason_codes == ("COLD_NOT_FASTER",)
    assert outcomes["arrow"].reason_codes == ("WARM_NOT_FASTER",)
    assert outcomes["duckdb"].status == "capability_missing"
    assert outcomes["processes"].reason_codes == (
        "SCIENTIFIC_OUTPUT_MISMATCH",
    )
    assert outcomes["threads"].reason_codes == (
        "COLD_NOT_FASTER",
        "WARM_NOT_FASTER",
    )


def test_uncertainty_overlap_preserves_reference_fallback() -> None:
    trials = (
        _trial(
            "python_reference",
            cold=(10.0, 10.4, 9.6, 10.2, 9.8),
            warm=(8.0, 8.4, 7.6, 8.2, 7.8),
        ),
        _trial(
            "numpy",
            cold=(9.7, 10.1, 9.3, 9.9, 9.5),
            warm=(7.7, 8.1, 7.3, 7.9, 7.5),
        ),
    )

    decision = select_fastest_equivalent_engine(trials)

    assert decision.selected_engine == "python_reference"
    assert decision.cold_speedup == 1.0
    assert decision.warm_speedup == 1.0
    assert decision.outcomes[1].reason_codes == (
        "COLD_UNCERTAINTY_OVERLAP",
        "WARM_UNCERTAINTY_OVERLAP",
    )


def test_engine_trial_requires_real_end_to_end_timing_evidence() -> None:
    with pytest.raises(ValueError, match="compilation"):
        EngineTrial(
            engine="numba",
            capability_available=True,
            capability_reason=None,
            scientific_output_sha256=OUTPUT_HASH,
            cold=build_timing_distribution(
                condition="cold",
                samples_seconds=(2.0, 2.1),
            ),
            warm=build_timing_distribution(
                condition="warm",
                samples_seconds=(1.0, 1.1),
            ),
            end_to_end_includes_compilation=False,
            end_to_end_includes_warmup=True,
            failure_codes=(),
        )


def test_slower_or_non_equivalent_trial_never_replaces_reference() -> None:
    reference = _trial(
        "python_reference",
        cold=(5.0, 5.1, 4.9),
        warm=(4.0, 4.1, 3.9),
    )
    slower = _trial(
        "numpy",
        cold=(7.0, 7.1, 6.9),
        warm=(6.0, 6.1, 5.9),
    )
    mismatch = _trial(
        "arrow",
        cold=(1.0, 1.1, 0.9),
        warm=(1.0, 1.1, 0.9),
        output_hash="c" * 64,
    )

    decision = select_fastest_equivalent_engine(
        (reference, slower, mismatch)
    )

    assert decision.selected_engine == "python_reference"
    assert decision.reference_fallback_preserved is True
    assert decision.scientific_outputs_equal is True


def test_engine_trials_artifact_contains_all_capability_outcomes(
    tmp_path: Path,
) -> None:
    trials = (
        _trial(
            "python_reference",
            cold=(5.0, 5.1),
            warm=(4.0, 4.1),
        ),
        _unavailable("duckdb"),
    )
    path = write_engine_trials(
        trials,
        tmp_path / "engine_trials.json",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "engine_trials.json"
    assert [item["engine"] for item in payload["trials"]] == [
        "python_reference",
        "duckdb",
    ]
    assert payload["trials"][1]["failure_codes"] == [
        "CAPABILITY_MISSING"
    ]


def test_reference_engine_is_mandatory() -> None:
    with pytest.raises(ValueError, match="python_reference"):
        select_fastest_equivalent_engine(
            (
                _trial(
                    "numpy",
                    cold=(1.0, 1.1),
                    warm=(1.0, 1.1),
                ),
            )
        )
