"""Build one deterministic partition of the global SP500 component store."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token
from aurora.infra.sp500_megarun.catalog_component_store import ComponentStoreWriter
from aurora.infra.sp500_megarun.catalog_component_inventory import (
    collect_unique_components,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_scheduler import CatalogComponentScheduleV1
from aurora.infra.sp500_megarun.catalog_resources import (
    ResourceUsageSnapshot,
    resource_usage_delta,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
    runtime_dataset_ids_for_lane,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_fragments,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    feature_frame_to_decisions,
    load_train_total_return_ledger,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.strategy_catalog import verify_strategy_catalog_directory


_PROCESS_EVALUATOR: TrainLaneEvaluator | None = None
_PROCESS_LEDGER_INDEX: Any = None
_PROCESS_SEARCH_END: str | None = None


def _initialize_component_process(
    snapshot: str,
    expected_manifest_sha256: str,
    expected_spy_sha256: str,
    default_configurations: dict[str, dict[str, Any]],
    baseline_feature_dirs: dict[str, str],
    search_end: str,
) -> None:
    """Load immutable train inputs once for every persistent worker process."""

    global _PROCESS_EVALUATOR, _PROCESS_LEDGER_INDEX, _PROCESS_SEARCH_END
    verify_numeric_runtime_environment()
    snapshot_path = Path(snapshot)
    ledger = load_train_total_return_ledger(
        snapshot_path,
        allowed_end=search_end,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_spy_sha256=expected_spy_sha256,
    )
    _PROCESS_LEDGER_INDEX = ledger.index
    _PROCESS_SEARCH_END = search_end
    _PROCESS_EVALUATOR = TrainLaneEvaluator(
        snapshot_path,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_spy_sha256=expected_spy_sha256,
        default_configurations=default_configurations,
        baseline_feature_dirs={
            name: Path(path) for name, path in baseline_feature_dirs.items()
        },
    )


def _build_component_task(
    component: dict[str, Any],
) -> tuple[str, np.ndarray, float]:
    if (
        _PROCESS_EVALUATOR is None
        or _PROCESS_LEDGER_INDEX is None
        or _PROCESS_SEARCH_END is None
    ):
        raise RuntimeError("COMPONENT_PROCESS_NOT_INITIALIZED")
    started = time.perf_counter()
    frame = _PROCESS_EVALUATOR(
        str(component["lane_id"]),
        dict(component["configuration"]),
    )
    decisions = feature_frame_to_decisions(
        frame,
        allowed_end=_PROCESS_SEARCH_END,
    ).reindex(_PROCESS_LEDGER_INDEX)
    values = decisions.fillna(0.0).to_numpy(dtype=np.int8)
    return (
        str(component["configuration_sha256"]),
        values,
        time.perf_counter() - started,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--selected-config", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--runtime-source-run-id", required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--component-schedule", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--component-shard-index", type=int, required=True)
    parser.add_argument("--total-component-shards", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    resource_started = ResourceUsageSnapshot.capture()
    numeric_runtime = verify_numeric_runtime_environment()
    plan = verify_catalog_plan_token(
        args.run_plan,
        admission_token_sha256=args.admission_token,
    )
    resolved = RunOptimizationContractV1.model_validate_json(
        args.resolved_contract.read_text("utf-8")
    )
    if resolved.contract_sha256 != plan.contract_sha256:
        raise SystemExit("COMPONENT_CONTRACT_PLAN_MISMATCH")
    if not 0 <= args.component_shard_index < args.total_component_shards <= 360:
        raise SystemExit("COMPONENT_SHARD_INVALID")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract,
        data_contract,
    )
    receipt = verify_strategy_catalog_directory(args.catalog_dir)
    if receipt["validation_opened"] or receipt["locked_opened"]:
        raise SystemExit("COMPONENT_CATALOG_BOUNDARY_OPEN")
    snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    default_configurations = default_lane_configurations(feature_contract)
    baseline_feature_dirs = {
        name: str(args.runtime_input_pack / f"baseline_{name}")
        for name in ("price", "market", "macro")
    }
    catalog_rows = [
        json.loads(line)
        for line in (args.catalog_dir / "catalog.jsonl").read_text("utf-8").splitlines()
        if line
    ]
    selected_rows = json.loads(args.selected_config.read_text("utf-8"))
    if not isinstance(selected_rows, list):
        raise SystemExit("COMPONENT_SELECTED_CONFIG_INVALID")
    all_components = collect_unique_components(catalog_rows, selected_rows)
    schedule = CatalogComponentScheduleV1.model_validate_json(
        args.component_schedule.read_text("utf-8")
    )
    if len(schedule.shards) != args.total_component_shards:
        raise SystemExit("COMPONENT_SCHEDULE_SHARD_COUNT_INVALID")
    scheduled_ids = [
        component_id
        for shard in schedule.shards
        for component_id in shard.component_ids
    ]
    all_by_id = {
        str(component["configuration_sha256"]): component
        for component in all_components
    }
    if len(scheduled_ids) != len(set(scheduled_ids)) or set(scheduled_ids) != set(all_by_id):
        raise SystemExit("COMPONENT_SCHEDULE_COVERAGE_INVALID")
    shard = schedule.shards[args.component_shard_index]
    if shard.shard_index != args.component_shard_index:
        raise SystemExit("COMPONENT_SCHEDULE_INDEX_INVALID")
    assigned = tuple(all_by_id[component_id] for component_id in shard.component_ids)
    required_datasets = {
        dataset_id
        for component in assigned
        for dataset_id in runtime_dataset_ids_for_lane(str(component["lane_id"]))
    }
    runtime_fragment = verify_runtime_input_fragments(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            campaign
        ),
        required_dataset_ids=required_datasets,
        expected_runtime_source_run_id=args.runtime_source_run_id,
    )
    writer = ComponentStoreWriter(
        args.output_dir,
        data_snapshot_sha256=resolved.science.data_snapshot_sha256,
        evaluator_sha256=resolved.science.evaluator_sha256,
        session_count=len(ledger),
    )
    component_profiles: dict[str, dict[str, object]] = {}
    shard_started = time.perf_counter()
    process_count = plan.component_processes_per_worker
    initializer_args = (
        str(snapshot),
        campaign.train_snapshot_manifest_sha256,
        campaign.train_spy_sha256,
        default_configurations,
        baseline_feature_dirs,
        campaign.search_end,
    )
    if process_count == 1:
        _initialize_component_process(*initializer_args)
        built_components = [_build_component_task(component) for component in assigned]
    else:
        with ProcessPoolExecutor(
            max_workers=process_count,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_component_process,
            initargs=initializer_args,
        ) as executor:
            built_components = list(
                executor.map(
                    _build_component_task,
                    assigned,
                    chunksize=plan.block_size,
                )
            )
    for component, (component_id, values, duration) in zip(
        assigned,
        built_components,
        strict=True,
    ):
        if component_id != component["configuration_sha256"]:
            raise SystemExit("COMPONENT_PROCESS_ORDER_INVALID")
        writer.add(component_id, values)
        profile_key = (
            f'{component["lane_id"]}:{component["configuration_sha256"]}'
        )
        component_profiles[profile_key] = {
            "lane_id": component["lane_id"],
            "configuration_sha256": component["configuration_sha256"],
            "duration_samples": [duration],
            "sample_count": 1,
            "p50_seconds": duration,
            "p90_seconds": duration,
            "p95_seconds": duration,
            "p99_seconds": duration,
            "physical_seconds": duration,
        }
    shard_seconds = time.perf_counter() - shard_started
    manifest = writer.commit()
    resource_usage = resource_usage_delta(
        resource_started,
        ResourceUsageSnapshot.capture(),
    )
    (args.output_dir / "component_performance.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "component_shard_index": args.component_shard_index,
                "component_profiles": component_profiles,
                "physical_component_builds": len(component_profiles),
                "component_processes_per_worker": process_count,
                "runtime_input_bytes": int(runtime_fragment["assembled_bytes"]),
                "runtime_parent_total_bytes": int(
                    runtime_fragment["parent_total_bytes"]
                ),
                "runtime_required_dataset_ids": list(
                    runtime_fragment["required_dataset_ids"]
                ),
                "physical_component_seconds": sum(
                    float(row["physical_seconds"])
                    for row in component_profiles.values()
                ),
                "shard_seconds": shard_seconds,
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
    (args.output_dir / "receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "component_shard_index": args.component_shard_index,
                "total_component_shards": args.total_component_shards,
                "component_count": manifest.component_count,
                "all_component_count": len(all_components),
                "component_schedule_sha256": schedule.plan_sha256,
                "manifest_sha256": manifest.manifest_sha256,
                "numeric_runtime_profile_sha256": numeric_runtime["profile_sha256"],
                "component_processes_per_worker": process_count,
                "shard_seconds": shard_seconds,
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
