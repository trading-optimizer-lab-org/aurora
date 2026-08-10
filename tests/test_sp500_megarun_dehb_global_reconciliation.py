from __future__ import annotations


def _gate_rows(*, validation_pending: bool) -> list[dict[str, object]]:
    return [
        {
            "gate_id": gate_id,
            "stage": "validation" if 49 <= gate_id <= 54 else "train",
            "status": "PENDING" if validation_pending and 49 <= gate_id <= 54 else "PASS",
        }
        for gate_id in range(1, 61)
    ]


def test_train_candidate_can_freeze_before_validation_gates_are_opened() -> None:
    from scripts.reduce_sp500_megarun_dehb_global import _reconcile_finalist

    finalist = {
        "strategy_fingerprint": "a" * 64,
        "position_fingerprint": "b" * 64,
        "lane_id": "F001",
        "archive_key": [0.0, -0.2, -0.6, -0.1],
        "seed_consensus": 3,
        "supporting_islands": ["F001-R1", "F001-R2", "F001-R3"],
        "candidate_local_robustness_passed": True,
        "robustness": {"gate_matrix": _gate_rows(validation_pending=True)},
    }
    multiplicity = {
        "finalists": {
            "a" * 64: {
                "passed": True,
                "gates": {str(gate_id): True for gate_id in range(43, 49)},
            }
        }
    }

    result = _reconcile_finalist(finalist, multiplicity)

    assert result["train_freeze_eligible"] is True
    assert result["all_60_gates_passed"] is False
    assert [
        row["gate_id"] for row in result["gate_matrix"] if row["status"] == "PENDING"
    ] == list(range(49, 55))
