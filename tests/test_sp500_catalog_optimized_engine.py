from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def test_recipe_worker_is_started_as_repo_module_and_store_can_be_reused() -> None:
    from scripts.run_sp500_optimized_recipe_worker import _RESULT_SCHEMA

    worker = Path(".github/workflows/catalog-optimized-worker.yml").read_text(
        encoding="utf-8"
    )
    run = Path(".github/workflows/catalog-optimized-run.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m scripts.run_sp500_optimized_recipe_worker" in worker
    assert "plan.processes_per_worker" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "plan.component_processes_per_worker" in Path(
        "scripts/build_sp500_component_store.py"
    ).read_text("utf-8")
    assert "score_prepared_lane_candidate" not in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "score_ledger_decisions" not in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "FastTrainObjective" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "scientific_stage_seconds" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "scientific_attribution_difference_ratio" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "component_store_run_id" in worker
    assert "continue-on-error: true" in worker
    assert "if: ${{ always() }}" in worker
    assert "steps.evaluate.outcome != 'success'" in worker
    assert "recovery_microshards" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d" in worker
    assert "uv pip install --system --require-hashes" in worker
    assert "PYTHONPATH: ${{ github.workspace }}/.." in worker
    assert "pip install --no-deps -e ." not in worker
    assert "component_store_run_id" in run
    assert "inputs.component_store_run_id != '' || needs.merge_components.result == 'success'" in run
    assert "inputs.component_store_run_id || github.run_id" in run
    assert "component_cost_run_id" in run
    assert "evaluation_cache_run_ids" in run
    assert "pending_recipe_count" in run
    assert "resume_work_manifest.json" in worker
    assert "--resume-root" in run
    assert "python -m scripts.plan_sp500_component_schedule" in run
    assert "python -m scripts.audit_sp500_catalog_actions_run" in run
    assert "PYTHONPATH: ${{ github.workspace }}/.." in run
    assert "python scripts/verify_sp500_optimized_run.py" in run
    assert "  verify_qualification:" not in run
    assert "sp500-catalog-runtime-audit" in run
    audit_section = run.split("  audit_runtime:", 1)[1].split(
        "  update_autotune:", 1
    )[0]
    assert "pip install" not in audit_section
    assert "pip install --no-deps -e ." not in run
    assert run.count(
        "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d"
    ) == 5
    assert run.count("uv pip install --system --require-hashes") == 5
    assert "python -m scripts.compile_sp500_catalog_recipes" in run
    assert "--recipe-dag" in worker
    assert "verify_recipe_dag_artifacts" in Path(
        "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")

    combined = "\n".join(
        Path(path).read_text("utf-8")
        for path in (
            ".github/workflows/catalog-optimized-run.yml",
            ".github/workflows/catalog-optimized-worker.yml",
            ".github/workflows/catalog-component-worker.yml",
        )
    )
    assert 'cache: ""' not in combined
    assert 'cache: "pip"' not in run
    assert 'cache-dependency-path: "requirements/catalog-recipe-worker.lock"' not in run
    component_worker = Path(
        ".github/workflows/catalog-component-worker.yml"
    ).read_text(encoding="utf-8")
    assert "requirements/catalog-optimized.lock" in component_worker
    assert "uv pip install --system --require-hashes" in component_worker
    assert "PYTHONPATH: ${{ github.workspace }}/.." in component_worker
    assert "pip install --no-deps -e ." not in component_worker
    assert "--component-schedule" in component_worker
    assert "total_component_shards" in component_worker
    assert "fromJSON(needs.plan.outputs.component_matrix)" in run
    assert "component_schedule.json" in component_worker
    assert 'runtime-fragments/sp500-runtime-fragment-$dataset_id' in component_worker
    assert 'gh run download "$RUNTIME_FRAGMENT_RUN_ID"' in component_worker
    assert 'fragment_names+=(\n              --name' in component_worker
    assert 'runtime/train_snapshot_1993_2010/$dataset_id.parquet' in component_worker
    assert "inputs.component_store_run_id == ''" in run
    resume_gate = (
        "always() && needs.plan.result == 'success' && "
        "needs.plan.outputs.pending_recipe_count != '0' && "
        "(inputs.component_store_run_id != '' || "
        "needs.merge_components.result == 'success')"
    )
    assert run.count(resume_gate) == 3
    assert (
        "always() && needs.plan.result == 'success' && "
        "needs.reduce.result == 'success'"
        in run
    )

    verify_only = Path(
        ".github/workflows/catalog-optimized-verify-only.yml"
    ).read_text(encoding="utf-8")
    assert "optimized_result_run_id" in verify_only
    assert "python -m scripts.verify_sp500_optimized_run" in verify_only
    assert "if: ${{ always() }}" in verify_only
    assert _RESULT_SCHEMA.names == ["strategy_id", "result_json"]


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
