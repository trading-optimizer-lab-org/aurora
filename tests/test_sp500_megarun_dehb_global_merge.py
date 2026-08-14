from __future__ import annotations

import json

import pandas as pd


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


def test_candidate_records_accept_replica_float_roundoff_but_reject_material_drift() -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        candidate_records_equivalent,
    )

    base = {
        "candidate_id": "a" * 64,
        "strategy_fingerprint": "a" * 64,
        "position_fingerprint": "b" * 64,
        "lane_id": "F001",
        "configuration": {"window": 20},
        "archive_key": [1.0, 10.0, 1.600029791180237, -0.0512234362344039],
        "train_feasible": False,
    }
    replica_roundoff = {
        **base,
        "archive_key": [1.0, 10.0, 1.600029791180237, -0.05122343623440387],
    }
    material_drift = {
        **base,
        "archive_key": [1.0, 10.0, 1.6000297912, -0.0512234362344039],
    }

    assert candidate_records_equivalent(base, replica_roundoff) is True
    assert candidate_records_equivalent(base, material_drift) is False


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


def test_prefix_comparison_detects_any_changed_past_value() -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        compare_prefix_feature_frames,
    )

    full = pd.DataFrame(
        {
            "date": pd.to_datetime(["2000-01-03", "2000-01-04", "2006-01-03"]),
            "available_at": pd.to_datetime(["2000-01-03", "2000-01-04", "2006-01-03"]),
            "value": [1.0, 2.0, 3.0],
        }
    )
    same = full.iloc[:2].copy()

    assert compare_prefix_feature_frames(full, same, cutoff="2005-12-31")["passed"] is True

    changed = same.copy()
    changed.loc[1, "value"] = 2.1
    report = compare_prefix_feature_frames(full, changed, cutoff="2005-12-31")
    assert report["passed"] is False
    assert report["reason"] == "PREFIX_VALUES_CHANGED"


def test_global_merge_rejects_one_cache_key_with_two_result_hashes() -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        GlobalMergeError,
        register_evaluation_result_hash,
    )

    registry: dict[str, str] = {}
    register_evaluation_result_hash(registry, cache_key_sha256="a" * 64, result_sha256="b" * 64)

    try:
        register_evaluation_result_hash(registry, cache_key_sha256="a" * 64, result_sha256="c" * 64)
    except GlobalMergeError as exc:
        assert "GLOBAL_EVALUATION_CACHE_CONFLICT" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("conflicting cache result was accepted")


def test_cache_conflict_diagnostic_reports_sources_and_changed_fields(tmp_path) -> None:
    from aurora.infra.sp500_megarun.dehb_global_merge import (
        diagnose_evaluation_result_conflicts,
    )

    cache_key = "a" * 64
    rows = (
        {
            "evaluation": 17,
            "run_id": 101,
            "wave": 0,
            "island_id": "F067-R1",
            "fidelity": 8,
            "fitness": -0.21,
            "cost": 8.0,
            "configuration_json": '{"window":20}',
            "info_json": json.dumps(
                {
                    "annualized_alpha": 0.11,
                    "position_fingerprint": "b" * 64,
                    "validation_opened": False,
                    "locked_opened": False,
                },
                sort_keys=True,
            ),
            "cache_key_sha256": cache_key,
            "cache_result_sha256": "c" * 64,
            "evaluation_origin": "physical",
        },
        {
            "evaluation": 9,
            "run_id": 101,
            "wave": 0,
            "island_id": "F067-R2",
            "fidelity": 8,
            "fitness": -0.22,
            "cost": 8.0,
            "configuration_json": '{"window":20}',
            "info_json": json.dumps(
                {
                    "annualized_alpha": 0.10,
                    "position_fingerprint": "d" * 64,
                    "validation_opened": False,
                    "locked_opened": False,
                },
                sort_keys=True,
            ),
            "cache_key_sha256": cache_key,
            "cache_result_sha256": "e" * 64,
            "evaluation_origin": "physical",
        },
    )
    for index, row in enumerate(rows, start=1):
        bundle = tmp_path / f"worker-{index}" / f"island-{index}"
        bundle.mkdir(parents=True)
        pd.DataFrame([row]).to_parquet(bundle / "trial_ledger.parquet", index=False)

    report = diagnose_evaluation_result_conflicts(tmp_path)

    assert report["conflict_count"] == 1
    conflict = report["conflicts"][0]
    assert conflict["cache_key_sha256"] == cache_key
    assert conflict["result_hashes"] == ["c" * 64, "e" * 64]
    assert [source["island_id"] for source in conflict["sources"]] == [
        "F067-R1",
        "F067-R2",
    ]
    assert "fitness" in conflict["changed_fields"]
    assert "info.annualized_alpha" in conflict["changed_fields"]
    assert "info.position_fingerprint" in conflict["changed_fields"]
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
