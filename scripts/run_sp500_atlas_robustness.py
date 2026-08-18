"""Run the frozen, train-only Atlas robustness campaign."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_objective import score_atlas_decisions
from aurora.infra.sp500_megarun.catalog_atlas_robustness import classify_atlas_robustness
from aurora.infra.sp500_megarun.catalog_atlas_space import build_atlas_space
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import load_and_validate_campaign_contract
from aurora.infra.sp500_megarun.dehb_worker import feature_frame_to_decisions, load_train_total_return_ledger
from aurora.infra.sp500_megarun.dehb_lane_registry import TrainLaneEvaluator, default_lane_configurations
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract

try:
    from scripts.run_sp500_strategy_catalog_shard import compose_signals
except ModuleNotFoundError:
    from run_sp500_strategy_catalog_shard import compose_signals


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_robustness_manifest(
    policy: Mapping[str, object],
    candidate_strategy_ids: Sequence[str],
    *,
    plan_sha256: str,
    reduction_sha256: str,
) -> dict[str, object]:
    """Freeze candidate order and perturbations before any candidate is scored."""

    if policy.get("validation_opened") is not False or policy.get("locked_opened") is not False:
        raise ValueError("ATLAS_ROBUSTNESS_POLICY_BOUNDARY_OPEN")
    if policy.get("train_end") != "2010-12-31":
        raise ValueError("ATLAS_ROBUSTNESS_POLICY_TRAIN_END_INVALID")
    limit = int(policy["max_pareto_candidates"])
    candidates = sorted({str(value) for value in candidate_strategy_ids})[:limit]
    perturbations = [dict(value) for value in policy["perturbations"]]
    identity = {
        "schema_version": 1,
        "policy_id": str(policy["policy_id"]),
        "train_end": "2010-12-31",
        "candidate_strategy_ids": candidates,
        "perturbations": perturbations,
        "plan_sha256": plan_sha256,
        "reduction_sha256": reduction_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    return {**identity, "robustness_sha256": _sha256_json(identity)}


def _read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("ATLAS_ROBUSTNESS_ROW_OBJECT_REQUIRED")
                yield row


def _metrics(positions: np.ndarray, dates: pd.DatetimeIndex, spy: np.ndarray) -> dict[str, object]:
    result = score_atlas_decisions(positions, spy, dates.to_numpy(), train_end="2010-12-31")
    return {
        "positive_weeks": result.positive_weeks,
        "total_weeks": result.total_weeks,
        "positive_week_fraction": result.positive_week_fraction,
        "positive_months": result.positive_months,
        "total_months": result.total_months,
        "positive_month_fraction": result.positive_month_fraction,
        "joint_positive_above_spy_years": result.joint_positive_above_spy_years,
        "total_years": result.total_years,
        "joint_positive_above_spy_fraction": result.joint_positive_above_spy_fraction,
        "annual_rows": json.dumps(list(result.annual_rows), sort_keys=True),
        "train_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
    }


def _period_mask(dates: pd.DatetimeIndex, start: str | None, end: str | None) -> np.ndarray:
    mask = np.ones(len(dates), dtype=bool)
    if start:
        mask &= dates >= pd.Timestamp(start)
    if end:
        mask &= dates <= pd.Timestamp(end)
    return mask


def _compact_result(candidate_id: str, name: str, values: Mapping[str, object]) -> dict[str, object]:
    return {"strategy_id": candidate_id, "name": name, **dict(values)}


def _build_signals(
    component_ids: Sequence[str],
    *,
    component_by_id: Mapping[str, object],
    evaluator: TrainLaneEvaluator,
    decision_index: pd.DatetimeIndex,
    cache: dict[str, pd.Series],
) -> list[pd.Series]:
    signals: list[pd.Series] = []
    for component_id in component_ids:
        component = component_by_id[str(component_id)]
        key = str(component.configuration_sha256)
        signal = cache.get(key)
        if signal is None:
            frame = evaluator(component.lane_id, component.configuration)
            signal = feature_frame_to_decisions(frame, allowed_end="2010-12-31").reindex(decision_index)
            cache[key] = signal
        signals.append(signal)
    return signals


def _neighbor_component(
    component: object,
    *,
    direction: str,
    lane_components: Mapping[str, Sequence[object]],
) -> object | None:
    values = list(lane_components[str(component.lane_id)])
    index = next((i for i, value in enumerate(values) if value.configuration_sha256 == component.configuration_sha256), None)
    if index is None:
        return None
    target = index - 1 if direction == "lower" else index + 1
    return values[target] if 0 <= target < len(values) else None


def run_robustness(
    *,
    final_results_dir: Path,
    plan_path: Path,
    catalog_dir: Path,
    runtime_input_pack: Path,
    campaign_contract_path: Path,
    data_contract_path: Path,
    feature_contract_path: Path,
    policy_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    plan = load_plan(plan_path)
    reduction = json.loads((Path(final_results_dir) / "reduction_receipt.json").read_text("utf-8"))
    if reduction.get("plan_sha256") != plan.plan_sha256:
        raise ValueError("ATLAS_ROBUSTNESS_PLAN_MISMATCH")
    policy = json.loads(Path(policy_path).read_text("utf-8"))
    frontier = list(_read_jsonl(Path(final_results_dir) / "pareto_frontier.jsonl"))
    by_id = {str(row["strategy_id"]): row for row in frontier}
    manifest = build_robustness_manifest(
        policy,
        list(by_id),
        plan_sha256=plan.plan_sha256,
        reduction_sha256=str(reduction["frontier_sha256"]),
    )
    candidates = [by_id[str(value)] for value in manifest["candidate_strategy_ids"]]

    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(Path(feature_contract_path), data_contract)
    campaign = load_and_validate_campaign_contract(Path(campaign_contract_path))
    if campaign.search_end != "2010-12-31" or feature_contract.search_end.isoformat() != "2010-12-31":
        raise ValueError("ATLAS_ROBUSTNESS_TRAIN_END_INVALID")
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_ROBUSTNESS_DATA_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_ROBUSTNESS_FEATURE_BOUNDARY_OPEN")
    snapshot = Path(runtime_input_pack) / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    evaluator = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs={name: Path(runtime_input_pack) / f"baseline_{name}" for name in ("price", "market", "macro")},
    )
    _, lane_components = build_atlas_space(feature_contract, catalog_id=plan.catalog_id)
    component_by_id = {
        component.configuration_sha256: component
        for values in lane_components.values()
        for component in values
    }
    decision_index = pd.DatetimeIndex(ledger.index).normalize()
    objective = FastTrainObjective(ledger, target_years=tuple(range(1998, 2011)), allowed_end="2010-12-31")
    spy = pd.to_numeric(ledger["long_return"], errors="raise").to_numpy(dtype=float)
    realized_dates = decision_index[1:]
    spy_realized = spy[:-1]
    cache: dict[str, pd.Series] = {}
    results: list[dict[str, object]] = []
    classifications: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_id = str(candidate["strategy_id"])
        component_ids = [str(value) for value in candidate["components"]]
        composition = dict(candidate["composition"])
        signals = _build_signals(component_ids, component_by_id=component_by_id, evaluator=evaluator, decision_index=decision_index, cache=cache)
        decisions = compose_signals(signals, composition)
        if int(composition.get("direction", 1)) == -1:
            decisions = -decisions
        base_scored = objective.score(decisions)
        base_positions = base_scored.positions.reindex(realized_dates).fillna(0.0).to_numpy(dtype=float)
        base_metrics = _metrics(base_positions, realized_dates, spy_realized)
        perturbation_rows: list[dict[str, object]] = []
        for perturbation in manifest["perturbations"]:
            kind = str(perturbation["kind"])
            name = str(perturbation["name"])
            if kind == "decision_delay":
                values = _metrics(pd.Series(base_positions, index=realized_dates).shift(int(perturbation["days"])).fillna(0.0).to_numpy(), realized_dates, spy_realized)
                perturbation_rows.append(_compact_result(candidate_id, name, values))
            elif kind in {"subperiod", "boundary_shift", "fixed_gap"}:
                mask = _period_mask(realized_dates, perturbation.get("start"), perturbation.get("end"))
                if kind == "fixed_gap":
                    mask = ~mask
                values = _metrics(base_positions[mask], realized_dates[mask], spy_realized[mask])
                perturbation_rows.append(_compact_result(candidate_id, name, values))
            elif kind == "leave_one_year_out":
                for year in range(1998, 2011):
                    mask = realized_dates.year != year
                    values = _metrics(base_positions[mask], realized_dates[mask], spy_realized[mask])
                    perturbation_rows.append(_compact_result(candidate_id, f"{name}_{year}", values))
            elif kind == "remove_best_periods":
                annual = json.loads(str(base_metrics["annual_rows"]))
                years = sorted(annual, key=lambda row: (-float(row["strategy_return"]), int(row["year"])))[: int(perturbation["count"])]
                mask = ~np.isin(realized_dates.year, [int(row["year"]) for row in years])
                values = _metrics(base_positions[mask], realized_dates[mask], spy_realized[mask])
                perturbation_rows.append(_compact_result(candidate_id, name, values))
            elif kind == "neighbor_parameter":
                for index, component_id in enumerate(component_ids):
                    component = component_by_id[component_id]
                    neighbor = _neighbor_component(component, direction=str(perturbation["direction"]), lane_components=lane_components)
                    if neighbor is None:
                        perturbation_rows.append(_compact_result(candidate_id, f"{name}_{index}", {"train_end": "2010-12-31", "validation_opened": False, "locked_opened": False, "invalid_reason": "NO_NEIGHBOR"}))
                        continue
                    changed_ids = list(component_ids)
                    changed_ids[index] = str(neighbor.configuration_sha256)
                    changed_signals = _build_signals(changed_ids, component_by_id=component_by_id, evaluator=evaluator, decision_index=decision_index, cache=cache)
                    changed = compose_signals(changed_signals, composition)
                    if int(composition.get("direction", 1)) == -1:
                        changed = -changed
                    changed_scored = objective.score(changed)
                    changed_positions = changed_scored.positions.reindex(realized_dates).fillna(0.0).to_numpy(dtype=float)
                    perturbation_rows.append(_compact_result(candidate_id, f"{name}_{index}", _metrics(changed_positions, realized_dates, spy_realized)))
            elif kind == "ablation_each_component":
                for index in range(len(signals)):
                    ablated = list(signals)
                    ablated[index] = pd.Series(np.nan, index=decision_index)
                    changed = compose_signals(ablated, composition)
                    if int(composition.get("direction", 1)) == -1:
                        changed = -changed
                    changed_scored = objective.score(changed)
                    changed_positions = changed_scored.positions.reindex(realized_dates).fillna(0.0).to_numpy(dtype=float)
                    perturbation_rows.append(_compact_result(candidate_id, f"{name}_{index}", _metrics(changed_positions, realized_dates, spy_realized)))
            else:
                raise ValueError(f"ATLAS_ROBUSTNESS_PERTURBATION_UNKNOWN:{kind}")
        results.extend(perturbation_rows)
        checked = [row for row in perturbation_rows if "invalid_reason" not in row]
        classification = classify_atlas_robustness(base_metrics, checked)
        classifications.append({
            "strategy_id": candidate_id,
            "status": classification.status,
            "red_test_count": len(classification.red_tests),
            "red_tests_json": json.dumps(list(classification.red_tests)),
            "zero_tolerance_failures_json": json.dumps(list(classification.zero_tolerance_failures)),
            "perturbation_count": len(perturbation_rows),
            "validation_opened": False,
            "locked_opened": False,
        })

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "robustness_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results_frame = pd.DataFrame(results)
    classifications_frame = pd.DataFrame(classifications)
    results_frame.to_parquet(output / "robustness_results.parquet", index=False)
    classifications_frame.to_parquet(output / "robustness_classification.parquet", index=False)
    classifications_frame[classifications_frame["status"] == "green"].to_parquet(output / "robust_candidates.parquet", index=False)
    classifications_frame[classifications_frame["status"].isin(["amber"])].to_parquet(output / "fragile_reserve.parquet", index=False)
    classifications_frame[classifications_frame["status"] == "invalid"].to_parquet(output / "invalid_candidates.parquet", index=False)
    receipt = {
        "schema_version": 1,
        "accepted": True,
        "robustness_sha256": manifest["robustness_sha256"],
        "candidate_count": len(candidates),
        "perturbation_result_count": len(results),
        "green_count": int((classifications_frame["status"] == "green").sum()),
        "amber_count": int((classifications_frame["status"] == "amber").sum()),
        "red_count": int((classifications_frame["status"] == "red").sum()),
        "invalid_count": int((classifications_frame["status"] == "invalid").sum()),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "robustness_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-results", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_robustness(
                final_results_dir=args.final_results,
                plan_path=args.plan,
                catalog_dir=args.catalog_dir,
                runtime_input_pack=args.runtime_input_pack,
                campaign_contract_path=args.campaign_contract,
                data_contract_path=args.data_contract,
                feature_contract_path=args.feature_contract,
                policy_path=args.policy,
                output_dir=args.output_dir,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
