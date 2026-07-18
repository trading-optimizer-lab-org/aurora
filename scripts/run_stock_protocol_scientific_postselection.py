"""Prepare, distribute and finalize scientific pre-holdout stock validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

import numpy as np
import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.campaign import evaluate_spec
from aurora.research.stock_protocol.dataset import read_pack_audit, read_pack_range
from aurora.research.stock_protocol.layers import freeze_snapshot, load_snapshot
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.portfolio import UnsupportedPortfolioData
from aurora.research.stock_protocol.postselection import (
    MIN_CANDIDATE_OBSERVATIONS,
    build_robustness_plan,
    execute_robustness_task,
    merge_robustness_tasks,
)
from aurora.research.stock_protocol.scientific_evaluation import (
    evaluate_development_walk_forward_from_pack,
    evaluate_development_walk_forward_many_from_pack,
)
from aurora.research.stock_protocol.signals import compute_features


DEVELOPMENT_END = "2015-12-31"
HOLDOUT_START = "2016-01-01"
HOLDOUT_END = "2020-12-31"


def _json_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _equity_returns(curve: pd.DataFrame, initial_capital: float = 100_000.0) -> pd.DataFrame:
    if curve.empty or not {"date", "equity"} <= set(curve.columns):
        raise ValueError("development equity curve is empty or malformed")
    frame = curve[["date", "equity"]].copy().sort_values("date")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    equity = pd.to_numeric(frame["equity"], errors="raise").astype(float)
    returns = equity.pct_change(fill_method=None)
    returns.iloc[0] = float(equity.iloc[0]) / initial_capital - 1.0
    if not np.isfinite(returns).all() or returns.le(-1.0).any():
        raise ValueError("development daily returns are invalid")
    frame["daily_return"] = returns
    return frame[["date", "daily_return"]]


def _copy_candidate_ledgers(
    output_root: Path,
    candidate_id: str,
    evaluation: Any,
) -> None:
    for directory, frame in (
        ("daily_equity_curves", evaluation.equity_curve),
        ("trade_ledgers", evaluation.trade_ledger),
        ("position_ledgers", evaluation.position_ledger),
    ):
        target = output_root / directory
        target.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target / f"{candidate_id}.csv", index=False)


def _filter_statistically_eligible_candidates(
    returns: pd.DataFrame,
    trades: pd.DataFrame,
    decisions: list[dict[str, Any]],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    list[dict[str, Any]],
    pd.DataFrame,
    dict[str, int],
]:
    """Exclude histories that cannot support the declared robustness tests."""

    candidate_columns = [column for column in returns if column != "date"]
    observation_counts = {
        candidate: int(returns[candidate].notna().sum())
        for candidate in candidate_columns
    }
    trade_counts = trades.groupby("candidate_id").size().to_dict()
    exclusions: list[dict[str, Any]] = []
    eligible: list[str] = []
    for candidate in candidate_columns:
        observations = observation_counts[candidate]
        closed_trades = int(trade_counts.get(candidate, 0))
        reason = ""
        if observations < MIN_CANDIDATE_OBSERVATIONS:
            reason = "insufficient_development_observations"
        elif closed_trades == 0:
            reason = "no_closed_trades"
        if reason:
            exclusions.append(
                {
                    "candidate_id": candidate,
                    "development_observations": observations,
                    "minimum_required_observations": MIN_CANDIDATE_OBSERVATIONS,
                    "closed_trades": closed_trades,
                    "reason": reason,
                    "locked_opened": False,
                }
            )
        else:
            eligible.append(candidate)
    if len(eligible) < 2:
        raise ValueError(
            "fewer than two candidates have enough real history and closed trades"
        )
    eligible_set = set(eligible)
    filtered_returns = returns[["date", *eligible]].copy()
    filtered_trades = trades.loc[
        trades["candidate_id"].astype(str).isin(eligible_set)
    ].copy()
    filtered_decisions = [
        decision
        for decision in decisions
        if str(decision["candidate_id"]) in eligible_set
    ]
    if len(filtered_decisions) != len(eligible):
        raise ValueError("eligible robustness candidates lack frozen decisions")
    exclusion_columns = [
        "candidate_id",
        "development_observations",
        "minimum_required_observations",
        "closed_trades",
        "reason",
        "locked_opened",
    ]
    return (
        filtered_returns,
        filtered_trades,
        filtered_decisions,
        pd.DataFrame(exclusions, columns=exclusion_columns),
        observation_counts,
    )


def prepare_postselection_inputs(
    *,
    manifest_path: Path,
    pack_root: Path,
    costs_snapshot_path: Path,
    output_root: Path,
    task_count: int = 360,
) -> dict[str, Path]:
    """Re-evaluate frozen cost candidates before 2016 and create real robustness work."""

    manifest = load_protocol_manifest(manifest_path)
    if manifest.locked_opened or manifest.data_end != HOLDOUT_END:
        raise ValueError("manifest violates the locked-period policy")
    pack_audit = read_pack_audit(pack_root)
    if pack_audit.locked_opened or pack_audit.locked_rows:
        raise ValueError("research pack contains locked data")
    snapshot = load_snapshot(
        costs_snapshot_path,
        expected_layer="costs",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    return_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    walk_forward_rows: list[dict[str, Any]] = []
    yearly_parts: list[pd.DataFrame] = []
    frozen_decisions: list[dict[str, Any]] = []
    source_decisions = list(snapshot["decisions"])
    cross_validated_results = evaluate_development_walk_forward_many_from_pack(
        pack_root,
        [dict(decision["parameters"]) for decision in source_decisions],
        start=manifest.research_start,
        end=DEVELOPMENT_END,
    )
    if len(cross_validated_results) != len(source_decisions):
        raise ValueError("walk-forward batch did not return every frozen candidate")
    for decision, cross_validated in zip(
        source_decisions, cross_validated_results, strict=True
    ):
        candidate_id = str(decision["candidate_id"])
        spec = dict(decision["parameters"])
        walk_forward_result = cross_validated.result
        row = {
            **walk_forward_result.result_row(),
            "evaluation_start": manifest.research_start,
            "evaluation_end": DEVELOPMENT_END,
            "data_end": DEVELOPMENT_END,
            "walk_forward_mode": "expanding_10y_3y_1y_purged",
            "walk_forward_folds": len(cross_validated.folds),
            "selection_used_holdout": False,
            "survivorship_limited": True,
            "locked_opened": False,
        }
        walk_forward_rows.append(row)
        if walk_forward_result.status != "evaluated":
            continue
        daily = _equity_returns(walk_forward_result.equity_curve).rename(
            columns={"daily_return": candidate_id}
        )
        return_parts.append(daily)
        trades = walk_forward_result.trade_ledger.copy()
        if not trades.empty:
            trades.insert(0, "candidate_id", candidate_id)
            trades = trades.loc[pd.to_numeric(trades["net_return"], errors="coerce").notna()].copy()
            trade_parts.append(trades)
        yearly = walk_forward_result.yearly.copy()
        yearly["period"] = "development_purged_walk_forward"
        yearly_parts.append(yearly)
        _copy_candidate_ledgers(output_root, candidate_id, walk_forward_result)
        frozen_decisions.append(
            {
                "candidate_id": candidate_id,
                "parameters": spec,
                "validation_metrics": {
                    key: _json_scalar(value)
                    for key, value in walk_forward_result.metrics.items()
                },
                "decision": "advance_to_statistical_robustness",
            }
        )
    if len(return_parts) < 2 or len(frozen_decisions) < 2:
        raise ValueError("at least two frozen evaluated candidates are required")
    returns = return_parts[0]
    for part in return_parts[1:]:
        returns = returns.merge(part, on="date", how="outer", validate="one_to_one")
    returns = returns.sort_values("date").reset_index(drop=True)
    if not trade_parts:
        raise ValueError("frozen candidates produced no closed trades")
    trades = pd.concat(trade_parts, ignore_index=True)
    (
        returns,
        trades,
        frozen_decisions,
        statistical_exclusions,
        observation_counts,
    ) = _filter_statistically_eligible_candidates(
        returns,
        trades,
        frozen_decisions,
    )
    returns_path = output_root / "development_returns.csv"
    trades_path = output_root / "development_trades.csv"
    walk_forward_path = output_root / "walk_forward_results.csv"
    yearly_path = output_root / "yearly_results.csv"
    exclusions_path = output_root / "statistical_exclusions.csv"
    returns.to_csv(returns_path, index=False)
    trades.to_csv(trades_path, index=False)
    exclusion_reasons = (
        statistical_exclusions.set_index("candidate_id")["reason"].to_dict()
        if not statistical_exclusions.empty
        else {}
    )
    walk_forward = pd.DataFrame(walk_forward_rows)
    walk_forward["development_observations"] = (
        walk_forward["candidate_id"].map(observation_counts).fillna(0).astype(int)
    )
    walk_forward["statistical_robustness_eligible"] = walk_forward[
        "candidate_id"
    ].isin({str(item["candidate_id"]) for item in frozen_decisions})
    walk_forward["statistical_exclusion_reason"] = (
        walk_forward["candidate_id"].map(exclusion_reasons).fillna("")
    )
    walk_forward.to_csv(walk_forward_path, index=False)
    statistical_exclusions.to_csv(exclusions_path, index=False)
    pd.concat(yearly_parts, ignore_index=True).to_csv(yearly_path, index=False)
    walk_forward_snapshot = freeze_snapshot(
        layer="walk_forward",
        input_artifact=walk_forward_path,
        output_path=output_root / "walk_forward_snapshot.json",
        policy_hash=manifest.policy_hash,
        dataset_hash=pack_audit.dataset_hash,
        date_start=manifest.research_start,
        date_end=DEVELOPMENT_END,
        universe="current_universe_backfill",
        decisions=frozen_decisions,
    )
    robustness_plan = build_robustness_plan(
        returns, trades[["candidate_id", "symbol", "entry_date", "net_return"]], task_count=task_count
    )
    robustness_plan["policy_hash"] = manifest.policy_hash
    robustness_plan["dataset_hash"] = pack_audit.dataset_hash
    plan_path = output_root / "robustness_plan.json"
    plan_path.write_text(
        json.dumps(robustness_plan, indent=2, sort_keys=True), encoding="utf-8"
    )
    data_audit = {
        **pack_audit.to_json(),
        "data_end": manifest.data_end,
        "locked_rows": 0,
        "locked_opened": False,
        "universe_mode": "current_universe_backfill",
        "survivorship_limited": True,
        "statistical_candidates_eligible": len(frozen_decisions),
        "statistical_candidates_excluded": len(statistical_exclusions),
        "robustness_input_mode": "purged_walk_forward_test_folds",
        "robustness_required_methods": robustness_plan.get("required_methods", []),
        "robustness_unavailable_methods": robustness_plan.get(
            "unavailable_methods", {}
        ),
        "walk_forward_used_for_diagnostics": True,
        "walk_forward_used_for_selection": False,
    }
    data_audit_path = output_root / "data_audit.json"
    data_audit_path.write_text(
        json.dumps(data_audit, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "returns": returns_path,
        "trades": trades_path,
        "walk_forward_results": walk_forward_path,
        "walk_forward_snapshot": walk_forward_snapshot,
        "yearly_results": yearly_path,
        "statistical_exclusions": exclusions_path,
        "robustness_plan": plan_path,
        "data_audit": data_audit_path,
    }


def prepare_postselection_candidate(
    *,
    manifest_path: Path,
    pack_root: Path,
    costs_snapshot_path: Path,
    candidate_index: int,
    output_root: Path,
) -> dict[str, Path]:
    """Evaluate one frozen cost decision without touching the final holdout."""

    manifest = load_protocol_manifest(manifest_path)
    if manifest.locked_opened or manifest.data_end != HOLDOUT_END:
        raise ValueError("manifest violates the locked-period policy")
    pack_audit = read_pack_audit(pack_root)
    if pack_audit.locked_opened or pack_audit.locked_rows:
        raise ValueError("research pack contains locked data")
    snapshot = load_snapshot(
        costs_snapshot_path,
        expected_layer="costs",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    source_decisions = list(snapshot["decisions"])
    if candidate_index < 0 or candidate_index >= len(source_decisions):
        raise IndexError(
            f"candidate index {candidate_index} outside 0..{len(source_decisions) - 1}"
        )
    decision = source_decisions[candidate_index]
    candidate_id = str(decision["candidate_id"])
    spec = dict(decision["parameters"])
    cross_validated = evaluate_development_walk_forward_from_pack(
        pack_root,
        spec,
        start=manifest.research_start,
        end=DEVELOPMENT_END,
    )
    result = cross_validated.result
    result_candidate_id = str(result.result_row().get("candidate_id", ""))
    if result_candidate_id and result_candidate_id != candidate_id:
        raise ValueError(
            f"candidate identity changed: {candidate_id} != {result_candidate_id}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    row = {
        **result.result_row(),
        "candidate_id": candidate_id,
        "evaluation_start": manifest.research_start,
        "evaluation_end": DEVELOPMENT_END,
        "data_end": DEVELOPMENT_END,
        "walk_forward_mode": "expanding_10y_3y_1y_purged",
        "walk_forward_folds": len(cross_validated.folds),
        "selection_used_holdout": False,
        "survivorship_limited": True,
        "locked_opened": False,
    }
    walk_forward_path = output_root / "walk_forward_result.csv"
    pd.DataFrame([row]).to_csv(walk_forward_path, index=False)
    returns_path = output_root / "development_returns.csv"
    trades_path = output_root / "development_trades.csv"
    yearly_path = output_root / "yearly_results.csv"
    evaluated = result.status == "evaluated"
    frozen_decision: dict[str, Any] | None = None
    if evaluated:
        _equity_returns(result.equity_curve).rename(
            columns={"daily_return": candidate_id}
        ).to_csv(returns_path, index=False)
        trades = result.trade_ledger.copy()
        if not trades.empty:
            trades.insert(0, "candidate_id", candidate_id)
            trades = trades.loc[
                pd.to_numeric(trades["net_return"], errors="coerce").notna()
            ].copy()
        trades.to_csv(trades_path, index=False)
        yearly = result.yearly.copy()
        yearly["period"] = "development_purged_walk_forward"
        yearly.to_csv(yearly_path, index=False)
        _copy_candidate_ledgers(output_root, candidate_id, result)
        frozen_decision = {
            "candidate_id": candidate_id,
            "parameters": spec,
            "validation_metrics": {
                key: _json_scalar(value) for key, value in result.metrics.items()
            },
            "decision": "advance_to_statistical_robustness",
        }
    candidate_shard_path = output_root / "candidate_shard.json"
    candidate_shard_path.write_text(
        json.dumps(
            {
                "candidate_index": candidate_index,
                "candidate_count": len(source_decisions),
                "candidate_id": candidate_id,
                "policy_hash": manifest.policy_hash,
                "dataset_hash": pack_audit.dataset_hash,
                "evaluated": evaluated,
                "frozen_decision": frozen_decision,
                "locked_opened": False,
                "data_end": DEVELOPMENT_END,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    outputs = {
        "candidate_shard": candidate_shard_path,
        "walk_forward_result": walk_forward_path,
    }
    for name, path in (
        ("returns", returns_path),
        ("trades", trades_path),
        ("yearly_results", yearly_path),
    ):
        if path.is_file():
            outputs[name] = path
    return outputs


def _copy_shard_ledgers(shard_root: Path, output_root: Path) -> None:
    for directory in ("daily_equity_curves", "trade_ledgers", "position_ledgers"):
        source = shard_root / directory
        if not source.is_dir():
            continue
        target = output_root / directory
        target.mkdir(parents=True, exist_ok=True)
        for path in source.glob("*.csv"):
            destination = target / path.name
            if destination.exists():
                raise ValueError(f"duplicate candidate ledger: {path.name}")
            shutil.copy2(path, destination)


def merge_postselection_candidate_shards(
    *,
    manifest_path: Path,
    pack_root: Path,
    costs_snapshot_path: Path,
    shards_root: Path,
    output_root: Path,
    task_count: int = 360,
) -> dict[str, Path]:
    """Merge every independently evaluated candidate into robustness inputs."""

    manifest = load_protocol_manifest(manifest_path)
    if manifest.locked_opened or manifest.data_end != HOLDOUT_END:
        raise ValueError("manifest violates the locked-period policy")
    pack_audit = read_pack_audit(pack_root)
    if pack_audit.locked_opened or pack_audit.locked_rows:
        raise ValueError("research pack contains locked data")
    snapshot = load_snapshot(
        costs_snapshot_path,
        expected_layer="costs",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    source_decisions = list(snapshot["decisions"])
    shard_paths = sorted(shards_root.rglob("candidate_shard.json"))
    if len(shard_paths) != len(source_decisions):
        raise ValueError(
            f"expected {len(source_decisions)} candidate shards, found {len(shard_paths)}"
        )
    indexed: dict[int, tuple[Path, dict[str, Any]]] = {}
    for path in shard_paths:
        shard = json.loads(path.read_text(encoding="utf-8"))
        index = int(shard["candidate_index"])
        if index in indexed:
            raise ValueError(f"duplicate candidate shard index: {index}")
        if shard.get("locked_opened") is not False:
            raise ValueError(f"candidate shard {index} opened locked data")
        if shard.get("candidate_count") != len(source_decisions):
            raise ValueError(f"candidate shard {index} has the wrong decision count")
        if shard.get("policy_hash") != manifest.policy_hash:
            raise ValueError(f"candidate shard {index} policy hash mismatch")
        if shard.get("dataset_hash") != pack_audit.dataset_hash:
            raise ValueError(f"candidate shard {index} dataset hash mismatch")
        indexed[index] = (path.parent, shard)
    expected_indices = set(range(len(source_decisions)))
    if set(indexed) != expected_indices:
        raise ValueError("candidate shard indices are incomplete")

    output_root.mkdir(parents=True, exist_ok=True)
    return_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    walk_forward_parts: list[pd.DataFrame] = []
    yearly_parts: list[pd.DataFrame] = []
    frozen_decisions: list[dict[str, Any]] = []
    for index, source_decision in enumerate(source_decisions):
        shard_root, shard = indexed[index]
        candidate_id = str(source_decision["candidate_id"])
        if shard.get("candidate_id") != candidate_id:
            raise ValueError(f"candidate shard {index} identity mismatch")
        walk_forward_parts.append(pd.read_csv(shard_root / "walk_forward_result.csv"))
        if not bool(shard.get("evaluated")):
            continue
        frozen = shard.get("frozen_decision")
        if not isinstance(frozen, dict) or frozen.get("candidate_id") != candidate_id:
            raise ValueError(f"candidate shard {index} lacks its frozen decision")
        return_parts.append(pd.read_csv(shard_root / "development_returns.csv"))
        trades_path = shard_root / "development_trades.csv"
        if trades_path.is_file() and trades_path.stat().st_size:
            trades = pd.read_csv(trades_path)
            if not trades.empty:
                trade_parts.append(trades)
        yearly_path = shard_root / "yearly_results.csv"
        if yearly_path.is_file() and yearly_path.stat().st_size:
            yearly = pd.read_csv(yearly_path)
            if not yearly.empty:
                yearly_parts.append(yearly)
        _copy_shard_ledgers(shard_root, output_root)
        frozen_decisions.append(frozen)
    if len(return_parts) < 2 or len(frozen_decisions) < 2:
        raise ValueError("at least two frozen evaluated candidates are required")
    if not trade_parts:
        raise ValueError("frozen candidates produced no closed trades")

    returns = return_parts[0]
    for part in return_parts[1:]:
        returns = returns.merge(part, on="date", how="outer", validate="one_to_one")
    returns = returns.sort_values("date").reset_index(drop=True)
    trades = pd.concat(trade_parts, ignore_index=True)
    (
        returns,
        trades,
        frozen_decisions,
        statistical_exclusions,
        observation_counts,
    ) = _filter_statistically_eligible_candidates(
        returns, trades, frozen_decisions
    )
    returns_path = output_root / "development_returns.csv"
    trades_path = output_root / "development_trades.csv"
    walk_forward_path = output_root / "walk_forward_results.csv"
    yearly_path = output_root / "yearly_results.csv"
    exclusions_path = output_root / "statistical_exclusions.csv"
    returns.to_csv(returns_path, index=False)
    trades.to_csv(trades_path, index=False)
    statistical_exclusions.to_csv(exclusions_path, index=False)
    walk_forward = pd.concat(walk_forward_parts, ignore_index=True)
    eligible_ids = {str(item["candidate_id"]) for item in frozen_decisions}
    exclusion_reasons = (
        statistical_exclusions.set_index("candidate_id")["reason"].to_dict()
        if not statistical_exclusions.empty
        else {}
    )
    walk_forward["development_observations"] = (
        walk_forward["candidate_id"].map(observation_counts).fillna(0).astype(int)
    )
    walk_forward["statistical_robustness_eligible"] = walk_forward[
        "candidate_id"
    ].isin(eligible_ids)
    walk_forward["statistical_exclusion_reason"] = (
        walk_forward["candidate_id"].map(exclusion_reasons).fillna("")
    )
    walk_forward.to_csv(walk_forward_path, index=False)
    if not yearly_parts:
        raise ValueError("frozen candidates produced no yearly evidence")
    pd.concat(yearly_parts, ignore_index=True).to_csv(yearly_path, index=False)
    walk_forward_snapshot = freeze_snapshot(
        layer="walk_forward",
        input_artifact=walk_forward_path,
        output_path=output_root / "walk_forward_snapshot.json",
        policy_hash=manifest.policy_hash,
        dataset_hash=pack_audit.dataset_hash,
        date_start=manifest.research_start,
        date_end=DEVELOPMENT_END,
        universe="current_universe_backfill",
        decisions=frozen_decisions,
    )
    robustness_plan = build_robustness_plan(
        returns,
        trades[["candidate_id", "symbol", "entry_date", "net_return"]],
        task_count=task_count,
    )
    robustness_plan["policy_hash"] = manifest.policy_hash
    robustness_plan["dataset_hash"] = pack_audit.dataset_hash
    plan_path = output_root / "robustness_plan.json"
    plan_path.write_text(
        json.dumps(robustness_plan, indent=2, sort_keys=True), encoding="utf-8"
    )
    data_audit_path = output_root / "data_audit.json"
    data_audit_path.write_text(
        json.dumps(
            {
                **pack_audit.to_json(),
                "data_end": manifest.data_end,
                "locked_rows": 0,
                "locked_opened": False,
                "universe_mode": "current_universe_backfill",
                "survivorship_limited": True,
                "statistical_candidates_eligible": len(frozen_decisions),
                "statistical_candidates_excluded": len(statistical_exclusions),
                "robustness_input_mode": "purged_walk_forward_test_folds",
                "robustness_required_methods": robustness_plan.get(
                    "required_methods", []
                ),
                "robustness_unavailable_methods": robustness_plan.get(
                    "unavailable_methods", {}
                ),
                "walk_forward_used_for_diagnostics": True,
                "walk_forward_used_for_selection": False,
                "candidate_shards_expected": len(source_decisions),
                "candidate_shards_found": len(shard_paths),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "returns": returns_path,
        "trades": trades_path,
        "walk_forward_results": walk_forward_path,
        "walk_forward_snapshot": walk_forward_snapshot,
        "yearly_results": yearly_path,
        "statistical_exclusions": exclusions_path,
        "robustness_plan": plan_path,
        "data_audit": data_audit_path,
    }


def freeze_robustness_snapshot(
    *,
    manifest_path: Path,
    walk_forward_snapshot_path: Path,
    robustness_results_path: Path,
    output_path: Path,
) -> Path:
    """Freeze robustness evidence before any final-holdout observation."""

    manifest = load_protocol_manifest(manifest_path)
    raw_snapshot = json.loads(walk_forward_snapshot_path.read_text(encoding="utf-8"))
    dataset_hash = str(raw_snapshot.get("dataset_hash", ""))
    snapshot = load_snapshot(
        walk_forward_snapshot_path,
        expected_layer="walk_forward",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=dataset_hash,
    )
    robustness = pd.read_csv(robustness_results_path)
    indexed = robustness.set_index("candidate_id", drop=False)
    decisions = []
    for previous in snapshot["decisions"]:
        candidate_id = str(previous["candidate_id"])
        if candidate_id not in indexed.index:
            raise ValueError(f"robustness result missing candidate {candidate_id}")
        evidence = indexed.loc[candidate_id]
        if isinstance(evidence, pd.DataFrame):
            raise ValueError(f"duplicate robustness result for {candidate_id}")
        metrics = {
            key: _json_scalar(value)
            for key, value in evidence.to_dict().items()
            if key != "candidate_id"
        }
        decisions.append(
            {
                "candidate_id": candidate_id,
                "parameters": dict(previous["parameters"]),
                "validation_metrics": metrics,
                "decision": (
                    "robustness_pass"
                    if bool(metrics.get("robust_pass"))
                    else "frozen_pareto_diagnostic_only"
                ),
            }
        )
    return freeze_snapshot(
        layer="robustness",
        input_artifact=robustness_results_path,
        output_path=output_path,
        policy_hash=manifest.policy_hash,
        dataset_hash=dataset_hash,
        date_start=manifest.research_start,
        date_end=DEVELOPMENT_END,
        universe="current_universe_backfill",
        decisions=decisions,
    )


def holdout_result_row(
    *,
    candidate_id: str,
    status: str,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "status": status,
        **{key: _json_scalar(value) for key, value in metrics.items()},
        "period_start": HOLDOUT_START,
        "period_end": HOLDOUT_END,
        "evaluation_count": 1,
        "selection_used": False,
        "validation_used_for_selection": False,
        "locked_opened": False,
        "data_end": HOLDOUT_END,
    }


def evaluate_frozen_holdout(
    *,
    manifest_path: Path,
    pack_root: Path,
    robustness_snapshot_path: Path,
    output_root: Path,
) -> Path:
    """Evaluate the frozen Pareto set once on 2016-2020 without selecting again."""

    manifest = load_protocol_manifest(manifest_path)
    pack_audit = read_pack_audit(pack_root)
    panel = read_pack_range(
        pack_root,
        start_date="2014-01-01",
        end_date=manifest.data_end,
    )
    if panel.audit.dataset_hash != pack_audit.dataset_hash:
        raise ValueError("bounded holdout pack hash mismatch")
    holdout_features = compute_features(panel)
    raw = json.loads(robustness_snapshot_path.read_text(encoding="utf-8"))
    snapshot = load_snapshot(
        robustness_snapshot_path,
        expected_layer="robustness",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    if raw.get("date_end") != DEVELOPMENT_END:
        raise ValueError("robustness was not frozen before final holdout")
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    yearly_parts: list[pd.DataFrame] = []
    for decision in snapshot["decisions"]:
        candidate_id = str(decision["candidate_id"])
        try:
            result = evaluate_spec(
                panel,
                dict(decision["parameters"]),
                start=HOLDOUT_START,
                end=HOLDOUT_END,
                features=holdout_features,
            )
            rows.append(
                holdout_result_row(
                    candidate_id=candidate_id,
                    status=result.status,
                    metrics=result.metrics,
                )
            )
            if result.status == "evaluated":
                _copy_candidate_ledgers(output_root, f"{candidate_id}_holdout", result)
                yearly = result.yearly.copy()
                yearly["period"] = "holdout_2016_2020"
                yearly_parts.append(yearly)
        except UnsupportedPortfolioData as exc:
            rows.append(
                {
                    **holdout_result_row(
                        candidate_id=candidate_id,
                        status="unsupported_missing_data",
                        metrics={},
                    ),
                    "failure_reason": str(exc),
                }
            )
    holdout_path = output_root / "holdout_2016_2020.csv"
    pd.DataFrame(rows).to_csv(holdout_path, index=False)
    if yearly_parts:
        pd.concat(yearly_parts, ignore_index=True).to_csv(
            output_root / "holdout_yearly_results.csv", index=False
        )
    (output_root / "holdout_audit.json").write_text(
        json.dumps(
            {
                "candidate_count": len(rows),
                "evaluation_count_per_candidate": 1,
                "selection_used": False,
                "validation_used_for_selection": False,
                "locked_opened": False,
                "period_start": HOLDOUT_START,
                "period_end": HOLDOUT_END,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return holdout_path


def evaluate_frozen_holdout_candidate(
    *,
    manifest_path: Path,
    pack_root: Path,
    robustness_snapshot_path: Path,
    candidate_index: int,
    output_root: Path,
) -> Path:
    """Evaluate one frozen candidate once on the untouched 2016-2020 holdout."""

    manifest = load_protocol_manifest(manifest_path)
    if manifest.locked_opened or manifest.data_end != HOLDOUT_END:
        raise ValueError("manifest violates the locked-period policy")
    pack_audit = read_pack_audit(pack_root)
    if pack_audit.locked_opened or pack_audit.locked_rows:
        raise ValueError("research pack contains locked data")
    raw = json.loads(robustness_snapshot_path.read_text(encoding="utf-8"))
    snapshot = load_snapshot(
        robustness_snapshot_path,
        expected_layer="robustness",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    if raw.get("date_end") != DEVELOPMENT_END:
        raise ValueError("robustness was not frozen before final holdout")
    decisions = list(snapshot["decisions"])
    if candidate_index < 0 or candidate_index >= len(decisions):
        raise IndexError(
            f"candidate index {candidate_index} outside 0..{len(decisions) - 1}"
        )
    decision = decisions[candidate_index]
    candidate_id = str(decision["candidate_id"])
    panel = read_pack_range(
        pack_root,
        start_date="2014-01-01",
        end_date=HOLDOUT_END,
    )
    if panel.audit.dataset_hash != pack_audit.dataset_hash:
        raise ValueError("bounded holdout pack hash mismatch")
    holdout_features = compute_features(panel)
    output_root.mkdir(parents=True, exist_ok=True)
    yearly_path = output_root / "holdout_yearly_result.csv"
    try:
        result = evaluate_spec(
            panel,
            dict(decision["parameters"]),
            start=HOLDOUT_START,
            end=HOLDOUT_END,
            features=holdout_features,
        )
        row = holdout_result_row(
            candidate_id=candidate_id,
            status=result.status,
            metrics=result.metrics,
        )
        if result.status == "evaluated":
            _copy_candidate_ledgers(output_root, f"{candidate_id}_holdout", result)
            yearly = result.yearly.copy()
            yearly["candidate_id"] = candidate_id
            yearly["period"] = "holdout_2016_2020"
            yearly.to_csv(yearly_path, index=False)
    except UnsupportedPortfolioData as exc:
        row = {
            **holdout_result_row(
                candidate_id=candidate_id,
                status="unsupported_missing_data",
                metrics={},
            ),
            "failure_reason": str(exc),
        }
    result_path = output_root / "holdout_candidate.csv"
    pd.DataFrame([row]).to_csv(result_path, index=False)
    (output_root / "holdout_candidate_shard.json").write_text(
        json.dumps(
            {
                "candidate_index": candidate_index,
                "candidate_count": len(decisions),
                "candidate_id": candidate_id,
                "policy_hash": manifest.policy_hash,
                "dataset_hash": pack_audit.dataset_hash,
                "evaluation_count": 1,
                "selection_used": False,
                "validation_used_for_selection": False,
                "locked_opened": False,
                "period_start": HOLDOUT_START,
                "period_end": HOLDOUT_END,
                "data_end": HOLDOUT_END,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return result_path


def merge_frozen_holdout_candidate_shards(
    *,
    manifest_path: Path,
    pack_root: Path,
    robustness_snapshot_path: Path,
    shards_root: Path,
    output_root: Path,
) -> Path:
    """Require and merge exactly one final-holdout evaluation per candidate."""

    manifest = load_protocol_manifest(manifest_path)
    if manifest.locked_opened or manifest.data_end != HOLDOUT_END:
        raise ValueError("manifest violates the locked-period policy")
    pack_audit = read_pack_audit(pack_root)
    if pack_audit.locked_opened or pack_audit.locked_rows:
        raise ValueError("research pack contains locked data")
    raw = json.loads(robustness_snapshot_path.read_text(encoding="utf-8"))
    snapshot = load_snapshot(
        robustness_snapshot_path,
        expected_layer="robustness",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash=pack_audit.dataset_hash,
    )
    if raw.get("date_end") != DEVELOPMENT_END:
        raise ValueError("robustness was not frozen before final holdout")
    decisions = list(snapshot["decisions"])
    shard_paths = sorted(shards_root.rglob("holdout_candidate_shard.json"))
    if len(shard_paths) != len(decisions):
        raise ValueError(
            f"expected {len(decisions)} holdout candidate shards, "
            f"found {len(shard_paths)}"
        )
    indexed: dict[int, tuple[Path, dict[str, Any]]] = {}
    for path in shard_paths:
        shard = json.loads(path.read_text(encoding="utf-8"))
        index = int(shard["candidate_index"])
        if index in indexed:
            raise ValueError(f"duplicate holdout candidate shard index: {index}")
        expected_policy = {
            "candidate_count": len(decisions),
            "policy_hash": manifest.policy_hash,
            "dataset_hash": pack_audit.dataset_hash,
            "evaluation_count": 1,
            "selection_used": False,
            "validation_used_for_selection": False,
            "locked_opened": False,
            "period_start": HOLDOUT_START,
            "period_end": HOLDOUT_END,
            "data_end": HOLDOUT_END,
        }
        for key, expected in expected_policy.items():
            if shard.get(key) != expected:
                raise ValueError(
                    f"holdout candidate shard {index} has invalid {key}: "
                    f"{shard.get(key)!r}"
                )
        indexed[index] = (path.parent, shard)
    if set(indexed) != set(range(len(decisions))):
        raise ValueError("holdout candidate shard indices are incomplete")

    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[pd.DataFrame] = []
    yearly_parts: list[pd.DataFrame] = []
    seen_candidates: set[str] = set()
    for index, decision in enumerate(decisions):
        shard_root, shard = indexed[index]
        candidate_id = str(decision["candidate_id"])
        if shard.get("candidate_id") != candidate_id:
            raise ValueError(f"holdout candidate shard {index} identity mismatch")
        if candidate_id in seen_candidates:
            raise ValueError(f"duplicate frozen holdout candidate: {candidate_id}")
        seen_candidates.add(candidate_id)
        result = pd.read_csv(shard_root / "holdout_candidate.csv")
        if len(result) != 1 or str(result.iloc[0]["candidate_id"]) != candidate_id:
            raise ValueError(f"holdout candidate shard {index} result mismatch")
        if int(result.iloc[0]["evaluation_count"]) != 1:
            raise ValueError(f"holdout candidate shard {index} was evaluated repeatedly")
        for column in (
            "selection_used",
            "validation_used_for_selection",
            "locked_opened",
        ):
            if bool(result.iloc[0][column]):
                raise ValueError(f"holdout candidate shard {index} violates {column}")
        if str(result.iloc[0]["data_end"]) != HOLDOUT_END:
            raise ValueError(f"holdout candidate shard {index} crossed locked start")
        rows.append(result)
        yearly_path = shard_root / "holdout_yearly_result.csv"
        if yearly_path.is_file() and yearly_path.stat().st_size:
            yearly = pd.read_csv(yearly_path)
            if not yearly.empty:
                yearly_parts.append(yearly)
        _copy_shard_ledgers(shard_root, output_root)

    holdout = pd.concat(rows, ignore_index=True)
    if holdout["candidate_id"].duplicated().any() or len(holdout) != len(decisions):
        raise ValueError("merged holdout does not contain every frozen candidate once")
    holdout_path = output_root / "holdout_2016_2020.csv"
    holdout.to_csv(holdout_path, index=False)
    yearly_output = output_root / "holdout_yearly_results.csv"
    if yearly_parts:
        pd.concat(yearly_parts, ignore_index=True).to_csv(yearly_output, index=False)
    else:
        pd.DataFrame(columns=["candidate_id", "year", "return", "period"]).to_csv(
            yearly_output, index=False
        )
    (output_root / "holdout_audit.json").write_text(
        json.dumps(
            {
                "candidate_count": len(holdout),
                "candidate_shards_expected": len(decisions),
                "candidate_shards_found": len(shard_paths),
                "evaluation_count_per_candidate": 1,
                "selection_used": False,
                "validation_used_for_selection": False,
                "locked_opened": False,
                "period_start": HOLDOUT_START,
                "period_end": HOLDOUT_END,
                "dataset_hash": pack_audit.dataset_hash,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return holdout_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    prepare.add_argument("--pack-root", type=Path, required=True)
    prepare.add_argument("--costs-snapshot", dest="costs_snapshot_path", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--task-count", type=int, default=360)
    candidate = commands.add_parser("prepare-candidate")
    candidate.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    candidate.add_argument("--pack-root", type=Path, required=True)
    candidate.add_argument(
        "--costs-snapshot", dest="costs_snapshot_path", type=Path, required=True
    )
    candidate.add_argument("--candidate-index", type=int, required=True)
    candidate.add_argument("--output-root", type=Path, required=True)
    merge_candidates = commands.add_parser("merge-candidates")
    merge_candidates.add_argument(
        "--manifest", dest="manifest_path", type=Path, required=True
    )
    merge_candidates.add_argument("--pack-root", type=Path, required=True)
    merge_candidates.add_argument(
        "--costs-snapshot", dest="costs_snapshot_path", type=Path, required=True
    )
    merge_candidates.add_argument("--shards-root", type=Path, required=True)
    merge_candidates.add_argument("--output-root", type=Path, required=True)
    merge_candidates.add_argument("--task-count", type=int, default=360)
    task = commands.add_parser("evaluate-task")
    task.add_argument("--plan", dest="plan_path", type=Path, required=True)
    task.add_argument("--returns", dest="returns_path", type=Path, required=True)
    task.add_argument("--trades", dest="trades_path", type=Path, required=True)
    task.add_argument("--task-index", type=int, required=True)
    task.add_argument("--output-root", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--plan", dest="plan_path", type=Path, required=True)
    merge.add_argument("--tasks-root", type=Path, required=True)
    merge.add_argument("--output-root", type=Path, required=True)
    freeze = commands.add_parser("freeze-robustness")
    freeze.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    freeze.add_argument("--walk-forward-snapshot", dest="walk_forward_snapshot_path", type=Path, required=True)
    freeze.add_argument("--robustness-results", dest="robustness_results_path", type=Path, required=True)
    freeze.add_argument("--output", dest="output_path", type=Path, required=True)
    holdout = commands.add_parser("holdout")
    holdout.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    holdout.add_argument("--pack-root", type=Path, required=True)
    holdout.add_argument("--robustness-snapshot", dest="robustness_snapshot_path", type=Path, required=True)
    holdout.add_argument("--output-root", type=Path, required=True)
    holdout_candidate = commands.add_parser("holdout-candidate")
    holdout_candidate.add_argument(
        "--manifest", dest="manifest_path", type=Path, required=True
    )
    holdout_candidate.add_argument("--pack-root", type=Path, required=True)
    holdout_candidate.add_argument(
        "--robustness-snapshot",
        dest="robustness_snapshot_path",
        type=Path,
        required=True,
    )
    holdout_candidate.add_argument("--candidate-index", type=int, required=True)
    holdout_candidate.add_argument("--output-root", type=Path, required=True)
    merge_holdout = commands.add_parser("merge-holdout")
    merge_holdout.add_argument(
        "--manifest", dest="manifest_path", type=Path, required=True
    )
    merge_holdout.add_argument("--pack-root", type=Path, required=True)
    merge_holdout.add_argument(
        "--robustness-snapshot",
        dest="robustness_snapshot_path",
        type=Path,
        required=True,
    )
    merge_holdout.add_argument("--shards-root", type=Path, required=True)
    merge_holdout.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "stock protocol scientific postselection"
    )
    args = vars(_parser().parse_args())
    command = args.pop("command")
    if command == "prepare":
        result: Any = prepare_postselection_inputs(**args)
    elif command == "prepare-candidate":
        result = prepare_postselection_candidate(**args)
    elif command == "merge-candidates":
        result = merge_postselection_candidate_shards(**args)
    elif command == "evaluate-task":
        result = execute_robustness_task(**args)
    elif command == "merge":
        result = merge_robustness_tasks(**args)
    elif command == "freeze-robustness":
        result = freeze_robustness_snapshot(**args)
    elif command == "holdout":
        result = evaluate_frozen_holdout(**args)
    elif command == "holdout-candidate":
        result = evaluate_frozen_holdout_candidate(**args)
    else:
        result = merge_frozen_holdout_candidate_shards(**args)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
