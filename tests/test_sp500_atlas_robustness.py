from __future__ import annotations

from aurora.infra.sp500_megarun.catalog_atlas_robustness import classify_atlas_robustness


def _base() -> dict[str, object]:
    return {
        "train_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "positive_week_fraction": 0.80,
        "positive_month_fraction": 0.75,
        "joint_positive_above_spy_fraction": 0.60,
    }


def test_one_red_test_is_amber() -> None:
    result = classify_atlas_robustness(
        _base(),
        [{**_base(), "name": "delay_one", "positive_week_fraction": 0.70}],
    )
    assert result.status == "amber"


def test_two_red_tests_are_red() -> None:
    result = classify_atlas_robustness(
        _base(),
        [
            {**_base(), "name": "delay_one", "positive_week_fraction": 0.70},
            {**_base(), "name": "leave_year", "positive_month_fraction": 0.64},
        ],
    )
    assert result.status == "red"


def test_protected_boundary_is_invalid() -> None:
    result = classify_atlas_robustness(
        _base(),
        [{**_base(), "name": "bad", "locked_opened": True}],
    )
    assert result.status == "invalid"
    assert result.zero_tolerance_failures
