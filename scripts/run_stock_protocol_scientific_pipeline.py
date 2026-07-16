"""Plan, execute and strictly merge one scientific stock-protocol layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from aurora.research.stock_protocol.campaign import (
    DEVELOPMENT_END,
    canonical_candidate_id,
    evaluate_spec,
    expand_layer_specs,
    initial_signal_specs,
)
from aurora.research.stock_protocol.dataset import read_pack
from aurora.research.stock_protocol.layers import (
    freeze_snapshot,
    load_snapshot,
    required_predecessor,
)
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.pareto import pareto_frontier


WORKFLOW_LAYERS = ("signal", "weights", "entries", "exits", "portfolio", "costs")
EXPANSION_LAYER = {
    "weights": "weight",
    "entries": "entry",
    "exits": "exit",
    "portfolio": "portfolio",
    "costs": "cost",
}
MAX_MATRIX_JOBS = 180
MAX_LAYER_JOBS = 360
MAX_FROZEN_DECISIONS = 10
PARETO_MAXIMIZE = ("cagr", "sortino", "calmar", "return_per_capital_day")
PARETO_MINIMIZE = (
    "drawdown_abs",
    "expected_shortfall_abs",
    "turnover",
    "average_days_invested",
    "total_costs",
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str),
        encoding="utf-8",
    )
    return path


def _validate_layer(layer: str) -> None:
    if layer not in WORKFLOW_LAYERS:
        raise ValueError(f"unknown scientific workflow layer: {layer}")


def _matrix_split(task_count: int) -> tuple[list[int], list[int]]:
    if task_count <= 0:
        raise ValueError("scientific layer cannot plan zero tasks")
    if task_count > MAX_LAYER_JOBS:
        raise ValueError(
            f"scientific layer planned {task_count} tasks; maximum is {MAX_LAYER_JOBS}"
        )
    first_count = min(MAX_MATRIX_JOBS, (task_count + 1) // 2)
    first = list(range(first_count))
    second = list(range(first_count, task_count))
    if len(second) > MAX_MATRIX_JOBS:
        raise ValueError("matrix_b exceeds GitHub's scientific concurrency contract")
    return first, second


def _upstream_specs(
    *,
    layer: str,
    previous_snapshot_path: Path | None,
    policy_hash: str,
    dataset_hash: str,
) -> list[dict[str, Any]]:
    predecessor = required_predecessor(layer)
    if predecessor is None:
        if previous_snapshot_path is not None:
            raise ValueError("signal layer must not consume a previous snapshot")
        return []
    if previous_snapshot_path is None:
        raise ValueError(f"layer {layer} requires the frozen {predecessor} snapshot")
    snapshot = load_snapshot(
        previous_snapshot_path,
        expected_layer=predecessor,
        expected_policy_hash=policy_hash,
        expected_dataset_hash=dataset_hash,
    )
    return [dict(item["parameters"]) for item in snapshot["decisions"]]


def plan_layer(
    *,
    manifest_path: Path,
    layer: str,
    output_path: Path,
    dataset_hash: str,
    previous_snapshot_path: Path | None,
) -> Path:
    """Create a dynamic matrix containing only genuine evaluation tasks."""

    _validate_layer(layer)
    manifest = load_protocol_manifest(manifest_path)
    if not dataset_hash:
        raise ValueError("dataset_hash is required")
    if manifest.locked_opened or manifest.data_end != "2020-12-31":
        raise ValueError("manifest violates the closed locked-period contract")
    if layer == "signal":
        specs = initial_signal_specs(manifest)
    else:
        upstream = _upstream_specs(
            layer=layer,
            previous_snapshot_path=previous_snapshot_path,
            policy_hash=manifest.policy_hash,
            dataset_hash=dataset_hash,
        )
        specs = expand_layer_specs(upstream, EXPANSION_LAYER[layer], manifest)
    planned = [
        {"candidate_id": canonical_candidate_id(spec), "spec": dict(spec)}
        for spec in specs
    ]
    candidate_ids = [item["candidate_id"] for item in planned]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError(f"layer {layer} produced duplicate candidate IDs")
    matrix_a, matrix_b = _matrix_split(len(planned))
    payload = {
        "schema_version": 1,
        "layer": layer,
        "dataset_hash": dataset_hash,
        "policy_hash": manifest.policy_hash,
        "data_end": manifest.data_end,
        "development_end": DEVELOPMENT_END.date().isoformat(),
        "locked_opened": False,
        "task_count": len(planned),
        "matrix_a": matrix_a,
        "matrix_b": matrix_b,
        "specs": planned,
    }
    return _write_json(output_path, payload)


def _load_plan(path: Path, layer: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("layer") != layer:
        raise ValueError(f"plan does not belong to layer {layer}")
    if payload.get("locked_opened") is not False:
        raise ValueError("plan opened locked data")
    specs = payload.get("specs")
    if not isinstance(specs, list) or int(payload.get("task_count", -1)) != len(specs):
        raise ValueError("plan task_count does not match its specs")
    ids = [str(item.get("candidate_id", "")) for item in specs]
    if not ids or any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("plan contains empty or duplicate candidate IDs")
    expected_indexes = set(range(len(specs)))
    actual_indexes = set(payload.get("matrix_a", [])) | set(payload.get("matrix_b", []))
    if actual_indexes and actual_indexes != expected_indexes:
        raise ValueError("plan matrices do not cover every task exactly once")
    return payload


def evaluate_task(
    *,
    manifest_path: Path,
    plan_path: Path,
    pack_root: Path,
    layer: str,
    task_index: int,
    output_root: Path,
) -> Path:
    """Evaluate exactly one planned configuration and persist full ledgers."""

    _validate_layer(layer)
    manifest = load_protocol_manifest(manifest_path)
    plan = _load_plan(plan_path, layer)
    if task_index < 0 or task_index >= int(plan["task_count"]):
        raise ValueError("task_index is outside the dynamic plan")
    if plan.get("policy_hash") != manifest.policy_hash:
        raise ValueError("plan policy hash mismatch")
    panel = read_pack(pack_root, manifest.data_end)
    if panel.audit.dataset_hash != plan.get("dataset_hash"):
        raise ValueError("plan dataset hash mismatch")
    planned = plan["specs"][task_index]
    spec = dict(planned["spec"])
    if canonical_candidate_id(spec) != planned["candidate_id"]:
        raise ValueError("planned candidate ID is not canonical")
    result = evaluate_spec(
        panel,
        spec,
        start=manifest.research_start,
        end=DEVELOPMENT_END.date().isoformat(),
    )
    task_root = output_root / f"task={task_index:04d}"
    task_root.mkdir(parents=True, exist_ok=True)
    row = {
        **result.result_row(),
        "layer": layer,
        "task_index": task_index,
        "horizon_sessions": int(spec.get("horizon_sessions", 0)),
        "cost_bps": int(spec.get("cost_bps", 0)),
        "dataset_hash": panel.audit.dataset_hash,
        "policy_hash": manifest.policy_hash,
        "survivorship_limited": True,
        "locked_opened": False,
        "data_end": manifest.data_end,
        "evaluation_start": manifest.research_start,
        "evaluation_end": DEVELOPMENT_END.date().isoformat(),
    }
    _write_json(task_root / "result.json", row)
    result.equity_curve.to_csv(task_root / "daily_equity.csv", index=False)
    result.trade_ledger.to_csv(task_root / "trade_ledger.csv", index=False)
    result.position_ledger.to_csv(task_root / "position_ledger.csv", index=False)
    result.yearly.to_csv(task_root / "yearly.csv", index=False)
    return task_root / "result.json"


def _result_files(tasks_root: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in tasks_root.rglob("result.json"):
        task_parts = [part for part in path.parts if part.startswith("task=")]
        if not task_parts:
            continue
        try:
            index = int(task_parts[-1].split("=", 1)[1])
        except ValueError as exc:
            raise ValueError(f"invalid task directory for {path}") from exc
        if index in found:
            raise ValueError(f"duplicate task result for index {index}")
        found[index] = path
    return found


def _finite_pareto_rows(frame: pd.DataFrame) -> pd.DataFrame:
    evaluated = frame.loc[frame["status"].eq("evaluated")].copy()
    if evaluated.empty:
        raise ValueError("scientific layer has no evaluated rows")
    evaluated["drawdown_abs"] = pd.to_numeric(
        evaluated["max_drawdown"], errors="coerce"
    ).abs()
    evaluated["expected_shortfall_abs"] = pd.to_numeric(
        evaluated["expected_shortfall_5"], errors="coerce"
    ).abs()
    front = pareto_frontier(
        evaluated,
        maximize=PARETO_MAXIMIZE,
        minimize=PARETO_MINIMIZE,
    )
    if front.empty:
        raise ValueError("scientific layer has no finite Pareto rows")
    return front


def _compromise_selection(front: pd.DataFrame) -> pd.DataFrame:
    """Bound the next layer without reducing selection to one headline metric."""

    if len(front) <= MAX_FROZEN_DECISIONS:
        return front.copy()
    utilities: list[pd.Series] = []
    for column in PARETO_MAXIMIZE:
        values = pd.to_numeric(front[column], errors="raise")
        span = float(values.max() - values.min())
        utilities.append((values - values.min()) / span if span else pd.Series(0.5, index=front.index))
    for column in PARETO_MINIMIZE:
        values = pd.to_numeric(front[column], errors="raise")
        span = float(values.max() - values.min())
        utilities.append((values.max() - values) / span if span else pd.Series(0.5, index=front.index))
    ranked = front.copy()
    ranked["pareto_compromise_score"] = pd.concat(utilities, axis=1).mean(axis=1)
    return ranked.sort_values(
        ["pareto_compromise_score", "candidate_id"],
        ascending=[False, True],
    ).head(MAX_FROZEN_DECISIONS)


def merge_layer_tasks(
    *,
    manifest_path: Path,
    layer: str,
    plan_path: Path,
    tasks_root: Path,
    output_root: Path,
) -> dict[str, Path]:
    """Require complete task coverage, compute Pareto and freeze the handoff."""

    _validate_layer(layer)
    manifest = load_protocol_manifest(manifest_path)
    plan = _load_plan(plan_path, layer)
    if plan.get("policy_hash") not in (None, manifest.policy_hash):
        raise ValueError("plan policy hash mismatch")
    expected = set(range(int(plan["task_count"])))
    files = _result_files(tasks_root)
    actual = set(files)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f"missing task results: {missing}")
    if extra:
        raise ValueError(f"unexpected task results: {extra}")
    rows: list[dict[str, Any]] = []
    for index in sorted(expected):
        row = json.loads(files[index].read_text(encoding="utf-8"))
        planned = plan["specs"][index]
        if int(row.get("task_index", index)) != index:
            raise ValueError(f"task index mismatch at {index}")
        if row.get("candidate_id") != planned["candidate_id"]:
            raise ValueError(f"candidate mismatch at task {index}")
        if row.get("dataset_hash") != plan.get("dataset_hash"):
            raise ValueError(f"dataset hash mismatch at task {index}")
        if row.get("policy_hash") != manifest.policy_hash:
            raise ValueError(f"policy hash mismatch at task {index}")
        if row.get("locked_opened") is not False:
            raise ValueError(f"task {index} opened locked data")
        if str(row.get("data_end")) != manifest.data_end:
            raise ValueError(f"task {index} has an invalid data boundary")
        if pd.Timestamp(row.get("evaluation_end")) > DEVELOPMENT_END:
            raise ValueError(f"task {index} used final holdout during selection")
        rows.append(row)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / f"{layer}_results.csv"
    frame = pd.DataFrame(rows)
    frame.to_csv(results_path, index=False)
    front = _finite_pareto_rows(frame)
    pareto_path = output_root / f"{layer}_pareto_frontier.csv"
    front.to_csv(pareto_path, index=False)
    selected = _compromise_selection(front)
    specs_by_id = {item["candidate_id"]: item["spec"] for item in plan["specs"]}
    metric_columns = [*PARETO_MAXIMIZE, *PARETO_MINIMIZE]
    decisions = [
        {
            "candidate_id": str(row["candidate_id"]),
            "parameters": dict(specs_by_id[str(row["candidate_id"])]),
            "validation_metrics": {
                column: float(row[column]) for column in metric_columns
            },
            "decision": "advance_on_development_pareto",
        }
        for _, row in selected.iterrows()
    ]
    snapshot_path = output_root / f"{layer}_snapshot.json"
    freeze_snapshot(
        layer=layer,
        input_artifact=results_path,
        output_path=snapshot_path,
        policy_hash=manifest.policy_hash,
        dataset_hash=str(plan["dataset_hash"]),
        date_start=manifest.research_start,
        date_end=DEVELOPMENT_END.date().isoformat(),
        universe="current_universe_backfill",
        decisions=decisions,
    )
    audit = {
        "layer": layer,
        "planned_tasks": len(expected),
        "found_tasks": len(actual),
        "evaluated_rows": int(frame["status"].eq("evaluated").sum()),
        "pareto_rows": int(len(front)),
        "frozen_decisions": len(decisions),
        "dataset_hash": plan["dataset_hash"],
        "policy_hash": manifest.policy_hash,
        "development_end": DEVELOPMENT_END.date().isoformat(),
        "holdout_used_for_selection": False,
        "locked_opened": False,
        "partial": False,
    }
    audit_path = _write_json(output_root / f"{layer}_merge_audit.json", audit)
    return {
        "results": results_path,
        "pareto": pareto_path,
        "snapshot": snapshot_path,
        "audit": audit_path,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    plan.add_argument("--layer", required=True)
    plan.add_argument("--output", dest="output_path", type=Path, required=True)
    plan.add_argument("--dataset-hash", required=True)
    plan.add_argument("--previous-snapshot", dest="previous_snapshot_path", type=Path)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    evaluate.add_argument("--plan", dest="plan_path", type=Path, required=True)
    evaluate.add_argument("--pack-root", type=Path, required=True)
    evaluate.add_argument("--layer", required=True)
    evaluate.add_argument("--task-index", type=int, required=True)
    evaluate.add_argument("--output-root", type=Path, required=True)
    merge = subparsers.add_parser("merge")
    merge.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    merge.add_argument("--layer", required=True)
    merge.add_argument("--plan", dest="plan_path", type=Path, required=True)
    merge.add_argument("--tasks-root", type=Path, required=True)
    merge.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = vars(_parser().parse_args())
    command = args.pop("command")
    if command == "plan":
        result: Any = plan_layer(**args)
    elif command == "evaluate":
        result = evaluate_task(**args)
    else:
        result = merge_layer_tasks(**args)
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
