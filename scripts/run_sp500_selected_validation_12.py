"""Run the single authorized 2011-2020 validation of 12 frozen recipes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    AuthorizedValidationLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_objective import (
    build_adjusted_open_total_return_ledger,
    score_ledger_decisions,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    candidate_fingerprints,
    feature_frame_to_decisions,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.selected_validation import (
    VALIDATION_ACK,
    VALIDATION_END,
    VALIDATION_START,
    SelectedValidationError,
    build_authorized_validation_snapshot,
    compose_selected_signals,
    load_selection_manifest,
    score_validation_returns,
    write_validation_baselines,
)


TRAIN_RUNTIME_RUN_ID = 31418682679
TRAIN_RUNTIME_ARTIFACT = (
    "sp500-megarun-dehb-runtime-inputs-31418682679"
)
VALIDATION_SNAPSHOT_RUN_ID = 31418658411
VALIDATION_SNAPSHOT_ARTIFACT = (
    "sp500-megarun-VALIDATION-CLOSED-2011-2020-F001-F240-31418658411"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--validation-snapshot", type=Path, required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--authorization", required=True)
    return parser


def _canonical_key(lane_id: str, configuration: dict[str, Any]) -> str:
    payload = json.dumps(
        {"lane_id": lane_id, "configuration": configuration},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _summary_row(row: dict[str, Any]) -> dict[str, Any]:
    validation = row["validation_metrics"]
    return {
        "selection_order": row["selection_order"],
        "name": row["name"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "train_annualized_return": row["train_metrics"][
            "annualized_strategy_return"
        ],
        "validation_annualized_return": validation["annualized_strategy_return"],
        "validation_annualized_alpha": validation["annualized_alpha"],
        "validation_weekly_positive_rate": validation["weekly_positive_rate"],
        "validation_weekly_spy_beat_rate": validation["weekly_spy_beat_rate"],
        "validation_weekly_winning_or_positive_rate": validation[
            "weekly_winning_or_positive_rate"
        ],
        "validation_positive_years": validation["positive_years"],
        "validation_years_beating_spy": validation["years_beating_spy"],
        "validation_years_passing_both": validation["years_passing_both"],
        "validation_average_return_when_spy_falls": validation[
            "average_return_when_spy_falls"
        ],
        "validation_worst_annual_return": validation["worst_annual_return"],
        "validation_worst_annual_alpha": validation["worst_annual_alpha"],
    }


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("SELECTED_VALIDATION_GITHUB_ACTIONS_REQUIRED")
    if args.authorization != VALIDATION_ACK:
        raise SystemExit("SELECTED_VALIDATION_AUTHORIZATION_INVALID")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract,
        data_contract,
    )
    selection = load_selection_manifest(args.selection_manifest)
    boundaries = campaign.raw.get("boundaries", {})
    if (
        campaign.validation_opened
        or campaign.locked_opened
        or boundaries.get("validation_start") != VALIDATION_START.date().isoformat()
        or boundaries.get("validation_end") != VALIDATION_END.date().isoformat()
    ):
        raise SystemExit("SELECTED_VALIDATION_CAMPAIGN_BOUNDARY_INVALID")
    verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            campaign
        ),
    )
    work = args.working_dir.resolve()
    if work.exists():
        raise SystemExit("SELECTED_VALIDATION_WORKDIR_ALREADY_EXISTS")
    work.mkdir(parents=True)
    train_snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    authorized = build_authorized_validation_snapshot(
        train_snapshot,
        args.validation_snapshot,
        work / "authorized_validation_snapshot_1993_2020",
        authorization=args.authorization,
    )
    defaults = default_lane_configurations(feature_contract)
    base_evaluator = AuthorizedValidationLaneEvaluator(
        authorized.snapshot_dir,
        expected_manifest_sha256=authorized.manifest_sha256,
        expected_spy_sha256=authorized.spy_sha256,
        default_configurations=defaults,
        authorization=args.authorization,
    )
    baseline_roots = write_validation_baselines(
        base_evaluator,
        defaults,
        work / "validation_baselines",
    )
    evaluator = AuthorizedValidationLaneEvaluator(
        authorized.snapshot_dir,
        expected_manifest_sha256=authorized.manifest_sha256,
        expected_spy_sha256=authorized.spy_sha256,
        default_configurations=defaults,
        authorization=args.authorization,
        baseline_feature_dirs=baseline_roots,
    )
    prices = pd.read_parquet(authorized.snapshot_dir / "D_SPY.parquet")
    ledger = build_adjusted_open_total_return_ledger(
        prices,
        allowed_end=VALIDATION_END.date().isoformat(),
    )
    component_cache: dict[str, pd.Series] = {}
    result_rows: list[dict[str, Any]] = []
    for strategy in selection.strategies:
        component_signals: list[pd.Series] = []
        for component in strategy.components:
            lane_id = str(component["lane_id"])
            configuration = dict(component["configuration"])
            key = _canonical_key(lane_id, configuration)
            signal = component_cache.get(key)
            if signal is None:
                feature = evaluator(lane_id, configuration)
                signal = feature_frame_to_decisions(
                    feature,
                    allowed_end=VALIDATION_END.date().isoformat(),
                ).reindex(ledger.index)
                component_cache[key] = signal
            component_signals.append(signal)
        decisions = compose_selected_signals(
            component_signals,
            strategy.composition,
        )
        strategy_fingerprint, position_fingerprint = candidate_fingerprints(
            strategy.source_id,
            {"recipe_sha256": strategy.recipe_sha256},
            decisions,
        )
        realized = score_ledger_decisions(
            ledger,
            decisions,
            target_years=tuple(range(2011, 2021)),
            allowed_end=VALIDATION_END.date().isoformat(),
        )
        validation_mask = (
            realized.strategy_returns.index >= VALIDATION_START
        ) & (realized.strategy_returns.index <= VALIDATION_END)
        validation_metrics = score_validation_returns(
            realized.strategy_returns.loc[validation_mask],
            realized.spy_returns.loc[validation_mask],
        )
        result_rows.append(
            {
                "selection_order": strategy.selection_order,
                "name": strategy.name,
                "source_kind": strategy.source_kind,
                "source_id": strategy.source_id,
                "recipe_sha256": strategy.recipe_sha256,
                "components": list(strategy.components),
                "composition": dict(strategy.composition),
                "train_metrics": dict(strategy.train_metrics),
                "validation_metrics": validation_metrics,
                "strategy_fingerprint": strategy_fingerprint,
                "position_fingerprint": position_fingerprint,
                "validation_opened": True,
                "locked_opened": False,
            }
        )
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit("SELECTED_VALIDATION_OUTPUT_ALREADY_EXISTS")
    output.mkdir(parents=True)
    results_path = output / "validation_results.jsonl"
    results_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in result_rows
        ),
        encoding="utf-8",
    )
    summary_rows = [_summary_row(row) for row in result_rows]
    summary_path = output / "validation_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    frozen_selection = output / "selected_12_frozen.json"
    frozen_selection.write_bytes(args.selection_manifest.read_bytes())
    receipt = {
        "schema_version": 1,
        "selection_id": selection.selection_id,
        "selection_manifest_sha256": selection.sha256,
        "campaign_id": campaign.raw["campaign_id"],
        "git_commit": os.environ.get("SCIENTIFIC_COMMIT_SHA"),
        "train_runtime_run_id": TRAIN_RUNTIME_RUN_ID,
        "train_runtime_artifact": TRAIN_RUNTIME_ARTIFACT,
        "validation_snapshot_run_id": VALIDATION_SNAPSHOT_RUN_ID,
        "validation_snapshot_artifact": VALIDATION_SNAPSHOT_ARTIFACT,
        "authorized_snapshot_manifest_sha256": authorized.manifest_sha256,
        "authorized_spy_sha256": authorized.spy_sha256,
        "authorized_dataset_count": authorized.dataset_count,
        "maximum_date": authorized.maximum_date,
        "strategy_count": len(result_rows),
        "unique_component_count": len(component_cache),
        "results_sha256": _sha256_file(results_path),
        "summary_sha256": _sha256_file(summary_path),
        "validation_start": VALIDATION_START.date().isoformat(),
        "validation_end": VALIDATION_END.date().isoformat(),
        "validation_opened": True,
        "locked_opened": False,
    }
    if receipt["strategy_count"] != 12 or receipt["maximum_date"] != "2020-12-31":
        raise SelectedValidationError("SELECTED_VALIDATION_RECEIPT_INVALID")
    (output / "validation_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
