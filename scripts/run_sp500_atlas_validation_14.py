"""Open 2011-2020 once for the 14 immutable Atlas-1 Pareto recipes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_objective import score_atlas_decisions
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import load_and_validate_campaign_contract
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    AuthorizedValidationLaneEvaluator,
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_objective import build_adjusted_open_total_return_ledger
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import feature_frame_to_decisions, load_train_total_return_ledger
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract
from aurora.infra.sp500_megarun.selected_validation import (
    ATLAS_VALIDATION_ACK,
    build_authorized_validation_snapshot,
    write_validation_baselines,
)
from aurora.infra.sp500_megarun.strategy_catalog import CatalogComponentV1

from scripts.run_sp500_strategy_catalog_shard import compose_signals


FRONTIER_SHA256 = "c38436e3458b3df0f716fa423befa89ce8127891ff2543207a37893f4870be1d"
PLAN_SHA256 = "bd79d52474fbffba864915f004d9a63114b9d48d235d7502c328c423ad7ddd82"
CATALOG_MANIFEST_SHA256 = "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08"
SOURCE_RUN_ID = 36032882147
TRAIN_RUNTIME_RUN_ID = 31418682679
VALIDATION_SNAPSHOT_RUN_ID = 31420960542
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frozen_frontier(final_results: Path, plan_path: Path) -> list[dict[str, Any]]:
    """Bind the exact pre-validation selection to its verified train run."""

    receipt = json.loads((final_results / "reduction_receipt.json").read_text("utf-8"))
    plan = load_plan(plan_path)
    if (
        receipt.get("accepted") is not True
        or receipt.get("requested_recipe_count") != 209906
        or receipt.get("verified_recipe_count") != 209906
        or receipt.get("pareto_recipe_count") != 14
        or receipt.get("frontier_sha256") != FRONTIER_SHA256
        or receipt.get("plan_sha256") != PLAN_SHA256
        or receipt.get("catalog_manifest_sha256") != CATALOG_MANIFEST_SHA256
        or receipt.get("validation_opened") is not False
        or receipt.get("locked_opened") is not False
        or plan.plan_sha256 != PLAN_SHA256
        or plan.catalog_manifest_sha256 != CATALOG_MANIFEST_SHA256
    ):
        raise ValueError("ATLAS_VALIDATION_SELECTION_IDENTITY_INVALID")
    frontier_path = final_results / "pareto_frontier.jsonl"
    if _sha256_file(frontier_path) != FRONTIER_SHA256:
        raise ValueError("ATLAS_VALIDATION_FRONTIER_HASH_MISMATCH")
    rows = [json.loads(line) for line in frontier_path.read_text("utf-8").splitlines()]
    ids = [str(row.get("strategy_id")) for row in rows]
    if len(rows) != 14 or len(set(ids)) != 14:
        raise ValueError("ATLAS_VALIDATION_FRONTIER_COUNT_OR_ID_INVALID")
    for row in rows:
        identity = {key: value for key, value in row.items() if key != "result_sha256"}
        if (
            canonical_sha256(identity) != row.get("result_sha256")
            or row.get("validation_opened") is not False
            or row.get("locked_opened") is not False
            or row.get("plan_sha256") != PLAN_SHA256
            or row.get("strategy_id") != "ATLAS1-" + str(row.get("scientific_recipe_sha256"))
            or int(row.get("raw_ordinal", -1)) != plan.selected_raw_ordinal(int(row["ordinal"]))
        ):
            raise ValueError("ATLAS_VALIDATION_FRONTIER_ROW_INVALID")
    return rows


def load_frozen_components(catalog_dir: Path, rows: list[dict[str, Any]]) -> dict[str, CatalogComponentV1]:
    manifest = json.loads((catalog_dir / "manifest.json").read_text("utf-8"))
    identity = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    component_file = catalog_dir / "components.jsonl"
    if (
        canonical_sha256(identity) != CATALOG_MANIFEST_SHA256
        or manifest.get("manifest_sha256") != CATALOG_MANIFEST_SHA256
        or manifest.get("validation_opened") is not False
        or manifest.get("locked_opened") is not False
        or _sha256_file(component_file) != manifest["artifacts_sha256"]["components.jsonl"]
    ):
        raise ValueError("ATLAS_VALIDATION_CATALOG_INVALID")
    required = {str(component) for row in rows for component in row["components"]}
    selected: dict[str, CatalogComponentV1] = {}
    with component_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            component_id = str(payload.get("configuration_sha256"))
            if component_id in required:
                if component_id in selected:
                    raise ValueError("ATLAS_VALIDATION_COMPONENT_DUPLICATE")
                selected[component_id] = CatalogComponentV1.from_payload(payload)
    if set(selected) != required:
        raise ValueError("ATLAS_VALIDATION_COMPONENT_MISSING")
    return selected


def _score_rows(
    rows: list[dict[str, Any]],
    components: dict[str, CatalogComponentV1],
    evaluator: TrainLaneEvaluator,
    objective: FastTrainObjective,
    decision_index: pd.DatetimeIndex,
    *,
    allowed_end: str,
    validation: bool,
) -> list[dict[str, Any]]:
    cache: dict[str, pd.Series] = {}
    results: list[dict[str, Any]] = []
    for row in rows:
        signals: list[pd.Series] = []
        for component_id in row["components"]:
            component = components[str(component_id)]
            signal = cache.get(str(component_id))
            if signal is None:
                frame = evaluator(component.lane_id, component.configuration)
                signal = feature_frame_to_decisions(frame, allowed_end=allowed_end).reindex(decision_index)
                cache[str(component_id)] = signal
            signals.append(signal)
        composition = dict(row["composition"])
        decisions = compose_signals(signals, composition)
        if int(composition.get("direction", 1)) == -1:
            decisions = -decisions
        scored = objective.score(decisions)
        if not validation:
            positions_sha256 = hashlib.sha256(scored.positions.to_numpy(dtype="int8").tobytes()).hexdigest()
            if positions_sha256 != row["position_sha256"]:
                raise ValueError("ATLAS_VALIDATION_TRAIN_POSITION_MISMATCH")
            if abs(scored.score.annualized_strategy_return - float(row["annualized_strategy_return"])) > 1e-12:
                raise ValueError("ATLAS_VALIDATION_TRAIN_SCORE_MISMATCH")
            continue
        mask = (scored.realized_at >= VALIDATION_START) & (scored.realized_at <= VALIDATION_END)
        dates = scored.realized_at[mask]
        positions = scored.positions.reindex(dates).to_numpy(dtype=float)
        spy = scored.spy_returns.loc[dates].to_numpy(dtype=float)
        metrics = score_atlas_decisions(positions, spy, dates.to_numpy(), train_end="2020-12-31")
        if metrics.total_years != 10 or [entry["year"] for entry in metrics.annual_rows] != list(range(2011, 2021)):
            raise ValueError("ATLAS_VALIDATION_YEAR_COVERAGE_INVALID")
        results.append({
            "strategy_id": row["strategy_id"],
            "train_result_sha256": row["result_sha256"],
            "annualized_strategy_return": scored.score.annualized_strategy_return,
            "annualized_alpha": scored.score.annualized_alpha,
            "positive_weeks": metrics.positive_weeks,
            "total_weeks": metrics.total_weeks,
            "positive_months": metrics.positive_months,
            "total_months": metrics.total_months,
            "joint_positive_above_spy_years": metrics.joint_positive_above_spy_years,
            "total_years": metrics.total_years,
            "annual_rows": list(metrics.annual_rows),
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "validation_opened": True,
            "locked_opened": False,
        })
    return results


def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    if not args.preflight_only and (os.environ.get("GITHUB_ACTIONS") != "true" or args.authorization != ATLAS_VALIDATION_ACK):
        raise ValueError("ATLAS_VALIDATION_AUTHORIZATION_REQUIRED")
    if not args.preflight_only and (args.output_dir.exists() or args.working_dir.exists()):
        raise ValueError("ATLAS_VALIDATION_OUTPUT_ALREADY_EXISTS")
    rows = load_frozen_frontier(args.final_results, args.plan)
    components = load_frozen_components(args.catalog_dir, rows)
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
    if campaign.search_end != "2010-12-31" or feature_contract.search_end.isoformat() != "2010-12-31":
        raise ValueError("ATLAS_VALIDATION_TRAIN_BOUNDARY_INVALID")
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_VALIDATION_SOURCE_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_VALIDATION_FEATURE_BOUNDARY_OPEN")
    verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(campaign),
    )
    defaults = default_lane_configurations(feature_contract)
    train_snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    train_ledger = load_train_total_return_ledger(
        train_snapshot,
        allowed_end="2010-12-31",
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    train_evaluator = TrainLaneEvaluator(
        train_snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=defaults,
        baseline_feature_dirs={name: args.runtime_input_pack / f"baseline_{name}" for name in ("price", "market", "macro")},
    )
    _score_rows(rows, components, train_evaluator, FastTrainObjective(train_ledger, target_years=tuple(range(1998, 2011)), allowed_end="2010-12-31"), pd.DatetimeIndex(train_ledger.index), allowed_end="2010-12-31", validation=False)
    if args.preflight_only:
        return {"train_parity_verified": True, "strategy_count": len(rows), "frontier_sha256": FRONTIER_SHA256, "validation_opened": False, "locked_opened": False}
    args.working_dir.mkdir(parents=True)
    authorized = build_authorized_validation_snapshot(
        train_snapshot,
        args.validation_snapshot,
        args.working_dir / "authorized_validation_snapshot_1993_2020",
        authorization=args.authorization,
        expected_authorization=ATLAS_VALIDATION_ACK,
    )
    base = AuthorizedValidationLaneEvaluator(
        authorized.snapshot_dir,
        expected_manifest_sha256=authorized.manifest_sha256,
        expected_spy_sha256=authorized.spy_sha256,
        default_configurations=defaults,
        authorization=args.authorization,
        expected_authorization=ATLAS_VALIDATION_ACK,
    )
    baselines = write_validation_baselines(base, defaults, args.working_dir / "validation_baselines")
    evaluator = AuthorizedValidationLaneEvaluator(
        authorized.snapshot_dir,
        expected_manifest_sha256=authorized.manifest_sha256,
        expected_spy_sha256=authorized.spy_sha256,
        default_configurations=defaults,
        authorization=args.authorization,
        expected_authorization=ATLAS_VALIDATION_ACK,
        baseline_feature_dirs=baselines,
    )
    prices = pd.read_parquet(authorized.snapshot_dir / "D_SPY.parquet")
    if pd.DatetimeIndex(pd.to_datetime(prices["date"])).max().normalize() != VALIDATION_END:
        raise ValueError("ATLAS_VALIDATION_SPY_END_INCOMPLETE")
    ledger = build_adjusted_open_total_return_ledger(prices, allowed_end="2020-12-31")
    results = _score_rows(rows, components, evaluator, FastTrainObjective(ledger, target_years=tuple(range(2011, 2021)), allowed_end="2020-12-31"), pd.DatetimeIndex(ledger.index), allowed_end="2020-12-31", validation=True)
    args.output_dir.mkdir(parents=True)
    results_path = args.output_dir / "validation_results.jsonl"
    with results_path.open("x", encoding="utf-8", newline="\n") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    receipt = {
        "schema_version": 1,
        "source_run_id": SOURCE_RUN_ID,
        "train_runtime_run_id": TRAIN_RUNTIME_RUN_ID,
        "validation_snapshot_run_id": VALIDATION_SNAPSHOT_RUN_ID,
        "frontier_sha256": FRONTIER_SHA256,
        "plan_sha256": PLAN_SHA256,
        "catalog_manifest_sha256": CATALOG_MANIFEST_SHA256,
        "authorized_snapshot_manifest_sha256": authorized.manifest_sha256,
        "git_commit": os.environ.get("SCIENTIFIC_COMMIT_SHA"),
        "strategy_count": len(results),
        "train_parity_verified": True,
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "maximum_date": authorized.maximum_date,
        "validation_opened": True,
        "locked_opened": False,
        "results_sha256": _sha256_file(results_path),
    }
    if len(results) != 14 or receipt["maximum_date"] != "2020-12-31":
        raise ValueError("ATLAS_VALIDATION_RECEIPT_INVALID")
    (args.output_dir / "validation_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("final-results", "plan", "catalog-dir", "runtime-input-pack", "validation-snapshot", "campaign-contract", "data-contract", "feature-contract", "working-dir", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    print(json.dumps(run_validation(parser.parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
