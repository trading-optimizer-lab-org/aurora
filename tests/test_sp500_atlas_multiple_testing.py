from __future__ import annotations

from scripts.report_sp500_atlas_multiple_testing import build_multiple_testing_report


def test_multiple_testing_report_is_explicitly_train_only() -> None:
    rows = [
        {
            "strategy_id": "b",
            "strategy_kind": "single",
            "composition": {"kind": "identity", "direction": 1},
            "positive_weeks": 10,
            "positive_months": 5,
            "joint_positive_above_spy_years": 3,
            "annual_rows": [{"year": 2000, "strategy_return": 0.1}],
        },
        {
            "strategy_id": "a",
            "strategy_kind": "cross",
            "composition": {"kind": "and", "direction": -1},
            "positive_weeks": 9,
            "positive_months": 4,
            "joint_positive_above_spy_years": 2,
            "annual_rows": [{"year": 2000, "strategy_return": 0.2}],
        },
    ]
    report = build_multiple_testing_report(
        rows,
        raw_universe=100,
        canonical_universe=80,
        campaign_recipe_count=2,
        pareto_count=1,
        reserve_count=1,
        robust_count=1,
        adaptive_generations=0,
    )

    assert report["campaign_recipe_count"] == 2
    assert report["canonical_coverage_fraction"] == 0.025
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["status"] == "diagnostic_not_validation"
