"""Evaluate one deterministic shard of the frozen SP500 strategy catalog."""

from __future__ import annotations

import argparse
import json
import math
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.catalog_performance import (
    CatalogPerformanceRecorder,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions
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


def _resident_memory_mb() -> float:
    try:
        import psutil
    except ImportError:
        return 0.0
    return float(psutil.Process().memory_info().rss / (1024.0 * 1024.0))


def _compounded_return(values: pd.Series) -> float:
    return math.expm1(float(np.log1p(values.to_numpy(dtype=float)).sum()))


def weekly_winning_or_positive_metrics(
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
) -> dict[str, int | float]:
    """Count weeks that either make money or beat SPY, without double counting."""

    if strategy_returns.empty or not strategy_returns.index.equals(spy_returns.index):
        raise ValueError("CATALOG_WEEKLY_RETURN_INDEX_INVALID")
    weekly = pd.DataFrame({"strategy": strategy_returns, "spy": spy_returns})
    weekly["week"] = weekly.index.to_period("W-FRI")
    compounded = weekly.groupby("week", sort=True)[["strategy", "spy"]].agg(
        _compounded_return
    )
    positive = compounded["strategy"] > 0.0
    beats_spy = compounded["strategy"] > compounded["spy"]
    winning_or_positive = positive | beats_spy
    week_count = len(compounded)
    return {
        "week_count": week_count,
        "positive_weeks": int(positive.sum()),
        "weeks_beating_spy": int(beats_spy.sum()),
        "winning_or_positive_weeks": int(winning_or_positive.sum()),
        "weekly_winning_or_positive_rate": float(winning_or_positive.sum() / week_count),
    }


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


def resolve_component_signals(
    components: Sequence[Mapping[str, Any]],
    *,
    evaluator: Callable[[str, Mapping[str, Any]], Any],
    decision_index: pd.Index,
    allowed_end: Any,
    component_cache: dict[str, pd.Series],
    recorder: CatalogPerformanceRecorder | None = None,
    decision_builder: Callable[..., pd.Series] = feature_frame_to_decisions,
) -> list[pd.Series]:
    """Build each missing component once and profile physical work honestly."""

    signals: list[pd.Series] = []
    for component in components:
        lane_id = str(component["lane_id"])
        configuration = component["configuration"]
        if not isinstance(configuration, Mapping):
            raise ValueError("CATALOG_COMPONENT_CONFIGURATION_INVALID")
        key = str(component["configuration_sha256"])
        signal = component_cache.get(key)
        if signal is None:
            context = (
                recorder.component_build(lane_id, key)
                if recorder is not None
                else nullcontext()
            )
            with context:
                frame = evaluator(lane_id, configuration)
                signal = decision_builder(
                    frame,
                    allowed_end=allowed_end,
                ).reindex(decision_index)
                component_cache[key] = signal
        elif recorder is not None:
            recorder.component_cache_hit(lane_id, key)
        signals.append(signal)
    return signals


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--selected-config", type=Path)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument(
        "--thermal-state",
        choices=sorted(CatalogPerformanceRecorder.THERMAL_STATES),
        default="cold",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.total_shards != 360 or not 0 <= args.shard_index < args.total_shards:
        raise SystemExit("CATALOG_SHARD_INVALID")
    from aurora.infra.sp500_megarun.catalog_admission import (
        verify_catalog_worker_admission,
    )

    try:
        verify_catalog_worker_admission(
            args.run_plan,
            admission_token_sha256=args.admission_token,
            shard_index=args.shard_index,
            total_shards=args.total_shards,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    recorder = CatalogPerformanceRecorder(
        shard_index=args.shard_index,
        total_shards=args.total_shards,
        thermal_state=args.thermal_state,
        memory_mb=_resident_memory_mb,
    )
    with recorder.phase("contract_validation"):
        contract = load_and_validate_campaign_contract(args.campaign_contract)
        data_contract = load_and_validate_contract(args.data_contract)
        feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
        receipt = verify_strategy_catalog_directory(args.catalog_dir)
    if receipt["strategy_count"] != 37258 or receipt["validation_opened"] or receipt["locked_opened"]:
        raise SystemExit("CATALOG_RECEIPT_INVALID")
    with recorder.phase("runtime_verification"):
        verify_runtime_input_pack(
            args.runtime_input_pack,
            expected_scientific_input_binding_sha256=scientific_input_binding_sha256(contract),
        )
    snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    baselines = {name: args.runtime_input_pack / f"baseline_{name}" for name in ("price", "market", "macro")}
    with recorder.phase("data_load") as span:
        ledger = load_train_total_return_ledger(
            snapshot,
            allowed_end=contract.search_end,
            expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
            expected_spy_sha256=contract.train_spy_sha256,
        )
        span.add_units(len(ledger))
    with recorder.phase("evaluator_initialization"):
        evaluator = TrainLaneEvaluator(
            snapshot,
            expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
            expected_spy_sha256=contract.train_spy_sha256,
            default_configurations=default_lane_configurations(feature_contract),
            baseline_feature_dirs=baselines,
        )
    catalog_path = args.catalog_dir / "catalog.jsonl"
    with recorder.phase("catalog_read") as span:
        catalog_bytes = catalog_path.read_bytes()
        span.add_bytes_read(len(catalog_bytes))
        rows = [json.loads(line) for line in catalog_bytes.decode("utf-8").splitlines()]
        span.add_units(len(rows))
    assigned = [row for ordinal, row in enumerate(rows) if ordinal % args.total_shards == args.shard_index]
    decision_index = ledger.index
    component_cache: dict[str, pd.Series] = {}
    output: list[dict[str, Any]] = []
    with recorder.phase("catalog_evaluation") as evaluation_span:
        for row in assigned:
            signals = resolve_component_signals(
                row["components"],
                evaluator=evaluator,
                decision_index=decision_index,
                allowed_end=contract.search_end,
                component_cache=component_cache,
                recorder=recorder,
            )
            decisions = recorder.measure(
                "signal_composition",
                partial(compose_signals, signals, row["composition"]),
            )
            config = {"scientific_recipe_sha256": row["scientific_recipe_sha256"]}
            strategy_fingerprint, position_fingerprint = recorder.measure(
                "position_fingerprinting",
                partial(
                    candidate_fingerprints,
                    row["strategy_id"],
                    config,
                    decisions,
                ),
            )
            prepared = PreparedLaneCandidate(
                lane_id=row["strategy_id"], configuration=config, fidelity=FULL_FIDELITY,
                target_years=FULL_YEARS, decisions=decisions,
                strategy_fingerprint=strategy_fingerprint, position_fingerprint=position_fingerprint,
            )
            result = recorder.measure(
                "strategy_scoring",
                partial(
                    score_prepared_lane_candidate,
                    prepared,
                    ledger=ledger,
                    fidelity_years={FULL_FIDELITY: FULL_YEARS},
                    allowed_end=contract.search_end,
                ),
            )
            realized = recorder.measure(
                "realized_returns",
                partial(
                    score_ledger_decisions,
                    ledger,
                    decisions,
                    target_years=FULL_YEARS,
                    allowed_end=contract.search_end,
                ),
            )
            result = dict(result)
            weekly_metrics = recorder.measure(
                "weekly_metrics",
                partial(
                    weekly_winning_or_positive_metrics,
                    realized.strategy_returns,
                    realized.spy_returns,
                ),
            )
            result["info"] = {
                **result["info"],
                **weekly_metrics,
            }
            output.append({"strategy_id": row["strategy_id"], "scientific_recipe_sha256": row["scientific_recipe_sha256"], "strategy_kind": row["strategy_kind"], "components": row["components"], "composition": row["composition"], "result": result})
            evaluation_span.add_units(1)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with recorder.phase("result_serialization") as serialization_span:
        result_bytes = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in output).encode("utf-8")
        (args.output_dir / "results.jsonl").write_bytes(result_bytes)
        serialization_span.add_units(len(output))
        serialization_span.add_bytes_written(len(result_bytes))
    selected_output: list[dict[str, Any]] = []
    if args.selected_config is not None and args.shard_index == 0:
        selected_rows = json.loads(args.selected_config.read_text("utf-8"))
        if not isinstance(selected_rows, list) or len(selected_rows) != 13:
            raise SystemExit("CATALOG_SELECTED_CONFIG_INVALID")
        for selected in selected_rows:
            lane_id = str(selected["lane_id"])
            configuration = dict(selected["configuration"])
            frame = evaluator(lane_id, configuration)
            decisions = feature_frame_to_decisions(
                frame,
                allowed_end=contract.search_end,
            ).reindex(decision_index)
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
            result = score_prepared_lane_candidate(
                prepared,
                ledger=ledger,
                fidelity_years={FULL_FIDELITY: FULL_YEARS},
                allowed_end=contract.search_end,
            )
            realized = score_ledger_decisions(
                ledger,
                decisions,
                target_years=FULL_YEARS,
                allowed_end=contract.search_end,
            )
            result = dict(result)
            result["info"] = {
                **result["info"],
                **weekly_winning_or_positive_metrics(
                    realized.strategy_returns,
                    realized.spy_returns,
                ),
            }
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
    performance_outputs = recorder.write(args.output_dir)
    audit = {"schema_version": 1, "shard_index": args.shard_index, "total_shards": args.total_shards, "strategy_count": len(output), "selected_strategy_count": len(selected_output), "first_strategy_id": output[0]["strategy_id"] if output else None, "last_strategy_id": output[-1]["strategy_id"] if output else None, "performance_summary_sha256": performance_outputs.summary_sha256, "performance_events_sha256": performance_outputs.events_path_sha256, "physical_component_builds": recorder.summary()["physical_component_builds"], "component_cache_hits": recorder.summary()["component_cache_hits"], "thermal_state": args.thermal_state, "validation_opened": False, "locked_opened": False}
    (args.output_dir / "receipt.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
