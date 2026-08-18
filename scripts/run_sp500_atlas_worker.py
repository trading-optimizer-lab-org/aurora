"""Evaluate one immutable Atlas ordinal shard in GitHub Actions.

The worker never claims work dynamically.  Its half-open ordinal interval is
fixed in the signed plan, which makes retries and final coverage checks simple.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import pandas as pd

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_objective import score_atlas_decisions
from aurora.infra.sp500_megarun.catalog_atlas_space import build_atlas_space, recipe_for_ordinal
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import load_and_validate_campaign_contract
from aurora.infra.sp500_megarun.dehb_lane_registry import TrainLaneEvaluator, default_lane_configurations
from aurora.infra.sp500_megarun.dehb_numeric_runtime import verify_numeric_runtime_environment
from aurora.infra.sp500_megarun.dehb_runtime_inputs import scientific_input_binding_sha256, verify_runtime_input_pack
from aurora.infra.sp500_megarun.dehb_worker import feature_frame_to_decisions, load_train_total_return_ledger
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract

try:
    from scripts.run_sp500_strategy_catalog_shard import compose_signals
except ModuleNotFoundError:
    from run_sp500_strategy_catalog_shard import compose_signals


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    return _sha256_file(path)


def _result_row(
    *,
    recipe: dict[str, object],
    scored: object,
    atlas_metrics: object,
    position_sha256: str,
    plan_sha256: str,
    shard_index: int,
) -> dict[str, object]:
    metrics = atlas_metrics
    payload: dict[str, object] = {
        "ordinal": int(recipe["ordinal"]),
        "raw_ordinal": int(recipe["raw_ordinal"]),
        "strategy_id": str(recipe["strategy_id"]),
        "scientific_recipe_sha256": str(recipe["scientific_recipe_sha256"]),
        "strategy_kind": str(recipe["strategy_kind"]),
        "components": list(recipe["components"]),
        "composition": dict(recipe["composition"]),
        "position_sha256": position_sha256,
        "positive_weeks": metrics.positive_weeks,
        "total_weeks": metrics.total_weeks,
        "positive_week_fraction": metrics.positive_week_fraction,
        "positive_months": metrics.positive_months,
        "total_months": metrics.total_months,
        "positive_month_fraction": metrics.positive_month_fraction,
        "joint_positive_above_spy_years": metrics.joint_positive_above_spy_years,
        "total_years": metrics.total_years,
        "joint_positive_above_spy_fraction": metrics.joint_positive_above_spy_fraction,
        "annual_rows": list(metrics.annual_rows),
        "annualized_strategy_return": float(scored.score.annualized_strategy_return),
        "annualized_alpha": float(scored.score.annualized_alpha),
        "weeks_beating_spy": int(scored.score.weeks_beating_spy),
        "week_count": int(scored.score.week_count),
        "plan_sha256": plan_sha256,
        "shard_index": shard_index,
        "evaluation_origin": "physical",
        "validation_opened": False,
        "locked_opened": False,
    }
    result_identity = canonical_sha256(payload)
    return {**payload, "result_sha256": result_identity}


def run_worker(
    *,
    plan_path: Path,
    catalog_dir: Path,
    runtime_input_pack: Path,
    campaign_contract_path: Path,
    data_contract_path: Path,
    feature_contract_path: Path,
    shard_index: int,
    output_dir: Path,
) -> dict[str, object]:
    plan = load_plan(Path(plan_path))
    shard = plan.shard(shard_index)
    catalog_root = Path(catalog_dir)
    catalog_manifest = json.loads((catalog_root / "manifest.json").read_text("utf-8"))
    if catalog_manifest.get("manifest_sha256") != plan.catalog_manifest_sha256:
        raise ValueError("ATLAS_WORKER_CATALOG_HASH_MISMATCH")
    if catalog_manifest.get("validation_opened") is not False or catalog_manifest.get("locked_opened") is not False:
        raise ValueError("ATLAS_WORKER_CATALOG_BOUNDARY_OPEN")
    space_payload = json.loads((catalog_root / "recipe_space.json").read_text("utf-8"))
    if _sha256_file(catalog_root / "recipe_space.json") != plan.catalog_space_sha256:
        raise ValueError("ATLAS_WORKER_SPACE_HASH_MISMATCH")
    campaign = load_and_validate_campaign_contract(Path(campaign_contract_path))
    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(Path(feature_contract_path), data_contract)
    if campaign.search_end != "2010-12-31" or feature_contract.search_end.isoformat() != "2010-12-31":
        raise ValueError("ATLAS_WORKER_TRAIN_END_INVALID")
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_WORKER_DATA_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_WORKER_FEATURE_BOUNDARY_OPEN")
    verify_runtime_input_pack(
        Path(runtime_input_pack),
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(campaign),
    )
    # Rebuild the compact metadata and require the immutable space identity to
    # match the catalog file before any market data is evaluated.
    space, components = build_atlas_space(feature_contract, catalog_id=plan.catalog_id)
    if int(space_payload["canonical_recipe_count"]) != space.canonical_recipe_count:
        raise ValueError("ATLAS_WORKER_SPACE_COUNT_MISMATCH")
    component_by_id = {
        component.configuration_sha256: component
        for rows in components.values()
        for component in rows
    }
    snapshot = Path(runtime_input_pack) / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    baselines = {
        name: Path(runtime_input_pack) / f"baseline_{name}"
        for name in ("price", "market", "macro")
    }
    evaluator = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs=baselines,
    )
    objective = FastTrainObjective(ledger, target_years=tuple(range(1998, 2011)), allowed_end=campaign.search_end)
    component_cache: dict[str, pd.Series] = {}
    rows: list[dict[str, object]] = []
    started_at_iso = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    for ordinal in range(shard.start_ordinal, shard.stop_ordinal):
        raw_ordinal = plan.selected_raw_ordinal(ordinal)
        recipe = recipe_for_ordinal(space, components, raw_ordinal)
        recipe["ordinal"] = ordinal
        recipe["raw_ordinal"] = raw_ordinal
        signals: list[pd.Series] = []
        for component_id in recipe["components"]:
            component = component_by_id[str(component_id)]
            signal = component_cache.get(component.configuration_sha256)
            if signal is None:
                frame = evaluator(component.lane_id, component.configuration)
                signal = feature_frame_to_decisions(frame, allowed_end=campaign.search_end).reindex(ledger.index)
                component_cache[component.configuration_sha256] = signal
            signals.append(signal)
        decisions = compose_signals(signals, dict(recipe["composition"]))
        if int(dict(recipe["composition"]).get("direction", 1)) == -1:
            decisions = -decisions
        scored = objective.score(decisions)
        realized_positions = scored.positions.reindex(scored.realized_at).to_numpy(dtype=float)
        spy_returns = scored.spy_returns.to_numpy(dtype=float)
        atlas_metrics = score_atlas_decisions(
            realized_positions,
            spy_returns,
            scored.realized_at.to_numpy(),
            train_end=campaign.search_end,
        )
        position_bytes = scored.positions.to_numpy(dtype="int8").tobytes()
        rows.append(
            _result_row(
                recipe=recipe,
                scored=scored,
                atlas_metrics=atlas_metrics,
                position_sha256=_sha256_bytes(position_bytes),
                plan_sha256=plan.plan_sha256,
                shard_index=shard_index,
            )
        )
    if len(rows) != shard.expected_recipe_count:
        raise ValueError("ATLAS_WORKER_COUNT_INVALID")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "results.jsonl"
    result_sha256 = _write_jsonl(result_path, rows)
    receipt = {
        "schema_version": 1,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "shard_index": shard_index,
        "start_ordinal": shard.start_ordinal,
        "stop_ordinal": shard.stop_ordinal,
        "expected_recipe_count": shard.expected_recipe_count,
        "actual_recipe_count": len(rows),
        "result_sha256": result_sha256,
        "component_cache_count": len(component_cache),
        "elapsed_seconds": time.perf_counter() - started,
        "started_at_iso": started_at_iso,
        "finished_at_iso": datetime.now(timezone.utc).isoformat(),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "worker_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    # Keep the CLI names independent from the Python API names.  In
    # particular, argparse exposes ``--plan`` while the function deliberately
    # calls it ``plan_path``.  Passing ``vars(args)`` directly would therefore
    # fail only when the real worker starts, after all preflight checks passed.
    print(
        json.dumps(
            run_worker(
                plan_path=args.plan,
                catalog_dir=args.catalog_dir,
                runtime_input_pack=args.runtime_input_pack,
                campaign_contract_path=args.campaign_contract,
                data_contract_path=args.data_contract,
                feature_contract_path=args.feature_contract,
                shard_index=args.shard_index,
                output_dir=args.output_dir,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
