"""Evaluate catalog recipes from the immutable global component store."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import (
    verify_catalog_worker_admission,
)
from aurora.infra.sp500_megarun.catalog_component_store import CatalogComponentStore
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_resume import CatalogResumeWorkManifestV1
from aurora.infra.sp500_megarun.catalog_resources import (
    ResourceUsageSnapshot,
    resource_usage_delta,
)
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    candidate_fingerprints,
    load_train_total_return_ledger,
)
from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    normalize_scientific_result,
)
from aurora.infra.sp500_megarun.dehb_objective import (
    candidate_rank_key,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    configuration_sha256,
    verify_strategy_catalog_directory,
)
from scripts.run_sp500_strategy_catalog_shard import (
    FULL_FIDELITY,
    FULL_YEARS,
    compose_signals,
    merge_weekly_winning_or_positive_metrics,
)
from scripts.compile_sp500_catalog_recipes import verify_recipe_dag_artifacts


_RESULT_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("result_json", pa.string()),
    ]
)

_PROCESS_STORE: CatalogComponentStore | None = None
_PROCESS_LEDGER: pd.DataFrame | None = None
_PROCESS_SEARCH_END: str | None = None
_PROCESS_OBJECTIVE: FastTrainObjective | None = None


def _signals_for_components(
    components: list[dict[str, object]],
    *,
    store: CatalogComponentStore,
    index: pd.Index,
) -> list[pd.Series]:
    signals: list[pd.Series] = []
    for component in components:
        values = store.get(str(component["configuration_sha256"]))
        signal = pd.Series(values.astype(float), index=index, dtype=float)
        signals.append(signal.mask(signal == 0.0))
    return signals


def _evaluate(
    *,
    lane_id: str,
    configuration: dict[str, object],
    decisions: pd.Series,
    ledger: pd.DataFrame,
    search_end: str,
    objective: FastTrainObjective | None = None,
) -> tuple[dict[str, object], str]:
    strategy_fingerprint, position_fingerprint = candidate_fingerprints(
        lane_id,
        configuration,
        decisions,
    )
    active_objective = objective or FastTrainObjective(
        ledger,
        target_years=FULL_YEARS,
        allowed_end=search_end,
    )
    realized = active_objective.score(decisions)
    score = realized.score
    archive_key = candidate_rank_key(score)
    config_sha256 = hashlib.sha256(
        json.dumps(
            configuration,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    result = dict(
        normalize_scientific_result(
            {
                "fitness": float(score.dehb_fitness),
                "cost": float(FULL_FIDELITY),
                "info": {
                    "lane_id": lane_id,
                    "fidelity": FULL_FIDELITY,
                    "target_years": list(FULL_YEARS),
                    "config": dict(configuration),
                    "config_sha256": config_sha256,
                    "strategy_fingerprint": strategy_fingerprint,
                    "position_fingerprint": position_fingerprint,
                    "train_feasible": score.feasible,
                    "failed_years": list(score.failed_years),
                    "annual_returns": {
                        str(year): asdict(row)
                        for year, row in score.annual_returns.items()
                    },
                    "annualized_strategy_return": score.annualized_strategy_return,
                    "annualized_spy_return": score.annualized_spy_return,
                    "annualized_alpha": score.annualized_alpha,
                    "weekly_spy_beat_rate": score.weekly_spy_beat_rate,
                    "weeks_beating_spy": score.weeks_beating_spy,
                    "week_count": score.week_count,
                    "archive_key": list(archive_key),
                    "objective_runtime_seconds": 0.0,
                    "full_fidelity": True,
                    "validation_opened": False,
                    "locked_opened": False,
                },
            }
        )
    )
    result["info"] = merge_weekly_winning_or_positive_metrics(
        result["info"],
        realized.weekly_calendar_metrics,
    )
    return result, position_fingerprint


def _initialize_recipe_process(
    component_store: str,
    data_snapshot_sha256: str,
    evaluator_sha256: str,
    snapshot: str,
    search_end: str,
    snapshot_manifest_sha256: str,
    spy_sha256: str,
) -> None:
    """Load immutable mmap and train-only ledger once per persistent process."""

    global _PROCESS_LEDGER, _PROCESS_OBJECTIVE, _PROCESS_SEARCH_END, _PROCESS_STORE
    _PROCESS_STORE = CatalogComponentStore.open(
        Path(component_store),
        expected_data_snapshot_sha256=data_snapshot_sha256,
        expected_evaluator_sha256=evaluator_sha256,
    )
    _PROCESS_LEDGER = load_train_total_return_ledger(
        Path(snapshot),
        allowed_end=search_end,
        expected_manifest_sha256=snapshot_manifest_sha256,
        expected_spy_sha256=spy_sha256,
    )
    _PROCESS_SEARCH_END = search_end
    _PROCESS_OBJECTIVE = FastTrainObjective(
        _PROCESS_LEDGER,
        target_years=FULL_YEARS,
        allowed_end=search_end,
    )


def _evaluate_catalog_row(row: dict[str, Any]) -> dict[str, object]:
    if (
        _PROCESS_STORE is None
        or _PROCESS_LEDGER is None
        or _PROCESS_OBJECTIVE is None
        or _PROCESS_SEARCH_END is None
    ):
        raise RuntimeError("RECIPE_PROCESS_NOT_INITIALIZED")
    started = time.perf_counter()
    signals = _signals_for_components(
        list(row["components"]),
        store=_PROCESS_STORE,
        index=_PROCESS_LEDGER.index,
    )
    component_load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    decisions = compose_signals(signals, dict(row["composition"]))
    composition_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result, position_fingerprint = _evaluate(
        lane_id=str(row["strategy_id"]),
        configuration={
            "scientific_recipe_sha256": row["scientific_recipe_sha256"]
        },
        decisions=decisions,
        ledger=_PROCESS_LEDGER,
        search_end=_PROCESS_SEARCH_END,
        objective=_PROCESS_OBJECTIVE,
    )
    objective_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result_json = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
    )
    serialization_seconds = time.perf_counter() - started
    return {
        "strategy_id": row["strategy_id"],
        "scientific_recipe_sha256": row["scientific_recipe_sha256"],
        "strategy_kind": row["strategy_kind"],
        "position_fingerprint": position_fingerprint,
        "result_json": result_json,
        "_stage_seconds": {
            "component_load": component_load_seconds,
            "composition": composition_seconds,
            "objective": objective_seconds,
            "serialization": serialization_seconds,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--selected-config", type=Path, required=True)
    parser.add_argument("--component-store", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--resume-work-manifest", type=Path, required=True)
    parser.add_argument("--recipe-dag", type=Path, required=True)
    parser.add_argument("--recipe-dag-manifest", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    resource_started = ResourceUsageSnapshot.capture()
    numeric_runtime = verify_numeric_runtime_environment()
    plan = verify_catalog_worker_admission(
        args.run_plan,
        admission_token_sha256=args.admission_token,
        shard_index=args.shard_index,
        total_shards=args.total_shards,
    )
    resolved = RunOptimizationContractV1.model_validate_json(
        args.resolved_contract.read_text("utf-8")
    )
    if resolved.contract_sha256 != plan.contract_sha256:
        raise SystemExit("RECIPE_CONTRACT_PLAN_MISMATCH")
    work_manifest = CatalogResumeWorkManifestV1.model_validate_json(
        args.resume_work_manifest.read_text("utf-8")
    )
    work_identity = work_manifest.model_dump(
        mode="python",
        exclude={"manifest_sha256"},
    )
    if (
        canonical_sha256(work_identity) != work_manifest.manifest_sha256
        or work_manifest.manifest_sha256 != plan.work_manifest_sha256
        or len(work_manifest.pending_strategy_ids) != plan.pending_recipe_count
        or len(work_manifest.cached_strategy_ids) != plan.cached_recipe_count
        or work_manifest.active_workers != plan.active_workers
    ):
        raise SystemExit("RECIPE_WORK_MANIFEST_INVALID")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    receipt = verify_strategy_catalog_directory(args.catalog_dir)
    if receipt["validation_opened"] or receipt["locked_opened"]:
        raise SystemExit("RECIPE_CATALOG_BOUNDARY_OPEN")
    store = CatalogComponentStore.open(
        args.component_store,
        expected_data_snapshot_sha256=resolved.science.data_snapshot_sha256,
        expected_evaluator_sha256=resolved.science.evaluator_sha256,
    )
    snapshot = args.component_store / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    rows = [
        json.loads(line)
        for line in (args.catalog_dir / "catalog.jsonl").read_text("utf-8").splitlines()
        if line
    ]
    dag_manifest = verify_recipe_dag_artifacts(
        args.recipe_dag,
        args.recipe_dag_manifest,
    )
    dag_table = pq.read_table(args.recipe_dag)
    dag_strategy_ids = dag_table.column("strategy_id").to_pylist()
    dag_science_ids = dag_table.column("scientific_recipe_sha256").to_pylist()
    dag_index = dict(zip(dag_strategy_ids, dag_science_ids, strict=True))
    if (
        int(dag_manifest["recipe_count"]) != len(rows)
        or len(dag_index) != len(rows)
        or any(
            dag_index.get(str(row["strategy_id"]))
            != str(row["scientific_recipe_sha256"])
            for row in rows
        )
    ):
        raise SystemExit("RECIPE_DAG_CATALOG_MISMATCH")
    by_strategy_id = {str(row["strategy_id"]): row for row in rows}
    assigned_ids = work_manifest.assign(args.shard_index)
    try:
        assigned = [by_strategy_id[strategy_id] for strategy_id in assigned_ids]
    except KeyError as exc:
        raise SystemExit("RECIPE_WORK_MANIFEST_STRATEGY_UNKNOWN") from exc
    process_count = plan.processes_per_worker
    initializer_args = (
        str(args.component_store),
        resolved.science.data_snapshot_sha256,
        resolved.science.evaluator_sha256,
        str(snapshot),
        campaign.search_end,
        campaign.train_snapshot_manifest_sha256,
        campaign.train_spy_sha256,
    )
    if process_count == 1:
        _initialize_recipe_process(*initializer_args)
        output = [_evaluate_catalog_row(row) for row in assigned]
    else:
        with ProcessPoolExecutor(
            max_workers=process_count,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_recipe_process,
            initargs=initializer_args,
        ) as executor:
            output = list(
                executor.map(
                    _evaluate_catalog_row,
                    assigned,
                    chunksize=plan.block_size,
                )
            )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result_path = args.output_dir / "results.parquet"
    scientific_stage_seconds = {
        name: sum(
            float(row["_stage_seconds"][name])
            for row in output
        )
        for name in (
            "component_load",
            "composition",
            "objective",
            "serialization",
        )
    }
    write_started = time.perf_counter()
    pq.write_table(
        pa.Table.from_pylist(output, schema=_RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
    )
    scientific_stage_seconds["write"] = time.perf_counter() - write_started
    selected_output: list[dict[str, object]] = []
    if args.shard_index == 0:
        selected_objective = FastTrainObjective(
            ledger,
            target_years=FULL_YEARS,
            allowed_end=campaign.search_end,
        )
        selected_rows = json.loads(args.selected_config.read_text("utf-8"))
        for selected in selected_rows:
            lane_id = str(selected["lane_id"])
            configuration = dict(selected["configuration"])
            key = configuration_sha256(lane_id, configuration)
            signal = pd.Series(
                store.get(key).astype(float),
                index=ledger.index,
                dtype=float,
            )
            decisions = signal.mask(signal == 0.0)
            result, _ = _evaluate(
                lane_id=lane_id,
                configuration=configuration,
                decisions=decisions,
                ledger=ledger,
                search_end=campaign.search_end,
                objective=selected_objective,
            )
            selected_output.append(
                {
                    "source_strategy_key": selected["source_strategy_key"],
                    "lane_id": lane_id,
                    "configuration": configuration,
                    "result": result,
                }
            )
        (args.output_dir / "selected_results.jsonl").write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in selected_output
            ),
            "utf-8",
        )
    bytes_written = result_path.stat().st_size
    resource_usage = resource_usage_delta(
        resource_started,
        ResourceUsageSnapshot.capture(),
    )
    (args.output_dir / "receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "shard_index": args.shard_index,
                "total_shards": args.total_shards,
                "strategy_count": len(output),
                "selected_strategy_count": len(selected_output),
                "unique_position_count": len(
                    {row["position_fingerprint"] for row in output}
                ),
                "result_bytes": bytes_written,
                "result_bytes_per_recipe": (
                    bytes_written / len(output) if output else 0.0
                ),
                "result_sha256": sha256_file(result_path),
                "science_identity_sha256": canonical_sha256(resolved.science),
                "catalog_manifest_sha256": resolved.science.catalog_manifest_sha256,
                "work_manifest_sha256": work_manifest.manifest_sha256,
                "recipe_dag_manifest_sha256": dag_manifest["manifest_sha256"],
                "evaluation_origin": "physical",
                "component_manifest_sha256": store.manifest.manifest_sha256,
                "numeric_runtime_profile_sha256": numeric_runtime["profile_sha256"],
                "physical_component_builds": 0,
                "component_cache_hits": sum(len(row["components"]) for row in assigned),
                "processes_per_worker": process_count,
                "scientific_stage_seconds": scientific_stage_seconds,
                **resource_usage,
                "validation_opened": False,
                "locked_opened": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
