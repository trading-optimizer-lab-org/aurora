"""Evaluate one deterministic shard of the frozen SP500 strategy catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    PreparedLaneCandidate,
    candidate_fingerprints,
    feature_frame_to_decisions,
    load_train_total_return_ledger,
    score_prepared_lane_candidate,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    verify_strategy_catalog_directory,
)


FULL_YEARS = tuple(range(1998, 2011))
FULL_FIDELITY = 27


def compose_signals(signals: Sequence[pd.Series], composition: Mapping[str, Any]) -> pd.Series:
    """Apply the catalog's exact {-1,0,+1} composition semantics."""

    if not signals:
        raise ValueError("CATALOG_COMPOSITION_EMPTY")
    index = signals[0].index
    if any(not item.index.equals(index) for item in signals):
        raise ValueError("CATALOG_COMPONENT_INDEX_MISMATCH")
    values = np.column_stack([item.fillna(0.0).to_numpy(float) for item in signals])
    kind = str(composition.get("kind"))
    if kind == "identity":
        out = values[:, 0]
    elif kind == "and":
        out = np.where(np.all(values == 1.0, axis=1), 1.0, np.where(np.all(values == -1.0, axis=1), -1.0, 0.0))
    elif kind == "gate":
        base = values[:, int(composition.get("base_component_index", 0))]
        out = np.where((base != 0.0) & np.all(values == base[:, None], axis=1), base, 0.0)
    elif kind == "override":
        base = values[:, int(composition.get("base_component_index", 0))]
        priority = values[:, int(composition["priority_component_index"])]
        out = np.where(priority != 0.0, priority, base)
    elif kind == "vote":
        positive = np.sum(values == 1.0, axis=1)
        negative = np.sum(values == -1.0, axis=1)
        needed = values.shape[1] if composition.get("mode") == "unanimity" else values.shape[1] // 2 + 1
        out = np.where(positive >= needed, 1.0, np.where(negative >= needed, -1.0, 0.0))
    elif kind == "weighted_score":
        weights = np.asarray(composition["weights"], dtype=float)
        if weights.shape != (values.shape[1],) or not np.isfinite(weights).all():
            raise ValueError("CATALOG_WEIGHT_MISMATCH")
        out = np.sign(values @ weights / np.abs(weights).sum())
    else:
        raise ValueError(f"CATALOG_COMPOSITION_UNKNOWN:{kind}")
    result = pd.Series(out, index=index, dtype=float, name="decision")
    return result.mask(result == 0.0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.total_shards != 360 or not 0 <= args.shard_index < args.total_shards:
        raise SystemExit("CATALOG_SHARD_INVALID")
    contract = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
    receipt = verify_strategy_catalog_directory(args.catalog_dir)
    if receipt["strategy_count"] != 37258 or receipt["validation_opened"] or receipt["locked_opened"]:
        raise SystemExit("CATALOG_RECEIPT_INVALID")
    verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(contract),
    )
    snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    baselines = {name: args.runtime_input_pack / f"baseline_{name}" for name in ("price", "market", "macro")}
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=contract.search_end,
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
    )
    evaluator = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs=baselines,
    )
    rows = [json.loads(line) for line in (args.catalog_dir / "catalog.jsonl").read_text("utf-8").splitlines()]
    assigned = [row for ordinal, row in enumerate(rows) if ordinal % args.total_shards == args.shard_index]
    decision_index = ledger.index
    component_cache: dict[str, pd.Series] = {}
    output: list[dict[str, Any]] = []
    for row in assigned:
        signals = []
        for component in row["components"]:
            key = component["configuration_sha256"]
            signal = component_cache.get(key)
            if signal is None:
                frame = evaluator(component["lane_id"], component["configuration"])
                signal = feature_frame_to_decisions(frame, allowed_end=contract.search_end).reindex(decision_index)
                component_cache[key] = signal
            signals.append(signal)
        decisions = compose_signals(signals, row["composition"])
        config = {"scientific_recipe_sha256": row["scientific_recipe_sha256"]}
        strategy_fingerprint, position_fingerprint = candidate_fingerprints(row["strategy_id"], config, decisions)
        prepared = PreparedLaneCandidate(
            lane_id=row["strategy_id"], configuration=config, fidelity=FULL_FIDELITY,
            target_years=FULL_YEARS, decisions=decisions,
            strategy_fingerprint=strategy_fingerprint, position_fingerprint=position_fingerprint,
        )
        result = score_prepared_lane_candidate(
            prepared, ledger=ledger, fidelity_years={FULL_FIDELITY: FULL_YEARS}, allowed_end=contract.search_end
        )
        output.append({"strategy_id": row["strategy_id"], "scientific_recipe_sha256": row["scientific_recipe_sha256"], "strategy_kind": row["strategy_kind"], "components": row["components"], "composition": row["composition"], "result": result})
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "results.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in output), "utf-8")
    audit = {"schema_version": 1, "shard_index": args.shard_index, "total_shards": args.total_shards, "strategy_count": len(output), "first_strategy_id": output[0]["strategy_id"] if output else None, "last_strategy_id": output[-1]["strategy_id"] if output else None, "validation_opened": False, "locked_opened": False}
    (args.output_dir / "receipt.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
