"""Evaluate catalog recipes from the immutable global component store."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
from collections.abc import Sequence
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
from aurora.infra.sp500_megarun.catalog_recovery_blocks import resolve_recovery_block
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeWorkManifestV1,
    scientific_result_sha256,
)
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

_PROCESS_STORE: Any = None
_PROCESS_LEDGER: pd.DataFrame | None = None
_PROCESS_SEARCH_END: str | None = None
_PROCESS_OBJECTIVE: FastTrainObjective | None = None


def _write_resume_microshard(
    root: Path,
    *,
    ordinal: int,
    rows: list[dict[str, object]],
    science_identity_sha256: str,
    catalog_manifest_sha256: str,
) -> None:
    """Commit one immutable recovery unit before the worker can lose it."""

    if not rows:
        return
    target = Path(root) / f"part-{ordinal:05d}"
    target.mkdir(parents=True, exist_ok=False)
    result_path = target / "results.parquet"
    temporary_result = target / "results.parquet.tmp"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=_RESULT_SCHEMA),
        temporary_result,
        compression="zstd",
        use_dictionary=True,
    )
    temporary_result.replace(result_path)
    receipt = {
        "schema_version": 1,
        "partial": True,
        "strategy_count": len(rows),
        "result_sha256": sha256_file(result_path),
        "science_identity_sha256": science_identity_sha256,
        "catalog_manifest_sha256": catalog_manifest_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    temporary_receipt = target / "receipt.json.tmp"
    temporary_receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    temporary_receipt.replace(target / "receipt.json")


def _signals_for_components(
    components: list[dict[str, object]],
    *,
    store: Any,
    index: pd.Index,
) -> list[pd.Series]:
    signals: list[pd.Series] = []
    for component in components:
        values = store.get(str(component["configuration_sha256"]))
        signal = pd.Series(values.astype(float), index=index, dtype=float)
        signals.append(signal.mask(signal == 0.0))
    return signals


class _ExactComponentPayload:
    """Read several exact mmap bundles without copying them into one matrix."""

    def __init__(self, stores: tuple[CatalogComponentStore, ...]) -> None:
        if not stores:
            raise ValueError("COMPONENT_PAYLOAD_INCOMPLETE")
        entries: dict[str, CatalogComponentStore] = {}
        bundle_manifests: list[str] = []
        for store in stores:
            wrapper_path = store.root / "component_bundle_manifest.json"
            try:
                wrapper = json.loads(wrapper_path.read_text("utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("COMPONENT_BUNDLE_MANIFEST_INVALID") from exc
            wrapper_identity = {
                key: value
                for key, value in wrapper.items()
                if key != "manifest_sha256"
            }
            if (
                wrapper.get("schema_version") != "1"
                or wrapper.get("component_store_manifest_sha256")
                != store.manifest.manifest_sha256
                or wrapper.get("validation_opened") is not False
                or wrapper.get("locked_opened") is not False
                or canonical_sha256(wrapper_identity)
                != wrapper.get("manifest_sha256")
            ):
                raise ValueError("COMPONENT_BUNDLE_MANIFEST_INVALID")
            source_ids = {
                str(item.get("source_configuration_sha256"))
                for item in wrapper.get("components", ())
                if isinstance(item, dict)
            }
            manifest_ids = {
                entry.component_id for entry in store.manifest.entries
            }
            if source_ids != manifest_ids:
                raise ValueError("COMPONENT_BUNDLE_STORE_COVERAGE_INVALID")
            for component_id in sorted(manifest_ids):
                if component_id in entries:
                    raise ValueError("COMPONENT_PAYLOAD_DUPLICATE")
                entries[component_id] = store
            bundle_manifests.append(str(wrapper["manifest_sha256"]))
        self._entries = entries
        self.manifest = SimpleNamespace(
            manifest_sha256=canonical_sha256(
                {
                    "schema_version": "exact-component-payload-v1",
                    "bundle_manifest_sha256": tuple(sorted(bundle_manifests)),
                    "component_ids": tuple(sorted(entries)),
                }
            )
        )

    def get(self, component_id: str):
        store = self._entries.get(str(component_id))
        if store is None:
            raise KeyError(component_id)
        return store.get(component_id)


def _open_exact_component_payload(
    root: Path,
    *,
    data_snapshot_sha256: str,
    evaluator_sha256: str,
) -> CatalogComponentStore | _ExactComponentPayload:
    payload_root = Path(root)
    if (payload_root / "manifest.json").is_file():
        return CatalogComponentStore.open(
            payload_root,
            expected_data_snapshot_sha256=data_snapshot_sha256,
            expected_evaluator_sha256=evaluator_sha256,
        )
    store_roots = tuple(
        sorted(
            {
                path.parent
                for path in payload_root.rglob("manifest.json")
                if (path.parent / "signals.npy").is_file()
            },
            key=lambda path: path.relative_to(payload_root).as_posix(),
        )
    )
    stores = tuple(
        CatalogComponentStore.open(
            store_root,
            expected_data_snapshot_sha256=data_snapshot_sha256,
            expected_evaluator_sha256=evaluator_sha256,
        )
        for store_root in store_roots
    )
    return _ExactComponentPayload(stores)


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
    _PROCESS_STORE = _open_exact_component_payload(
        Path(component_store),
        data_snapshot_sha256=data_snapshot_sha256,
        evaluator_sha256=evaluator_sha256,
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
    parser.add_argument("--runtime-input-pack", type=Path)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--resume-work-manifest", type=Path, required=True)
    parser.add_argument("--recipe-dag", type=Path, required=True)
    parser.add_argument("--recipe-dag-manifest", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--payload-descriptor", type=Path)
    parser.add_argument("--assignment-file", type=Path)
    parser.add_argument("--checkpoint-policy", type=Path)
    parser.add_argument("--checkpoint-slot-index", type=int)
    parser.add_argument("--checkpoint-slot-count", type=int)
    parser.add_argument("--previous-checkpoint-receipt", type=Path)
    parser.add_argument("--processes-per-worker-override", type=int)
    parser.add_argument("--block-size-override", type=int)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    scientific_wall_started = time.perf_counter()
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
    store = _open_exact_component_payload(
        args.component_store,
        data_snapshot_sha256=resolved.science.data_snapshot_sha256,
        evaluator_sha256=resolved.science.evaluator_sha256,
    )
    runtime_input_pack = args.runtime_input_pack or args.component_store
    snapshot = runtime_input_pack / "train_snapshot_1993_2010"
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
    payload_descriptor: dict[str, object] | None = None
    checkpoint_slot_index = 1
    checkpoint_slot_count = 1
    assigned_ids = work_manifest.assign(args.shard_index)
    if args.payload_descriptor is not None or args.assignment_file is not None:
        if (
            args.payload_descriptor is None
            or args.assignment_file is None
            or args.checkpoint_slot_index is None
            or args.checkpoint_slot_count is None
        ):
            raise SystemExit("RECIPE_EXACT_PAYLOAD_ARGUMENTS_INCOMPLETE")
        try:
            payload_descriptor = json.loads(
                args.payload_descriptor.read_text("utf-8")
            )
            assignment_payload = json.loads(args.assignment_file.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit("RECIPE_EXACT_PAYLOAD_INVALID") from exc
        if not isinstance(payload_descriptor, dict) or not isinstance(
            assignment_payload, dict
        ):
            raise SystemExit("RECIPE_EXACT_PAYLOAD_INVALID")
        checkpoint_slot_index = int(args.checkpoint_slot_index)
        checkpoint_slot_count = int(args.checkpoint_slot_count)
        if (
            payload_descriptor.get("worker_id") != args.shard_index
            or payload_descriptor.get("checkpoint_slot_count")
            != checkpoint_slot_count
            or checkpoint_slot_count not in (1, 2, 4, 8)
            or not 1 <= checkpoint_slot_index <= checkpoint_slot_count
        ):
            raise SystemExit("RECIPE_CHECKPOINT_BINDING_INVALID")
        if set(assignment_payload) != {
            "schema_version",
            "worker_id",
            "strategy_ids",
            "expected_strategy_manifest_sha256",
        }:
            raise SystemExit("RECIPE_ASSIGNMENT_SCHEMA_INVALID")
        assignment_ids = tuple(str(value) for value in assignment_payload["strategy_ids"])
        assignment_identity = {
            "schema_version": "1",
            "worker_id": args.shard_index,
            "strategy_ids": assignment_ids,
        }
        expected_strategy_manifest_sha256 = canonical_sha256(assignment_identity)
        if (
            assignment_payload["schema_version"] != "1"
            or assignment_payload["worker_id"] != args.shard_index
            or assignment_ids != tuple(sorted(set(assignment_ids)))
            or assignment_payload["expected_strategy_manifest_sha256"]
            != expected_strategy_manifest_sha256
            or payload_descriptor.get("expected_strategy_manifest_sha256")
            != expected_strategy_manifest_sha256
            or payload_descriptor.get("expected_strategy_count")
            != len(assignment_ids)
            or not set(assignment_ids).issubset(work_manifest.pending_strategy_ids)
        ):
            raise SystemExit("RECIPE_ASSIGNMENT_BINDING_INVALID")
        start = (len(assignment_ids) * (checkpoint_slot_index - 1)) // checkpoint_slot_count
        stop = (len(assignment_ids) * checkpoint_slot_index) // checkpoint_slot_count
        assigned_ids = assignment_ids[start:stop]
        if not assigned_ids:
            raise SystemExit("RECIPE_CHECKPOINT_SEGMENT_EMPTY")
    recovery_block_id = None
    if args.checkpoint_policy is not None:
        try:
            checkpoint_policy = json.loads(args.checkpoint_policy.read_text("utf-8"))
            if not isinstance(checkpoint_policy, dict):
                raise ValueError("RECOVERY_BLOCK_POLICY_INVALID")
            recovery_block_id = resolve_recovery_block(
                checkpoint_policy, science_sha256=canonical_sha256(resolved.science),
                worker_id=args.shard_index, slot_index=checkpoint_slot_index,
                strategy_ids=assigned_ids,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise SystemExit("RECIPE_RECOVERY_BLOCK_INVALID") from exc
    try:
        assigned = [by_strategy_id[strategy_id] for strategy_id in assigned_ids]
    except KeyError as exc:
        raise SystemExit("RECIPE_WORK_MANIFEST_STRATEGY_UNKNOWN") from exc
    process_count = (
        args.processes_per_worker_override
        if args.processes_per_worker_override is not None
        else plan.processes_per_worker
    )
    block_size = (
        args.block_size_override
        if args.block_size_override is not None
        else plan.block_size
    )
    if (
        process_count < 1
        or process_count > plan.processes_per_worker
        or block_size < 1
        or block_size > plan.block_size
    ):
        raise SystemExit("RECIPE_OPERATIONAL_REPLAN_INVALID")
    initializer_args = (
        str(args.component_store),
        resolved.science.data_snapshot_sha256,
        resolved.science.evaluator_sha256,
        str(snapshot),
        campaign.search_end,
        campaign.train_snapshot_manifest_sha256,
        campaign.train_spy_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    recovery_root = args.output_dir / "recovery_microshards"
    recovery_root.mkdir(parents=True, exist_ok=False)
    recovery_chunk_size = 64
    science_identity_sha256 = canonical_sha256(resolved.science)
    evaluation_started = time.perf_counter()
    initialization_seconds = evaluation_started - scientific_wall_started
    output: list[dict[str, object]] = []

    def record(row: dict[str, object]) -> None:
        output.append(row)
        if len(output) % recovery_chunk_size == 0:
            _write_resume_microshard(
                recovery_root,
                ordinal=(len(output) // recovery_chunk_size) - 1,
                rows=output[-recovery_chunk_size:],
                science_identity_sha256=science_identity_sha256,
                catalog_manifest_sha256=resolved.science.catalog_manifest_sha256,
            )

    if process_count == 1:
        _initialize_recipe_process(*initializer_args)
        for row in assigned:
            record(_evaluate_catalog_row(row))
    else:
        with ProcessPoolExecutor(
            max_workers=process_count,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_recipe_process,
            initargs=initializer_args,
        ) as executor:
            for row in executor.map(
                _evaluate_catalog_row,
                assigned,
                chunksize=block_size,
            ):
                record(row)
    remainder = len(output) % recovery_chunk_size
    if remainder:
        _write_resume_microshard(
            recovery_root,
            ordinal=len(output) // recovery_chunk_size,
            rows=output[-remainder:],
            science_identity_sha256=science_identity_sha256,
            catalog_manifest_sha256=resolved.science.catalog_manifest_sha256,
        )
    evaluation_seconds = time.perf_counter() - evaluation_started
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
    selected_started = time.perf_counter()
    if args.shard_index == 0 and checkpoint_slot_index == 1:
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
    selected_seconds = time.perf_counter() - selected_started
    scientific_wall_seconds = time.perf_counter() - scientific_wall_started
    scientific_wall_stage_seconds = {
        "initialization": initialization_seconds,
        "evaluation": evaluation_seconds,
        "write": scientific_stage_seconds["write"],
        "selected_verification": selected_seconds,
    }
    attributed_seconds = sum(scientific_wall_stage_seconds.values())
    scientific_attribution_difference_ratio = (
        abs(scientific_wall_seconds - attributed_seconds)
        / scientific_wall_seconds
        if scientific_wall_seconds
        else 0.0
    )
    bytes_written = result_path.stat().st_size
    resource_usage = resource_usage_delta(
        resource_started,
        ResourceUsageSnapshot.capture(),
    )
    previous_checkpoint_receipt_sha256 = "0" * 64
    if args.previous_checkpoint_receipt is not None:
        if not args.previous_checkpoint_receipt.is_file():
            raise SystemExit("PREVIOUS_CHECKPOINT_RECEIPT_MISSING")
        previous_checkpoint_receipt_sha256 = sha256_file(
            args.previous_checkpoint_receipt
        )
    (args.output_dir / "receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "shard_index": args.shard_index,
                "total_shards": args.total_shards,
                "checkpoint_slot_index": checkpoint_slot_index,
                "checkpoint_slot_count": checkpoint_slot_count,
                "attempt_id": (
                    payload_descriptor.get("attempt_id")
                    if payload_descriptor is not None
                    else "legacy-attempt"
                ),
                "previous_checkpoint_receipt_sha256": (
                    previous_checkpoint_receipt_sha256
                ),
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
                "science_identity_sha256": science_identity_sha256,
                "recovery_block_id": recovery_block_id,
                "catalog_manifest_sha256": resolved.science.catalog_manifest_sha256,
                "work_manifest_sha256": work_manifest.manifest_sha256,
                "recipe_dag_manifest_sha256": dag_manifest["manifest_sha256"],
                "evaluation_origin": "physical",
                "component_manifest_sha256": store.manifest.manifest_sha256,
                "numeric_runtime_profile_sha256": numeric_runtime["profile_sha256"],
                "physical_component_builds": 0,
                "component_cache_hits": sum(len(row["components"]) for row in assigned),
                "processes_per_worker": process_count,
                "block_size": block_size,
                "scientific_stage_seconds": scientific_stage_seconds,
                "scientific_wall_stage_seconds": scientific_wall_stage_seconds,
                "scientific_wall_seconds": scientific_wall_seconds,
                "scientific_attribution_difference_ratio": (
                    scientific_attribution_difference_ratio
                ),
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
    receipt_path = args.output_dir / "receipt.json"
    receipt_sha256 = sha256_file(receipt_path)
    attempt_id = (
        str(payload_descriptor["attempt_id"])
        if payload_descriptor is not None
        else "legacy-attempt"
    )
    unit_attempts = [
        {
            "strategy_id": str(row["strategy_id"]),
            "attempt_id": attempt_id,
            "checkpoint_slot_index": checkpoint_slot_index,
            "result_sha256": scientific_result_sha256(
                json.loads(str(row["result_json"]))
            ),
        }
        for row in output
    ]
    pq.write_table(
        pa.Table.from_pylist(unit_attempts),
        args.output_dir / "unit_attempts.parquet",
        compression="zstd",
        use_dictionary=True,
    )
    resource_row = {
        "worker_id": args.shard_index,
        "attempt_id": attempt_id,
        "checkpoint_slot_index": checkpoint_slot_index,
        "scientific_wall_seconds": scientific_wall_seconds,
        "result_bytes": bytes_written,
        "strategy_count": len(output),
        "cpu_seconds": float(resource_usage.get("cpu_seconds", 0.0)),
        "peak_memory_bytes": int(resource_usage.get("peak_memory_bytes", 0)),
    }
    pq.write_table(
        pa.Table.from_pylist([resource_row]),
        args.output_dir / "resource_telemetry.parquet",
        compression="zstd",
        use_dictionary=True,
    )
    (args.output_dir / "resource_summary.json").write_text(
        json.dumps(resource_row, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    attempt_manifest = {
        "schema_version": "1",
        "recovery_block_id": recovery_block_id,
        "worker_id": args.shard_index,
        "attempt_id": attempt_id,
        "checkpoint_slot_index": checkpoint_slot_index,
        "checkpoint_slot_count": checkpoint_slot_count,
        "strategy_ids": tuple(str(row["strategy_id"]) for row in output),
        "result_sha256": sha256_file(result_path),
        "receipt_sha256": receipt_sha256,
        "previous_checkpoint_receipt_sha256": (
            previous_checkpoint_receipt_sha256
        ),
        "validation_opened": False,
        "locked_opened": False,
    }
    (args.output_dir / "shard_attempt_manifest.json").write_text(
        json.dumps(attempt_manifest, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    checkpoint_chain = {
        "schema_version": "1",
        "recovery_block_id": recovery_block_id,
        "worker_id": args.shard_index,
        "attempt_id": attempt_id,
        "slot_index": checkpoint_slot_index,
        "slot_count": checkpoint_slot_count,
        "previous_receipt_sha256": previous_checkpoint_receipt_sha256,
        "current_receipt_sha256": receipt_sha256,
        "completed_strategy_ids": attempt_manifest["strategy_ids"],
        "validation_opened": False,
        "locked_opened": False,
    }
    checkpoint_chain["chain_sha256"] = canonical_sha256(checkpoint_chain)
    (args.output_dir / "checkpoint_chain_manifest.json").write_text(
        json.dumps(checkpoint_chain, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    shutil.rmtree(recovery_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
