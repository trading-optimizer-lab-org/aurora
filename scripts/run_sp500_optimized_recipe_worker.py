"""Evaluate catalog recipes from the immutable global component store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_admission import (
    verify_catalog_worker_admission,
)
from aurora.infra.sp500_megarun.catalog_component_store import CatalogComponentStore
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    PreparedLaneCandidate,
    candidate_fingerprints,
    load_train_total_return_ledger,
    score_prepared_lane_candidate,
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
    weekly_winning_or_positive_metrics,
)


_RESULT_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("scientific_recipe_sha256", pa.string()),
        ("strategy_kind", pa.string()),
        ("position_fingerprint", pa.string()),
        ("result_json", pa.string()),
    ]
)


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
) -> tuple[dict[str, object], str]:
    strategy_fingerprint, position_fingerprint = candidate_fingerprints(
        lane_id,
        configuration,
        decisions,
    )
    prepared = PreparedLaneCandidate(
        lane_id=lane_id,
        configuration=configuration,
        fidelity=FULL_FIDELITY,
        target_years=FULL_YEARS,
        decisions=decisions,
        strategy_fingerprint=strategy_fingerprint,
        position_fingerprint=position_fingerprint,
    )
    result = dict(
        score_prepared_lane_candidate(
            prepared,
            ledger=ledger,
            fidelity_years={FULL_FIDELITY: FULL_YEARS},
            allowed_end=search_end,
        )
    )
    from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions

    realized = score_ledger_decisions(
        ledger,
        decisions,
        target_years=FULL_YEARS,
        allowed_end=search_end,
    )
    result["info"] = merge_weekly_winning_or_positive_metrics(
        result["info"],
        weekly_winning_or_positive_metrics(
            realized.strategy_returns,
            realized.spy_returns,
        ),
    )
    return result, position_fingerprint


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--selected-config", type=Path, required=True)
    parser.add_argument("--component-store", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
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
    assigned = rows[args.shard_index :: args.total_shards]
    output: list[dict[str, object]] = []
    for row in assigned:
        signals = _signals_for_components(
            row["components"],
            store=store,
            index=ledger.index,
        )
        decisions = compose_signals(signals, row["composition"])
        configuration = {
            "scientific_recipe_sha256": row["scientific_recipe_sha256"]
        }
        result, position_fingerprint = _evaluate(
            lane_id=row["strategy_id"],
            configuration=configuration,
            decisions=decisions,
            ledger=ledger,
            search_end=campaign.search_end,
        )
        output.append(
            {
                "strategy_id": row["strategy_id"],
                "scientific_recipe_sha256": row["scientific_recipe_sha256"],
                "strategy_kind": row["strategy_kind"],
                "position_fingerprint": position_fingerprint,
                "result_json": json.dumps(
                    result,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result_path = args.output_dir / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(output, schema=_RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
    )
    selected_output: list[dict[str, object]] = []
    if args.shard_index == 0:
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
                "component_manifest_sha256": store.manifest.manifest_sha256,
                "physical_component_builds": 0,
                "component_cache_hits": sum(len(row["components"]) for row in assigned),
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
