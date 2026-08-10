from __future__ import annotations

import numpy as np
import pandas as pd


def _ledger() -> pd.DataFrame:
    index = pd.bdate_range("2000-01-03", "2001-12-31")
    return pd.DataFrame({"long_return": -0.0002}, index=index)


def _feature(value: float) -> pd.DataFrame:
    dates = _ledger().index
    return pd.DataFrame(
        {"date": dates, "available_at": dates, "value": np.full(len(dates), value)}
    )


def test_full_fidelity_robustness_reports_metrics_neighbors_bootstrap_and_60_gates() -> None:
    from aurora.infra.sp500_megarun.dehb_robustness import (
        review_candidate_robustness,
    )

    report = review_candidate_robustness(
        ledger=_ledger(),
        lane_id="F001",
        configuration={"window": 20},
        parameter_space={"window": (10, 20, 40, 80, 160)},
        feature_evaluator=lambda _lane, _config: _feature(-1.0),
        target_years=(2000, 2001),
        allowed_end="2010-12-31",
        seed=1234,
        bootstrap_paths=64,
        parameter_neighbors=4,
        temporal_delays=(1, 2),
    )

    assert report["candidate_local_passed"] is True
    assert report["passed"] is False
    assert report["neighbor_survival_rate"] == 1.0
    assert report["neighbor_count"] == 4
    assert report["bootstrap"]["paths"] == 64
    assert 0.0 <= report["bootstrap"]["all_year_gate_survival_rate"] <= 1.0
    assert report["period_metrics"]["monthly"]["period_count"] > 0
    assert report["direction_metrics"]["short_sessions"] > 0
    assert len(report["gate_matrix"]) == 60
    assert {row["gate_id"] for row in report["gate_matrix"]} == set(range(1, 61))
    assert all(row["name"] for row in report["gate_matrix"])
    assert {43, 44, 45, 46, 47, 48} <= set(report["pending_global_gate_ids"])
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


def test_neighbor_spike_fails_local_robustness_below_sixty_percent() -> None:
    from aurora.infra.sp500_megarun.dehb_robustness import (
        review_candidate_robustness,
    )

    report = review_candidate_robustness(
        ledger=_ledger(),
        lane_id="F001",
        configuration={"direction": -1},
        parameter_space={"direction": (-1, 1)},
        feature_evaluator=lambda _lane, config: _feature(float(config["direction"])),
        target_years=(2000, 2001),
        allowed_end="2010-12-31",
        seed=99,
        bootstrap_paths=16,
        parameter_neighbors=1,
        temporal_delays=(1,),
    )

    assert report["neighbor_count"] == 1
    assert report["neighbor_survival_rate"] == 0.0
    assert report["candidate_local_passed"] is False
    gate_8 = next(row for row in report["gate_matrix"] if row["gate_id"] == 8)
    assert gate_8["status"] == "FAIL"


def test_forbidden_parameter_neighbors_are_excluded_from_survival_rate() -> None:
    from aurora.infra.sp500_megarun.dehb_robustness import (
        review_candidate_robustness,
    )

    report = review_candidate_robustness(
        ledger=_ledger(),
        lane_id="F001",
        configuration={"direction": -1, "window": 20},
        parameter_space={"direction": (-1, 1), "window": (10, 20, 40)},
        feature_evaluator=lambda _lane, config: _feature(float(config["direction"])),
        target_years=(2000, 2001),
        allowed_end="2010-12-31",
        seed=7,
        bootstrap_paths=8,
        parameter_neighbors=4,
        temporal_delays=(1,),
        configuration_validator=lambda config: not (
            config["direction"] == 1 and config["window"] == 10
        ),
    )

    assert all(
        not (row["configuration"]["direction"] == 1 and row["configuration"]["window"] == 10)
        for row in report["neighbors"]
    )
