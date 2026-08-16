from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_recipe_worker_is_started_as_repo_module_and_store_can_be_reused() -> None:
    worker = Path(".github/workflows/catalog-optimized-worker.yml").read_text(
        encoding="utf-8"
    )
    run = Path(".github/workflows/catalog-optimized-run.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m scripts.run_sp500_optimized_recipe_worker" in worker
    assert "component_store_run_id" in worker
    assert "component_store_run_id" in run
    assert "inputs.component_store_run_id == ''" in run
    resume_gate = (
        "always() && needs.plan.result == 'success' && "
        "needs.merge_components.result == 'success'"
    )
    assert run.count(resume_gate) == 3
    assert (
        "always() && inputs.reference_run_id != '' && "
        "needs.plan.result == 'success' && needs.reduce.result == 'success'"
        in run
    )

    verify_only = Path(
        ".github/workflows/catalog-optimized-verify-only.yml"
    ).read_text(encoding="utf-8")
    assert "optimized_result_run_id" in verify_only
    assert "python -m scripts.verify_sp500_optimized_run" in verify_only
    assert "if: ${{ always() }}" in verify_only


def test_equivalence_gate_allows_only_declared_additive_weekly_metrics() -> None:
    from scripts.verify_sp500_optimized_run import _compare

    expected = {"week_count": 679, "weeks_beating_spy": 131}
    observed = {
        **expected,
        "positive_weeks": 500,
        "winning_or_positive_weeks": 520,
        "weekly_winning_or_positive_rate": 520 / 935,
    }
    differences: list[str] = []
    _compare(expected, observed, path="strategy.info", differences=differences)
    assert differences == []

    observed["week_count"] = 935
    _compare(expected, observed, path="strategy.info", differences=differences)
    assert differences == ["strategy.info.week_count"]

    observed["unknown_metric"] = 1
    unknown: list[str] = []
    _compare(expected, observed, path="strategy.info", differences=unknown)
    assert unknown == ["strategy.info:extra:unknown_metric"]


def test_equivalence_report_counts_every_affected_strategy_but_bounds_details(
    tmp_path: Path,
) -> None:
    import json

    from scripts.verify_sp500_optimized_run import verify_equivalence

    reference = tmp_path / "reference"
    optimized = tmp_path / "optimized"
    reference.mkdir()
    optimized.mkdir()
    expected_rows = []
    observed_rows = []
    for index in range(105):
        strategy_id = f"s{index:03d}"
        expected_rows.append(
            {"strategy_id": strategy_id, "result": {"fitness": float(index)}}
        )
        observed_rows.append(
            {"strategy_id": strategy_id, "result": {"fitness": float(index + 1)}}
        )
    (reference / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in expected_rows), "utf-8"
    )
    (optimized / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in observed_rows), "utf-8"
    )

    report = verify_equivalence(optimized, reference)

    assert report["difference_count"] == 105
    assert report["affected_strategy_count"] == 105
    assert len(report["affected_strategy_ids"]) == 105
    assert len(report["first_differences"]) == 100


def test_targeted_diagnostic_classifies_historical_result_origin() -> None:
    from scripts.diagnose_sp500_catalog_equivalence import classify_result

    reference = {"fitness": 1.0, "info": {"week_count": 679}}
    optimized = {"fitness": 2.0, "info": {"week_count": 679}}
    historical = {"fitness": 1.0, "info": {"week_count": 679}}

    report = classify_result(
        historical=historical,
        optimized=optimized,
        reference=reference,
    )

    assert report["matches_reference"] is True
    assert report["matches_optimized"] is False


def test_component_determinism_audit_groups_repeats_and_detects_conflicts() -> None:
    from scripts.audit_sp500_component_determinism import summarize_receipts

    stable = {
        "configuration_sha256": "a" * 64,
        "lane_id": "F069",
        "signal_sha256": "b" * 64,
        "feature_sha256": "c" * 64,
        "validation_opened": False,
        "locked_opened": False,
    }
    changed = {
        **stable,
        "signal_sha256": "d" * 64,
        "feature_sha256": "e" * 64,
    }

    report = summarize_receipts([stable, dict(stable), changed])

    assert report["component_count"] == 1
    assert report["repeat_count"] == 3
    assert report["deterministic"] is False
    assert report["conflicting_component_count"] == 1
    assert report["components"][0]["unique_signal_hash_count"] == 2


def test_cost_model_and_affinity_scheduler_are_deterministic() -> None:
    from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1
    from aurora.infra.sp500_megarun.catalog_scheduler import schedule_recipes

    model = CatalogCostModelV1.from_samples(
        {
            "fast": [1.0, 1.1, 0.9],
            "slow": [9.0, 10.0, 11.0],
        },
        fallback_seconds=2.0,
    )
    recipes = [
        {"recipe_id": "r0", "component_ids": ["slow"]},
        {"recipe_id": "r1", "component_ids": ["slow", "fast"]},
        {"recipe_id": "r2", "component_ids": ["fast"]},
        {"recipe_id": "r3", "component_ids": ["fast"]},
    ]

    first = schedule_recipes(recipes, model=model, workers=2)
    second = schedule_recipes(list(reversed(recipes)), model=model, workers=2)

    assert first.plan_sha256 == second.plan_sha256
    assert sorted(item for shard in first.shards for item in shard.recipe_ids) == [
        "r0",
        "r1",
        "r2",
        "r3",
    ]
    assert first.tail_ratio <= 1.25


def test_component_store_round_trip_is_exact_and_conflicts_fail(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_component_store import (
        CatalogComponentStore,
        ComponentStoreWriter,
    )

    writer = ComponentStoreWriter(
        tmp_path / "store",
        data_snapshot_sha256="a" * 64,
        evaluator_sha256="b" * 64,
        session_count=5,
    )
    first = np.array([-1, 0, 1, 1, 0], dtype=np.int8)
    second = np.array([1, 1, 0, -1, 0], dtype=np.int8)
    writer.add("c1", first)
    writer.add("c2", second)
    writer.add("c1", first.copy())
    with pytest.raises(ValueError, match="COMPONENT_RESULT_CONFLICT"):
        writer.add("c1", second)
    manifest = writer.commit()

    store = CatalogComponentStore.open(tmp_path / "store")
    assert manifest.component_count == 2
    assert store.manifest.manifest_sha256 == manifest.manifest_sha256
    np.testing.assert_array_equal(store.get("c1"), first)
    np.testing.assert_array_equal(store.get("c2"), second)
    with pytest.raises(KeyError):
        store.get("missing")


def test_component_store_rejects_scientific_mismatch(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_component_store import (
        CatalogComponentStore,
        ComponentStoreWriter,
    )

    writer = ComponentStoreWriter(
        tmp_path / "store",
        data_snapshot_sha256="a" * 64,
        evaluator_sha256="b" * 64,
        session_count=3,
    )
    writer.add("c1", np.array([1, 0, -1], dtype=np.int8))
    writer.commit()

    with pytest.raises(ValueError, match="COMPONENT_STORE_INCOMPATIBLE"):
        CatalogComponentStore.open(
            tmp_path / "store",
            expected_data_snapshot_sha256="c" * 64,
        )


def test_recipe_compiler_canonicalizes_commutative_inputs_but_keeps_explanation() -> None:
    from aurora.infra.sp500_megarun.catalog_recipe_compiler import compile_recipes

    rows = [
        {
            "strategy_id": "left",
            "scientific_recipe_sha256": "1" * 64,
            "components": [
                {"configuration_sha256": "a" * 64},
                {"configuration_sha256": "b" * 64},
            ],
            "composition": {"kind": "and"},
        },
        {
            "strategy_id": "right",
            "scientific_recipe_sha256": "2" * 64,
            "components": [
                {"configuration_sha256": "b" * 64},
                {"configuration_sha256": "a" * 64},
            ],
            "composition": {"kind": "and"},
        },
    ]

    compiled = compile_recipes(rows)
    assert compiled.unique_dag_count == 1
    assert compiled.recipe_count == 2
    assert compiled.recipes[0].dag_sha256 == compiled.recipes[1].dag_sha256
    assert [item.strategy_id for item in compiled.recipes] == ["left", "right"]


@pytest.mark.parametrize("bit_packed", [False, True])
def test_signal_codec_round_trip_is_exact(bit_packed: bool) -> None:
    from aurora.infra.sp500_megarun.catalog_signal_codec import (
        decode_signals,
        encode_signals,
    )

    values = np.array(
        [[-1, 0, 1, 1, 0], [1, -1, 0, 1, -1]],
        dtype=np.int8,
    )
    encoded = encode_signals(values, bit_packed=bit_packed)
    decoded = decode_signals(encoded)

    np.testing.assert_array_equal(decoded, values)
    assert encoded.logical_shape == values.shape
    assert encoded.payload.nbytes <= values.nbytes


def test_vector_engine_matches_scalar_and_deduplicates_positions() -> None:
    from aurora.infra.sp500_megarun.catalog_vector_engine import (
        evaluate_signal_block,
        scalar_reference,
    )

    decisions = np.array(
        [
            [1, 1, 0, -1, -1, 0, 1, 1],
            [1, 1, 0, -1, -1, 0, 1, 1],
            [-1, -1, 0, 1, 1, 0, -1, -1],
        ],
        dtype=np.int8,
    )
    spy_returns = np.array([0.01, -0.02, 0.03, 0.01, -0.01, 0.02, -0.03, 0.01])
    years = np.array([2009, 2009, 2009, 2009, 2010, 2010, 2010, 2010])

    vector = evaluate_signal_block(decisions, spy_returns, years)
    scalar = scalar_reference(decisions, spy_returns, years)

    np.testing.assert_allclose(vector.annualized_return, scalar.annualized_return)
    np.testing.assert_allclose(vector.annual_returns, scalar.annual_returns)
    assert vector.position_hashes == scalar.position_hashes
    assert vector.unique_position_count == 2
    assert vector.behavior_equivalence_hits == 1
    assert vector.validation_opened is False
    assert vector.locked_opened is False
