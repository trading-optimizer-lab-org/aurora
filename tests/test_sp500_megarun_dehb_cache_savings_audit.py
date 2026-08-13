from __future__ import annotations


def _record(island: str, lane: str, config: int, result: str) -> dict:
    return {
        "island_id": island,
        "lane_id": lane,
        "configuration": {"choice": config},
        "fidelity": 27,
        "scientific_result": {"strategy_fingerprint": result},
        "validation_opened": False,
        "locked_opened": False,
    }


def test_historical_audit_models_local_first_wave_and_prior_wave_cache() -> None:
    from aurora.infra.sp500_megarun.dehb_cache_savings_audit import (
        audit_historical_records,
    )

    wave_zero = [
        _record("F001-R1", "F001", 1, "same"),
        _record("F001-R1", "F001", 1, "same"),
        _record("F001-R2", "F001", 1, "same"),
    ]
    wave_one = [
        _record("F001-R1", "F001", 1, "same"),
        _record("F001-R2", "F001", 1, "same"),
        _record("F001-R1", "F001", 2, "new"),
        _record("F001-R1", "F001", 2, "new"),
    ]

    report = audit_historical_records([wave_zero, wave_one])

    assert report["waves"][0]["estimated_physical_evaluations"] == 2
    assert report["waves"][1]["estimated_physical_evaluations"] == 1
    assert report["estimated_physical_evaluations"] == 3
    assert report["scientific_result_conflicts"] == 0
    assert report["legacy_cache_import_allowed"] is False


def test_historical_audit_detects_same_key_with_different_science() -> None:
    from aurora.infra.sp500_megarun.dehb_cache_savings_audit import (
        audit_historical_records,
    )

    report = audit_historical_records(
        [
            [
                _record("F067-R1", "F067", 1, "first"),
                _record("F067-R2", "F067", 1, "different"),
            ]
        ]
    )

    assert report["scientific_result_conflicts"] == 1
    assert report["acceptance_65_percent"] is False
