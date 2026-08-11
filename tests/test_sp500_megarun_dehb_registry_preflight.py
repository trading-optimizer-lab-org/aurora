from __future__ import annotations

import pandas as pd
import pytest


def test_registry_preflight_exercises_240_routes_without_scoring_performance() -> None:
    from aurora.infra.sp500_megarun.dehb_registry_preflight import (
        audit_lane_registry,
    )

    lanes = tuple(f"F{number:03d}" for number in range(1, 241))
    report = audit_lane_registry(
        evaluator=lambda lane, _config: pd.DataFrame(
            {
                "date": pd.to_datetime(["2000-01-03", "2000-01-04"]),
                "available_at": pd.to_datetime(["2000-01-03", "2000-01-04"]),
                "value": [1.0, -float(int(lane[1:]))],
            }
        ),
        default_configurations={lane: {} for lane in lanes},
        expected_lane_ids=lanes,
        allowed_end="2010-12-31",
    )

    assert report["ready"] is True
    assert report["lane_count"] == 240
    assert report["performance_scored"] is False
    assert report["search_executed"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert len(report["aggregate_decision_sha256"]) == 64


def test_registry_preflight_fails_closed_on_future_availability() -> None:
    from aurora.infra.sp500_megarun.dehb_worker import DehbWorkerError
    from aurora.infra.sp500_megarun.dehb_registry_preflight import (
        audit_lane_registry,
    )

    with pytest.raises(DehbWorkerError, match="FEATURE_AVAILABLE_AFTER_DECISION"):
        audit_lane_registry(
            evaluator=lambda _lane, _config: pd.DataFrame(
                {
                    "date": pd.to_datetime(["2000-01-03"]),
                    "available_at": pd.to_datetime(["2000-01-04"]),
                    "value": [1.0],
                }
            ),
            default_configurations={"F001": {}},
            expected_lane_ids=("F001",),
            allowed_end="2010-12-31",
        )
