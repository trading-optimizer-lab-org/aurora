from __future__ import annotations


def _champion(*, replicate: int, fingerprint: str, local: bool = True) -> dict:
    return {
        "lane_id": "F001",
        "replicate": replicate,
        "island_id": f"F001-R{replicate}",
        "strategy_fingerprint": f"strategy-{replicate}".ljust(64, "0")[:64],
        "position_fingerprint": fingerprint,
        "full_fidelity": True,
        "train_feasible": True,
        "candidate_local_robustness_passed": local,
        "archive_key": [0.0, -0.20 - replicate / 1000.0, -0.60, -0.10],
    }


def test_seed_consensus_groups_behavior_clones_and_requires_two_of_three() -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        select_seed_consensus_finalists,
    )

    fingerprint = "f" * 64
    finalists = select_seed_consensus_finalists(
        [
            _champion(replicate=1, fingerprint=fingerprint),
            _champion(replicate=2, fingerprint=fingerprint),
            _champion(replicate=3, fingerprint="e" * 64),
        ]
    )

    assert len(finalists) == 1
    assert finalists[0]["position_fingerprint"] == fingerprint
    assert finalists[0]["seed_consensus"] == 2
    assert finalists[0]["supporting_islands"] == ["F001-R1", "F001-R2"]


def test_seed_consensus_excludes_local_robustness_failure() -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        select_seed_consensus_finalists,
    )

    fingerprint = "f" * 64
    finalists = select_seed_consensus_finalists(
        [
            _champion(replicate=1, fingerprint=fingerprint),
            _champion(replicate=2, fingerprint=fingerprint, local=False),
        ]
    )
    assert finalists == []
