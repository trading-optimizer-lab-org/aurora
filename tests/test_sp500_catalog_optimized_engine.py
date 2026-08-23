from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def test_recipe_worker_is_started_as_repo_module_and_store_can_be_reused() -> None:
    from scripts.run_sp500_optimized_recipe_worker import _RESULT_SCHEMA

    worker = Path(".github/workflows/catalog-optimized-worker.yml").read_text("utf-8")
    component = Path(".github/workflows/catalog-component-worker.yml").read_text(
        "utf-8"
    )
    run = Path(".github/workflows/catalog-optimized-run.yml").read_text("utf-8")
    worker_script = Path("scripts/run_sp500_optimized_recipe_worker.py").read_text(
        "utf-8"
    )

    assert "python -m scripts.run_catalog_recipe_worker_guarded" in worker
    assert worker.count("python -m scripts.run_catalog_recipe_worker_guarded") == 8
    assert "catalog-worker-failure-final.json" in worker
    assert "catalog-failure-attempt-" in Path(
        "infra/sp500_megarun/catalog_worker_failure.py"
    ).read_text("utf-8")
    assert "--runtime-input-pack \"$RUNNER_TEMP/runtime\"" in worker
    assert "_open_exact_component_payload" in worker_script
    assert "score_prepared_lane_candidate" not in worker_script
    assert "score_ledger_decisions" not in worker_script
    assert "FastTrainObjective" in worker_script
    assert "scientific_stage_seconds" in worker_script
    assert "aurora-runtime-setup" in worker
    assert "aurora-runtime-setup" in component
    assert "setup-uv" not in worker
    assert "setup-uv" not in component
    assert "uv pip install" not in worker
    assert "uv pip install" not in component
    assert "component_store_run_id" not in worker
    assert "--component-shard-index 0" in component
    assert "--total-component-shards 1" in component
    assert "component_cache_persistence_key_prefix" in component
    assert "steps.verify_bundle.outputs.cache_key" in component
    assert "verify_component_store" in run
    assert "needs: [engine_verify_sealed_plan, verify_component_store]" in run
    assert "Build the one locked runtime store" in run
    assert run.count("Build the one locked runtime store") == 1
    assert _RESULT_SCHEMA.names == ["strategy_id", "result_json"]


def test_engine_exposes_one_explicit_verified_outcome_even_after_failure() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    path = Path(".github/workflows/catalog-optimized-run.yml")
    workflow = load_github_yaml(path)
    call_outputs = workflow["on"]["workflow_call"]["outputs"]
    assert call_outputs["campaign_state"]["value"] == (
        "${{ jobs.campaign_outcome.outputs.campaign_state }}"
    )
    assert call_outputs["outcome_evidence_sha256"]["value"] == (
        "${{ jobs.campaign_outcome.outputs.outcome_evidence_sha256 }}"
    )
    assert call_outputs["final_evidence_artifact"]["value"] == (
        "${{ jobs.campaign_outcome.outputs.final_evidence_artifact }}"
    )
    outcome = workflow["jobs"]["campaign_outcome"]
    assert "always()" in outcome["if"]
    assert {
        "reduce",
        "verify_terminal_science",
        "audit_runtime",
        "recovery_wave_6",
    } <= set(outcome["needs"])
    rendered = json.dumps(outcome, sort_keys=True)
    assert "scripts/prepare_catalog_engine_outcome.py" in rendered
    assert "catalog-engine-outcome-${{ inputs.authority_id }}" in rendered


def test_terminal_science_uses_only_the_sealed_reference_identity() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    path = Path(".github/workflows/catalog-optimized-run.yml")
    workflow = load_github_yaml(path)
    job = workflow["jobs"]["verify_terminal_science"]
    rendered = json.dumps(job, sort_keys=True)
    assert "scripts/fetch_catalog_reference_artifact.py" in rendered
    assert "scripts/verify_catalog_terminal_science.py" in rendered
    assert "catalog-terminal-science-${{ inputs.authority_id }}" in rendered
    text = path.read_text("utf-8")
    for forbidden in (
        "9075791134",
        "9264302413",
        "sp500-megarun-dehb-runtime-inputs-31418682679",
        "sp500-strategy-catalog-final-results",
    ):
        assert forbidden not in text


def test_single_pass_recipe_score_is_scientifically_exact() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        scientific_result_sha256,
    )
    from aurora.infra.sp500_megarun.dehb_worker import (
        PreparedLaneCandidate,
        candidate_fingerprints,
        score_prepared_lane_candidate,
    )
    from scripts.run_sp500_optimized_recipe_worker import _evaluate
    from scripts.run_sp500_strategy_catalog_shard import (
        FULL_FIDELITY,
        FULL_YEARS,
        merge_weekly_winning_or_positive_metrics,
        weekly_winning_or_positive_metrics,
    )
    from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions

    index = pd.bdate_range("1998-01-02", "2010-12-31")
    ledger = pd.DataFrame(
        {"long_return": np.where(np.arange(len(index)) % 2, 0.0002, -0.0001)},
        index=index,
    )
    decisions = pd.Series(
        np.where(np.arange(len(index)) % 7 < 4, 1.0, -1.0),
        index=index,
    )
    configuration = {"scientific_recipe_sha256": "a" * 64}
    observed, _ = _evaluate(
        lane_id="unit",
        configuration=configuration,
        decisions=decisions,
        ledger=ledger,
        search_end="2010-12-31",
    )
    strategy_fingerprint, position_fingerprint = candidate_fingerprints(
        "unit",
        configuration,
        decisions,
    )
    prepared = PreparedLaneCandidate(
        lane_id="unit",
        configuration=configuration,
        fidelity=FULL_FIDELITY,
        target_years=FULL_YEARS,
        decisions=decisions,
        strategy_fingerprint=strategy_fingerprint,
        position_fingerprint=position_fingerprint,
    )
    expected = dict(
        score_prepared_lane_candidate(
            prepared,
            ledger=ledger,
            fidelity_years={FULL_FIDELITY: FULL_YEARS},
            allowed_end="2010-12-31",
        )
    )
    realized = score_ledger_decisions(
        ledger,
        decisions,
        target_years=FULL_YEARS,
        allowed_end="2010-12-31",
    )
    expected["info"] = merge_weekly_winning_or_positive_metrics(
        expected["info"],
        weekly_winning_or_positive_metrics(
            realized.strategy_returns,
            realized.spy_returns,
        ),
    )

    assert scientific_result_sha256(observed) == scientific_result_sha256(expected)


def test_fast_train_objective_is_exactly_equal_to_dataframe_reference() -> None:
    from aurora.infra.sp500_megarun.catalog_fast_objective import (
        FastTrainObjective,
    )
    from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions
    from scripts.run_sp500_strategy_catalog_shard import (
        FULL_YEARS,
        weekly_winning_or_positive_metrics,
    )

    index = pd.bdate_range("1996-01-02", "2010-12-31")
    ledger = pd.DataFrame(
        {"long_return": np.sin(np.arange(len(index))) * 0.0003},
        index=index,
    )
    values = np.where(np.arange(len(index)) % 11 == 0, -1.0, np.nan)
    values[np.arange(len(index)) % 17 == 0] = 1.0
    decisions = pd.Series(values, index=index)

    expected = score_ledger_decisions(
        ledger,
        decisions,
        target_years=FULL_YEARS,
        allowed_end="2010-12-31",
    )
    observed = FastTrainObjective(
        ledger,
        target_years=FULL_YEARS,
        allowed_end="2010-12-31",
    ).score(decisions)

    assert observed.score == expected.score
    pd.testing.assert_series_equal(observed.strategy_returns, expected.strategy_returns)
    pd.testing.assert_series_equal(observed.spy_returns, expected.spy_returns)
    assert observed.weekly_calendar_metrics == weekly_winning_or_positive_metrics(
        expected.strategy_returns,
        expected.spy_returns,
    )


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


def test_frozen_reference_manifest_verifies_exact_science_without_oracle_download(
    tmp_path: Path,
) -> None:
    import hashlib
    import json

    from scripts.verify_sp500_optimized_run import (
        scientific_results_sha256,
        verify_reference_manifest,
    )

    optimized = tmp_path / "optimized"
    optimized.mkdir()
    (optimized / "results.jsonl").write_text(
        json.dumps(
            {
                "strategy_id": "s0",
                "result": {
                    "fitness": 1.0,
                    "info": {"objective_runtime_seconds": 99.0},
                },
            }
        )
        + "\n",
        "utf-8",
    )
    count, result_sha256 = scientific_results_sha256(optimized)
    identity = {
        "schema_version": 1,
        "reference_run_id": "123",
        "strategy_count": count,
        "scientific_results_sha256": result_sha256,
        "normalization": "remove_objective_runtime_seconds_exact_json_v1",
        "validation_opened": False,
        "locked_opened": False,
    }
    identity["manifest_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(identity), "utf-8")

    report = verify_reference_manifest(
        optimized,
        manifest,
        expected_reference_run_id="123",
    )

    assert report["equivalent"] is True
    assert report["scientific_results_sha256"] == result_sha256
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


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


def test_component_schedule_uses_measured_costs_and_assigns_each_key_once() -> None:
    from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1
    from aurora.infra.sp500_megarun.catalog_scheduler import schedule_components

    profiles = {
        f"F069:{'a' * 64}": {
            "configuration_sha256": "a" * 64,
            "duration_samples": [20.0, 22.0, 24.0],
        },
        f"F069:{'b' * 64}": {
            "configuration_sha256": "b" * 64,
            "duration_samples": [18.0, 20.0, 21.0],
        },
        f"F001:{'c' * 64}": {
            "configuration_sha256": "c" * 64,
            "duration_samples": [1.0, 1.1, 1.2],
        },
        f"F001:{'d' * 64}": {
            "configuration_sha256": "d" * 64,
            "duration_samples": [1.0, 1.1, 1.2],
        },
    }
    model = CatalogCostModelV1.from_performance_profiles(
        profiles,
        fallback_seconds=1.0,
    )
    components = [
        {"lane_id": "F069" if key in "ab" else "F001", "configuration_sha256": key * 64}
        for key in "abcd"
    ]

    schedule = schedule_components(components, model=model, workers=2)

    assigned = [key for shard in schedule.shards for key in shard.component_ids]
    assert sorted(assigned) == sorted(key * 64 for key in "abcd")
    assert len(assigned) == len(set(assigned)) == 4
    assert all(shard.estimated_seconds > 0 for shard in schedule.shards)
    assert schedule.tail_ratio < 1.2


def test_affinity_component_schedule_keeps_required_dataset_sets_together() -> None:
    from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1
    from aurora.infra.sp500_megarun.catalog_scheduler import (
        schedule_components_by_affinity,
    )

    components = [
        {"configuration_sha256": f"{index:064x}", "lane_id": "F001"}
        for index in range(6)
    ]
    model = CatalogCostModelV1.from_samples(
        {str(index): [1.0] for index in range(6)},
        fallback_seconds=1.0,
    )
    affinity = {
        f"{index:064x}": ("D_SPY",) if index < 3 else ("D_Z1",)
        for index in range(6)
    }
    schedule = schedule_components_by_affinity(
        components,
        model=model,
        workers=4,
        affinity_by_component=affinity,
    )
    assert len(schedule.shards) == 4
    assert sorted(
        component_id
        for shard in schedule.shards
        for component_id in shard.component_ids
    ) == sorted(affinity)
    # Each group has two workers in this balanced fixture, so no shard can
    # contain components from both input families.
    for shard in schedule.shards:
        families = {
            "D_SPY" if component_id in {f"{i:064x}" for i in range(3)} else "D_Z1"
            for component_id in shard.component_ids
        }
        assert len(families) <= 1


def test_component_performance_merge_preserves_every_physical_cost(
    tmp_path: Path,
) -> None:
    from scripts.merge_sp500_component_store import merge_component_performance

    for index, duration in enumerate((1.0, 3.0, 2.0)):
        root = tmp_path / str(index)
        root.mkdir()
        component_id = f"{index + 1:064x}"
        profile = {
            "lane_id": f"F{index + 1:03d}",
            "configuration_sha256": component_id,
            "duration_samples": [duration],
            "sample_count": 1,
            "p50_seconds": duration,
            "p90_seconds": duration,
            "p95_seconds": duration,
            "p99_seconds": duration,
            "physical_seconds": duration,
        }
        (root / "component_performance.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "component_profiles": {
                        f"F{index + 1:03d}:{component_id}": profile
                    },
                    "physical_component_builds": 1,
                    "physical_component_seconds": duration,
                    "shard_seconds": duration,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ),
            "utf-8",
        )

    merged = merge_component_performance(tmp_path)
    assert merged["physical_component_builds"] == 3
    assert merged["physical_component_seconds"] == 6.0
    assert merged["component_worker_p50_seconds"] == 2.0
    assert merged["component_worker_p95_seconds"] == 3.0


def test_catalog_science_identity_excludes_replaceable_run_infrastructure() -> None:
    from aurora.infra.sp500_megarun.catalog_source_identity import (
        catalog_infrastructure_source_paths,
        catalog_scientific_source_paths,
    )

    root = Path.cwd().resolve()
    science = {
        path.relative_to(root).as_posix()
        for path in catalog_scientific_source_paths(root)
    }
    infrastructure = {
        path.relative_to(root).as_posix()
        for path in catalog_infrastructure_source_paths(root)
    }

    assert "infra/sp500_megarun/advanced_feature_engine.py" in science
    assert "infra/sp500_megarun/dehb_objective.py" in science
    assert "infra/sp500_megarun/catalog_scheduler.py" not in science
    assert ".github/workflows/catalog-optimized-run.yml" in infrastructure
    assert "scripts/run_sp500_optimized_recipe_worker.py" in infrastructure
    assert "scripts/audit_sp500_catalog_actions_run.py" in infrastructure
    assert science.isdisjoint(infrastructure)


@pytest.mark.parametrize("kind", ["garch", "gjr", "egarch"])
def test_compiled_volatility_path_matches_frozen_python_kernel(kind: str) -> None:
    from aurora.infra.sp500_megarun.advanced_feature_engine import (
        _decode_volatility_parameters,
        _variance_path,
        _variance_path_python,
    )

    residuals = np.linspace(-1.2, 1.3, 96, dtype=np.float64)
    p = 2
    q = 2
    count = 1 + (p + q if kind == "garch" else 2 * p + q)
    model = _decode_volatility_parameters(
        np.linspace(-0.4, 0.5, count, dtype=np.float64),
        kind=kind,
        p=p,
        q=q,
        variance=float(np.var(residuals)),
    )

    expected = _variance_path_python(
        residuals,
        model,
        expected_absolute=np.sqrt(2.0 / np.pi),
    )
    observed = _variance_path(
        residuals,
        model,
        expected_absolute=np.sqrt(2.0 / np.pi),
    )

    if kind == "egarch":
        np.testing.assert_array_equal(observed, expected)
    else:
        np.testing.assert_allclose(observed, expected, rtol=1e-13, atol=1e-13)


def test_vectorized_temporal_convolution_matches_frozen_python_kernel() -> None:
    from aurora.infra.sp500_megarun.predictive_feature_engine import (
        _convolution_basis,
        _convolution_basis_python,
    )

    generator = np.random.default_rng(148)
    sequences = generator.normal(size=(37, 63, 5))
    sequences[3] = np.nan
    filters = generator.normal(size=(4, 5, 3))
    expected = _convolution_basis_python(sequences, filters, dilation=4)
    observed = _convolution_basis(sequences, filters, dilation=4)
    for actual, reference in zip(observed, expected, strict=True):
        np.testing.assert_array_equal(actual, reference)


def test_vectorized_reservoir_states_match_frozen_python_kernel() -> None:
    from aurora.infra.sp500_megarun.predictive_feature_engine import (
        _reservoir_states,
        _reservoir_final_states,
        _reservoir_states_python,
        _reservoir_weights,
    )

    generator = np.random.default_rng(149)
    sequences = generator.normal(size=(41, 24, 7))
    sequences[5] = np.nan
    input_weight, recurrent, bias = _reservoir_weights(
        7,
        32,
        kind="reservoir",
        spectral_radius=0.7,
        seed=149,
    )
    expected = _reservoir_states_python(
        sequences,
        input_weight=input_weight,
        recurrent=recurrent,
        bias=bias,
        leak=0.4,
    )
    observed = _reservoir_states(
        sequences,
        input_weight=input_weight,
        recurrent=recurrent,
        bias=bias,
        leak=0.4,
    )
    for actual, reference in zip(observed, expected, strict=True):
        np.testing.assert_allclose(actual, reference, rtol=1e-13, atol=1e-13)
    np.testing.assert_allclose(
        _reservoir_final_states(
            sequences,
            input_weight=input_weight,
            recurrent=recurrent,
            bias=bias,
            leak=0.4,
        ),
        expected[0],
        rtol=1e-13,
        atol=1e-13,
    )


def test_parallel_sequence_refits_preserve_serial_results_exactly() -> None:
    from aurora.infra.sp500_megarun.predictive_feature_engine import (
        _rolling_sequence_model,
    )

    generator = np.random.default_rng(150)
    market = pd.DataFrame(
        {"date": pd.bdate_range("2000-01-03", periods=180)}
    )
    sequences = generator.normal(size=(180, 8, 4))
    target = generator.normal(size=180)

    def fit(x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        return {"mean": np.mean(x, axis=(0, 1)), "target": np.array([y.mean()])}

    def predict(model: dict[str, np.ndarray], row: np.ndarray) -> dict[str, float]:
        return {"value": float(np.mean(row - model["mean"]) + model["target"][0])}

    serial = _rolling_sequence_model(
        market,
        sequences,
        target,
        window=60,
        cadence="monthly",
        fit=fit,
        predict=predict,
        statistic="value",
        parallel_refits=False,
    )
    parallel = _rolling_sequence_model(
        market,
        sequences,
        target,
        window=60,
        cadence="monthly",
        fit=fit,
        predict=predict,
        statistic="value",
        parallel_refits=True,
    )
    np.testing.assert_array_equal(parallel.to_numpy(), serial.to_numpy())


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

    with CatalogComponentStore.open(tmp_path / "store") as store:
        assert manifest.component_count == 2
        assert store.manifest.manifest_sha256 == manifest.manifest_sha256
        np.testing.assert_array_equal(store.get("c1"), first)
        np.testing.assert_array_equal(store.get("c2"), second)
        with pytest.raises(KeyError):
            store.get("missing")
    with pytest.raises(ValueError, match="COMPONENT_STORE_CLOSED"):
        store.get("c1")
    (tmp_path / "store" / "signals.npy").unlink()


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


def test_component_store_closes_mmap_when_loaded_shape_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.infra.sp500_megarun import catalog_component_store as module

    writer = module.ComponentStoreWriter(
        tmp_path / "store",
        data_snapshot_sha256="a" * 64,
        evaluator_sha256="b" * 64,
        session_count=3,
    )
    writer.add("c1", np.array([1, 0, -1], dtype=np.int8))
    writer.commit()

    class Mapping:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Matrix:
        shape = (99, 99)
        _mmap = Mapping()

    matrix = Matrix()
    monkeypatch.setattr(module.np, "load", lambda *_args, **_kwargs: matrix)
    with pytest.raises(ValueError, match="COMPONENT_STORE_MATRIX_SHAPE_INVALID"):
        module.CatalogComponentStore.open(tmp_path / "store")
    assert matrix._mmap.closed is True


def test_component_store_merge_closes_sources_if_a_later_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.infra.sp500_megarun import catalog_component_store as module

    class OpenedStore:
        closed = False

        def close(self) -> None:
            self.closed = True

    first = OpenedStore()

    def fake_open(_cls: object, path: Path, **_kwargs: object) -> OpenedStore:
        if Path(path).name == "first":
            return first
        raise ValueError("COMPONENT_STORE_MANIFEST_INVALID")

    monkeypatch.setattr(module.CatalogComponentStore, "open", classmethod(fake_open))
    with pytest.raises(ValueError, match="COMPONENT_STORE_MANIFEST_INVALID"):
        module.merge_component_stores(
            [tmp_path / "first", tmp_path / "second"],
            tmp_path / "merged",
        )
    assert first.closed is True


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


def test_authoritative_recipe_dag_artifact_preserves_every_catalog_row(
    tmp_path: Path,
) -> None:
    from scripts.compile_sp500_catalog_recipes import (
        verify_recipe_dag_artifacts,
        write_recipe_dag_artifacts,
    )

    catalog = Path("config/sp500_megarun_strategy_catalog_v1/catalog.jsonl")
    manifest = write_recipe_dag_artifacts(catalog, tmp_path)
    verified = verify_recipe_dag_artifacts(
        tmp_path / "recipe_dag.parquet",
        tmp_path / "recipe_dag_manifest.json",
    )

    assert manifest["recipe_count"] == 37_258
    assert verified == manifest
    assert manifest["unique_dag_count"] <= manifest["recipe_count"]
    assert manifest["validation_opened"] is False
    assert manifest["locked_opened"] is False


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


def test_cold_runtime_is_built_at_most_once_and_workers_restore_offline() -> None:
    run = Path(".github/workflows/catalog-optimized-run.yml").read_text("utf-8")
    worker = Path(".github/workflows/catalog-optimized-worker.yml").read_text("utf-8")
    component = Path(".github/workflows/catalog-component-worker.yml").read_text("utf-8")
    setup = Path(".github/actions/aurora-runtime-setup/action.yml").read_text("utf-8")

    assert run.count("Build the one locked runtime store") == 1
    assert "--require-hashes" in run
    assert "--no-index" in setup
    assert "--require-hashes" in setup
    assert "aurora-runtime-setup" in worker
    assert "aurora-runtime-setup" in component
    assert "pip install -r requirements" not in worker
    assert "pip install -r requirements" not in component
    assert "uv pip install" not in worker
    assert "uv pip install" not in component
    assert "setup-uv" not in worker
    assert "setup-uv" not in component


def test_runtime_audit_proves_runner_inventory_commit_and_zero_cost() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    path = Path(".github/workflows/catalog-optimized-run.yml")
    workflow = load_github_yaml(path)
    audit = workflow["jobs"]["audit_runtime"]
    text = json.dumps(audit, sort_keys=True)
    assert "verify_terminal_science" in audit["needs"]
    assert "audit_catalog_runtime.py" in text
    assert "jobs-confirmation.json" in text
    assert "artifacts-confirmation.json" in text
    assert "catalog-sealed-execution-plan-${{ inputs.authority_id }}" in text
    assert "--components-reused" in text
    assert "--components-computed-once" in text
    for required in (
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
    ):
        assert required in text


def test_rebuildable_cache_persistence_failure_does_not_discard_same_run_bytes() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    paths = (
        Path(".github/workflows/catalog-optimized-run.yml"),
        Path(".github/workflows/catalog-component-worker.yml"),
    )
    save_steps = []
    for path in paths:
        workflow = load_github_yaml(path)
        for job in workflow["jobs"].values():
            for step in job.get("steps", ()):
                if str(step.get("uses", "")).startswith("actions/cache/save@"):
                    save_steps.append(step)
    assert len(save_steps) == 11
    assert all(step.get("continue-on-error") is True for step in save_steps)
    assert "Upload one-day runtime transport" in paths[0].read_text("utf-8")
    assert "Upload one-day exact component transport" in paths[1].read_text("utf-8")


def test_recipe_workers_have_exact_payloads_and_no_component_escape() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    root = Path(".github/workflows")
    run = load_github_yaml(root / "catalog-optimized-run.yml")
    worker = load_github_yaml(root / "catalog-optimized-worker.yml")
    component = load_github_yaml(root / "catalog-component-worker.yml")
    required_route_inputs = {
        "worker_id",
        "descriptor_bundle_artifact",
        "descriptor_member",
        "descriptor_sha256",
    }
    assert required_route_inputs <= set(worker["on"]["workflow_call"]["inputs"])
    assert required_route_inputs <= set(component["on"]["workflow_call"]["inputs"])
    forbidden_inputs = {
        "runtime_input_run_id",
        "component_store_run_id",
        "shard_index",
        "active_workers",
        "component_shard_index",
        "total_component_shards",
    }
    assert not forbidden_inputs.intersection(worker["on"]["workflow_call"]["inputs"])
    assert not forbidden_inputs.intersection(component["on"]["workflow_call"]["inputs"])

    for job_name in ("evaluate_a", "evaluate_b", "evaluate_c"):
        job = run["jobs"][job_name]
        assert "verify_component_store" in job["needs"]
        assert set(job["with"]) >= required_route_inputs

    text = (root / "catalog-optimized-worker.yml").read_text("utf-8").lower()
    for forbidden in (
        "build-component",
        "compute-component",
        "component fallback",
        "allow-component-miss",
    ):
        assert forbidden not in text
    assert "component_payload_incomplete" in text
    assert "download every" not in text


def test_recipe_worker_unrolls_exactly_eight_checkpoint_step_pairs() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    worker = load_github_yaml(
        Path(".github/workflows/catalog-optimized-worker.yml")
    )
    steps = worker["jobs"]["evaluate"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    for slot in range(1, 9):
        assert names.count(f"Compute checkpoint segment {slot}") == 1
        assert names.count(f"Upload checkpoint segment {slot}") == 1
    assert sum(name.startswith("Compute checkpoint segment ") for name in names) == 8
    assert sum(name.startswith("Upload checkpoint segment ") for name in names) == 8
    assert all(
        "checkpoint_slot_count" in json.dumps(step, sort_keys=True)
        for step in steps
        if str(step.get("name", "")).startswith("Compute checkpoint segment ")
        or str(step.get("name", "")).startswith("Upload checkpoint segment ")
    )


def test_each_next_checkpoint_requires_a_durable_upload_receipt() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    worker = load_github_yaml(
        Path(".github/workflows/catalog-optimized-worker.yml")
    )
    steps = {
        str(step.get("id")): step
        for step in worker["jobs"]["evaluate"]["steps"]
        if step.get("id")
    }
    for slot in range(2, 9):
        condition = str(steps[f"compute_{slot}"]["if"])
        prior = slot - 1
        assert f"steps.upload_{prior}.outputs['artifact-id'] != ''" in condition
        assert f"steps.upload_{prior}.outputs['artifact-digest'] != ''" in condition


def test_engine_reduces_sealed_checkpoint_groups_before_final_merge() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    run = load_github_yaml(
        Path(".github/workflows/catalog-optimized-run.yml")
    )
    jobs = run["jobs"]
    grouped = jobs["reduce_groups"]
    assert grouped["strategy"]["max-parallel"] <= 15
    assert "reduction_matrix" in str(grouped["strategy"]["matrix"])
    grouped_text = json.dumps(grouped, sort_keys=True)
    assert "checkpoint_artifact_pattern" in grouped_text
    assert "scripts.reduce_sp500_optimized_catalog_group" in grouped_text
    assert "retention-days\": 1" in grouped_text

    final = jobs["reduce"]
    assert "reduce_groups" in final["needs"]
    final_text = json.dumps(final, sort_keys=True)
    assert "reduction_artifact_pattern" in final_text
    assert "catalog-checkpoint-*" not in final_text
    assert "--reduction-plan" in final_text


def test_every_active_registry_engine_uses_the_common_efficient_path() -> None:
    from aurora.infra.github_performance.preflight import (
        CATALOG_ACTIVE_ENGINE_WORKFLOWS,
        load_github_yaml,
        validate_catalog_workflow_topology,
    )
    from aurora.infra.sp500_megarun.catalog_campaign_registry import (
        load_catalog_campaign_registry,
    )

    root = Path(".")
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    active = [campaign for campaign in registry.campaigns if campaign.active]
    assert active
    assert {campaign.engine_id for campaign in active} <= set(
        CATALOG_ACTIVE_ENGINE_WORKFLOWS
    )
    receipt = validate_catalog_workflow_topology(
        repo_root=root,
        registry=registry,
    )
    assert receipt.status == "ready"
    assert receipt.violations == ()

    for campaign in active:
        path = Path(CATALOG_ACTIVE_ENGINE_WORKFLOWS[campaign.engine_id])
        workflow = load_github_yaml(path)
        assert set(workflow["on"]) == {"workflow_call"}
        jobs = workflow["jobs"]
        recipe_jobs = [
            job
            for job in jobs.values()
            if job.get("uses")
            == "./.github/workflows/catalog-optimized-worker.yml"
        ]
        assert recipe_jobs
        assert all("verify_component_store" in job["needs"] for job in recipe_jobs)
        assert jobs["reduce_groups"]["strategy"]["max-parallel"] <= 15
        assert "reduce_groups" in jobs["reduce"]["needs"]


def test_weekly_keeper_is_read_only_and_cannot_launch_science() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    keeper_path = Path(".github/workflows/catalog-artifact-keeper.yml")
    keeper = load_github_yaml(keeper_path)
    assert keeper["on"] == {"schedule": [{"cron": "17 3 * * 0"}]}
    assert keeper["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "read",
    }
    audit = keeper["jobs"]["live_controls_audit_before_maintenance"]
    assert audit["uses"] == "./.github/workflows/catalog-live-controls-audit.yml"
    assert audit["with"]["purpose"] == "maintenance"
    assert "steps" not in audit
    assert "secrets" not in audit
    preservation = keeper["jobs"]["inventory_and_preserve"]
    assert preservation["runs-on"] == "ubuntu-24.04"
    assert preservation["timeout-minutes"] == 20
    assert "environment" not in preservation
    assert "secrets" not in preservation
    text = keeper_path.read_text("utf-8").lower()
    for forbidden in (
        "workflow_dispatch",
        "catalog-optimized-run.yml",
        "catalog-component-worker.yml",
        "catalog-optimized-worker.yml",
        "--method post",
        "--method patch",
        "--method delete",
    ):
        assert forbidden not in text
    assert "--maximum-download-bytes 1073741824" in text
    assert "--maximum-artifact-copies 8" in text
    assert "--maximum-cache-restores 16" in text


def test_keeper_source_contract_is_closed_and_covers_active_registry() -> None:
    from scripts.run_catalog_artifact_keeper import _validate_contract

    registry = json.loads(Path("config/catalog_campaign_registry_v1.json").read_text("utf-8"))
    source_contract = json.loads(
        Path("config/catalog_keeper_source_artifacts_v1.json").read_text("utf-8")
    )
    rows = _validate_contract(
        source_contract,
        repository="trading-optimizer-lab-org/aurora",
        registry=registry,
    )

    assert {row["contract_name"] for row in rows} == {
        "runtime_input_pack_v1",
        "reference_oracle_v1",
    }
    assert all(row["validation_opened"] is False for row in rows)
    assert all(row["locked_opened"] is False for row in rows)


def test_keeper_closed_file_verifier_rejects_one_changed_byte(tmp_path: Path) -> None:
    from scripts.run_catalog_artifact_keeper import (
        KeeperError,
        _file_sha256,
        _verify_closed_file_list,
    )

    root = tmp_path / "artifact"
    root.mkdir()
    target = root / "receipt.json"
    target.write_bytes(b"sealed\n")
    contract = {
        "files": [
            {
                "path": "receipt.json",
                "bytes": target.stat().st_size,
                "sha256": _file_sha256(target),
            }
        ]
    }
    assert len(_verify_closed_file_list(root, contract)) == 64

    target.write_bytes(b"changed\n")
    with pytest.raises(KeeperError, match="KEEPER_SOURCE_CONTENT_MISMATCH"):
        _verify_closed_file_list(root, contract)


def test_keeper_network_client_is_get_only_and_has_no_science_escape() -> None:
    text = Path("scripts/run_catalog_artifact_keeper.py").read_text("utf-8").lower()
    assert 'method="get"' in text
    for forbidden in (
        'method="post"',
        'method="patch"',
        'method="delete"',
        "subprocess",
        "build_sp500_component_store",
        "run_sp500_optimized_recipe_worker",
        "reduce_sp500_optimized_catalog_run",
    ):
        assert forbidden not in text


def test_keeper_drops_github_token_on_signed_storage_redirect() -> None:
    from urllib.request import Request

    from scripts.run_catalog_artifact_keeper import _ArtifactRedirectHandler

    source = Request(
        "https://api.github.com/repos/example/example/actions/artifacts/1/zip",
        method="GET",
        headers={"Authorization": "Bearer must-not-leak"},
    )
    redirected = _ArtifactRedirectHandler().redirect_request(
        source,
        None,
        302,
        "Found",
        {},
        "https://example.blob.core.windows.net/result/file.zip?sealed=1",
    )
    assert redirected is not None
    assert not any(
        key.casefold() == "authorization" for key in redirected.headers
    )


def test_exact_runtime_fragment_assembly_rejects_cross_artifact_conflicts(
    tmp_path: Path,
) -> None:
    from aurora.infra.github_performance.contracts import canonical_sha256
    from scripts.assemble_sp500_runtime_fragments import (
        assemble_runtime_fragments,
    )

    fragment_root = tmp_path / "fragments"
    names = ("catalog-input-a", "catalog-input-b")
    for name in names:
        target = fragment_root / name / "train_snapshot_1993_2010"
        target.mkdir(parents=True)
        (target / f"{name}.parquet").write_bytes(name.encode("ascii"))
    identity_sha256 = "a" * 64
    manifest_sha256 = canonical_sha256(
        {
            "schema_version": "1",
            "artifacts": names,
            "prepared_input_identity_sha256": identity_sha256,
        }
    )
    receipt = assemble_runtime_fragments(
        fragment_root,
        tmp_path / "assembled",
        artifact_names=names,
        prepared_input_identity_sha256=identity_sha256,
        expected_artifact_manifest_sha256=manifest_sha256,
    )
    assert receipt["file_count"] == 2

    shared = Path("shared.json")
    (fragment_root / names[0] / shared).write_text("left", "utf-8")
    (fragment_root / names[1] / shared).write_text("right", "utf-8")
    with pytest.raises(ValueError, match="RUNTIME_FRAGMENT_FILE_CONFLICT"):
        assemble_runtime_fragments(
            fragment_root,
            tmp_path / "conflict",
            artifact_names=names,
            prepared_input_identity_sha256=identity_sha256,
            expected_artifact_manifest_sha256=manifest_sha256,
        )


def test_recipe_worker_reads_exact_component_bundles_without_merging_copy(
    tmp_path: Path,
) -> None:
    from aurora.infra.github_performance.contracts import canonical_sha256
    from aurora.infra.sp500_megarun.catalog_component_store import (
        ComponentStoreWriter,
    )
    from scripts.run_sp500_optimized_recipe_worker import (
        _open_exact_component_payload,
    )

    payload_root = tmp_path / "components"
    for ordinal, values in enumerate(
        (np.array([1, 0, -1], dtype=np.int8), np.array([-1, 1, 0], dtype=np.int8))
    ):
        source_id = f"{ordinal + 1:064x}"
        root = payload_root / f"bundle-{ordinal}"
        writer = ComponentStoreWriter(
            root,
            data_snapshot_sha256="a" * 64,
            evaluator_sha256="b" * 64,
            session_count=3,
        )
        writer.add(source_id, values)
        manifest = writer.commit()
        identity = {
            "schema_version": "1",
            "bundle_identity_sha256": f"{ordinal + 10:064x}",
            "component_store_manifest_sha256": manifest.manifest_sha256,
            "component_count": 1,
            "components": [
                {
                    "component_id": f"{ordinal + 20:064x}",
                    "source_configuration_sha256": source_id,
                    "result_sha256": manifest.entries[0].result_sha256,
                }
            ],
            "validation_opened": False,
            "locked_opened": False,
        }
        (root / "component_bundle_manifest.json").write_text(
            json.dumps(
                {**identity, "manifest_sha256": canonical_sha256(identity)},
                sort_keys=True,
            )
            + "\n",
            "utf-8",
        )

    payload = _open_exact_component_payload(
        payload_root,
        data_snapshot_sha256="a" * 64,
        evaluator_sha256="b" * 64,
    )
    np.testing.assert_array_equal(payload.get(f"{1:064x}"), [1, 0, -1])
    np.testing.assert_array_equal(payload.get(f"{2:064x}"), [-1, 1, 0])
    assert not (payload_root / "signals.npy").exists()


def test_runtime_and_nine_prepared_partitions_are_reused_selectively() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    workflow_path = Path(".github/workflows/catalog-optimized-run.yml")
    workflow = load_github_yaml(workflow_path)
    steps = workflow["jobs"]["prepare_runtime_and_inputs"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    assert sum(name.startswith("Restore prepared ") for name in names) == 9
    assert sum(name.startswith("Save prepared ") for name in names) == 9
    assert sum(
        name.startswith("Upload one-day prepared ") for name in names
    ) == 9
    text = workflow_path.read_text("utf-8")
    assert "scripts/fetch_catalog_runtime_input_artifact.py" in text
    assert "9075791134" not in text
    assert "--partition-id" in text
    assert "prepared-input-store" not in text
    runtime_save = next(
        step for step in steps if step.get("name") == "Save exact immutable runtime cache"
    )
    assert runtime_save["with"]["key"] == "${{ steps.runtime_build.outputs.cache_key }}"


def test_runtime_preparation_publishes_one_small_bound_terminal_seal() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml

    workflow = load_github_yaml(
        Path(".github/workflows/catalog-optimized-run.yml")
    )
    steps = workflow["jobs"]["prepare_runtime_and_inputs"]["steps"]
    seal = next(
        step
        for step in steps
        if step.get("name") == "Publish bound runtime and prepared-input seal"
    )
    assert seal["with"]["name"] == (
        "catalog-runtime-prepared-seal-${{ inputs.authority_id }}"
    )
    assert seal["with"]["retention-days"] == 90
    rendered = json.dumps(steps, sort_keys=True)
    for binding in (
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "protected_commit_sha",
        "prepared_input_identity_sha256",
        "runtime_identity_sha256",
    ):
        assert binding in rendered
