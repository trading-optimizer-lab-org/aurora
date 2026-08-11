from __future__ import annotations

import numpy as np
import pandas as pd
import json
from pathlib import Path


def test_blocked_signal_placebos_preserve_blocks_and_use_no_sharpe() -> None:
    from aurora.infra.sp500_megarun.dehb_finalist_robustness import (
        blocked_signal_placebo_test,
    )

    index = pd.bdate_range("2000-01-03", periods=504)
    rng = np.random.default_rng(20260810)
    spy = pd.Series(
        rng.choice([-0.01, 0.01], size=len(index)), index=index, name="spy"
    )
    strategy = spy.abs().rename("strategy")

    report = blocked_signal_placebo_test(
        strategy,
        spy,
        seed=77,
        paths=255,
        block_lengths=(5, 10, 20),
    )

    assert report["paths"] == 255
    assert report["block_lengths"] == [5, 10, 20]
    assert report["uses_sharpe"] is False
    assert report["passed"] is True
    assert report["pvalue"] <= 0.05


def test_blocked_signal_placebo_rejects_returns_not_explained_by_spy_position() -> None:
    from aurora.infra.sp500_megarun.dehb_finalist_robustness import (
        FinalistRobustnessError,
        blocked_signal_placebo_test,
    )

    index = pd.bdate_range("2000-01-03", periods=40)
    spy = pd.Series(0.01, index=index)
    strategy = pd.Series(0.005, index=index)
    try:
        blocked_signal_placebo_test(strategy, spy, seed=1, paths=8)
    except FinalistRobustnessError as exc:
        assert "CANDIDATE_RETURN_NOT_SPY_LONG_SHORT" in str(exc)
    else:
        raise AssertionError("invalid strategy-return identity was accepted")


def test_finalist_evidence_closes_all_non_global_train_gates(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_finalist_robustness import (
        apply_finalist_train_gate_evidence,
    )
    from aurora.infra.sp500_megarun.dehb_technical_evidence import (
        build_technical_evidence,
    )

    repo = Path(__file__).resolve().parents[1]
    campaign = load_and_validate_campaign_contract(
        repo / "config/sp500_megarun_dehb_campaign_v1.json"
    )
    report_path = tmp_path / "official.json"
    report_path.write_text(
        json.dumps(
            {
                "ready": True,
                "official_dehb_version": "0.1.2",
                "configspace_version": "1.2.2",
                "lane_count": 240,
                "all_configspaces_exact": True,
                "fidelities": [1, 3, 9, 27],
                "eta": 3,
                "actual_four_worker_run": True,
                "worker_equivalence_1_2_4": True,
                "checkpoint_resume_exact": True,
                "forbidden_config_rejection_safe": True,
                "f015_parameter_grid_finite": True,
                "search_end": "2010-12-31",
                "validation_opened": False,
                "locked_opened": False,
                "snapshot_mounted": False,
                "dependency_lock_verified": True,
            }
        ),
        encoding="utf-8",
    )
    technical = build_technical_evidence(
        campaign,
        official_report_path=report_path,
        work_dir=tmp_path / "faults",
        github_sha="a" * 40,
    )
    matrix = [
        {
            "gate_id": gate_id,
            "name": f"gate_{gate_id}",
            "stage": "test",
            "status": (
                "PENDING"
                if gate_id >= 43
                or gate_id in {15, 16, 21, 22, 23, 24, 26, 28, 31, 40}
                else "MEASURED"
            ),
        }
        for gate_id in range(1, 61)
    ]
    train_manifest = {
        "spy_total_return_execution": {
            "method": "adjusted_open_from_adj_close_divided_by_close",
            "official_distribution_audit": {
                "operational_event_count": 19,
                "uncovered_event_count": 0,
                "validation_opened": False,
                "locked_opened": False,
            },
        }
    }
    prefix = {
        "passed": True,
        "cache_reproduction_passed": True,
        "hot_cache_reproduction": {"passed": True},
        "cold_cache_reproduction": {"passed": True},
    }

    result = apply_finalist_train_gate_evidence(
        matrix,
        campaign_sha256=campaign.sha256,
        lane_id="F001",
        required_datasets=("D_SPY",),
        seed_consensus=3,
        prefix_review=prefix,
        placebo_review={"passed": True},
        regime_review={"regimes": {}},
        train_manifest=train_manifest,
        technical_evidence=technical,
        reconstruction_verified=True,
    )

    pending = [row["gate_id"] for row in result if row["status"] == "PENDING"]
    assert pending == list(range(43, 55))
    assert next(row for row in result if row["gate_id"] == 16)["status"] == (
        "NOT_APPLICABLE"
    )
    assert next(row for row in result if row["gate_id"] == 23)["status"] == "PASS"
    assert all(
        next(row for row in result if row["gate_id"] == gate_id)["status"]
        == "PASS"
        for gate_id in (55, 56, 57, 58, 59, 60)
    )
