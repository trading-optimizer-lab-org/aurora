"""Reproduce and later evaluate the one frozen stock-protocol strategy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.exact_oos import (
    EXACT_CANDIDATE_ID,
    EXACT_DATASET_HASH,
    EXACT_POLICY_HASH,
    EXACT_SOURCE_ARTIFACT_DIGEST,
    EXACT_SOURCE_ARTIFACT_NAME,
    EXACT_SOURCE_RUN_ID,
    EXACT_SOURCE_TASK_ARTIFACT_DIGEST,
    EXACT_SOURCE_TASK_ARTIFACT_NAME,
    EXACT_SOURCE_TASK_RUN_ID,
    assert_exact_is_reproduction,
    exact_strategy_spec,
)
from aurora.research.stock_protocol.scientific_evaluation import (
    evaluate_development_walk_forward_from_pack,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def reproduce_is(
    *,
    pack_root: Path,
    source_result_path: Path,
    source_trade_ledger_path: Path,
    source_selection_path: Path,
    output_root: Path,
    implementation_commit: str,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission("exact IS reproduction")
    source_result = json.loads(source_result_path.read_text(encoding="utf-8-sig"))
    selection = pd.read_csv(source_selection_path)
    if len(selection) != 290:
        raise ValueError(f"source selection row count mismatch: {len(selection)}")
    best_cagr = selection.loc[pd.to_numeric(selection["cagr"]).idxmax()]
    best_sharpe = selection.loc[pd.to_numeric(selection["sharpe"]).idxmax()]
    if (
        best_cagr["candidate_id"] != EXACT_CANDIDATE_ID
        or best_sharpe["candidate_id"] != EXACT_CANDIDATE_ID
    ):
        raise ValueError("frozen candidate is not both source maxima")
    if json.loads(best_cagr["spec_json"]) != exact_strategy_spec():
        raise ValueError("source selection spec differs from frozen exact spec")
    if source_result.get("dataset_hash") != EXACT_DATASET_HASH:
        raise ValueError("source result dataset hash mismatch")
    if source_result.get("policy_hash") != EXACT_POLICY_HASH:
        raise ValueError("source result policy hash mismatch")
    source_ledger = pd.read_csv(source_trade_ledger_path)
    evaluation = evaluate_development_walk_forward_from_pack(
        pack_root,
        exact_strategy_spec(),
        start="1995-01-01",
        end="2015-12-31",
        initial_capital=100_000.0,
        mode="expanding",
    )
    report = assert_exact_is_reproduction(
        evaluation.result,
        source_result=source_result,
        source_trade_ledger=source_ledger,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation.result.trade_ledger.to_csv(
        output_root / "is_reproduced_trade_ledger.csv", index=False
    )
    evaluation.result.position_ledger.to_parquet(
        output_root / "is_reproduced_position_ledger.parquet", index=False
    )
    evaluation.result.equity_curve.to_parquet(
        output_root / "is_reproduced_daily_equity.parquet", index=False
    )
    evaluation.result.yearly.to_csv(
        output_root / "is_reproduced_yearly.csv", index=False
    )
    evaluation.fold_results.to_csv(
        output_root / "is_reproduced_folds.csv", index=False
    )
    _write_json(output_root / "strategy_spec.json", exact_strategy_spec())
    _write_json(
        output_root / "is_reproduction.json",
        {
            **report,
            "implementation_commit": implementation_commit,
            "source_run_id": EXACT_SOURCE_RUN_ID,
            "source_artifact_name": EXACT_SOURCE_ARTIFACT_NAME,
            "source_artifact_digest": EXACT_SOURCE_ARTIFACT_DIGEST,
            "source_task_run_id": EXACT_SOURCE_TASK_RUN_ID,
            "source_task_artifact_name": EXACT_SOURCE_TASK_ARTIFACT_NAME,
            "source_task_artifact_digest": EXACT_SOURCE_TASK_ARTIFACT_DIGEST,
            "dataset_hash": EXACT_DATASET_HASH,
            "policy_hash": EXACT_POLICY_HASH,
            "development_start": "1995-01-01",
            "development_end": "2015-12-31",
            "validation_used_for_selection": False,
            "locked_opened": False,
            "survivorship_limited": True,
        },
    )
    metric_rows = []
    for name, values in report["metric_comparison"].items():
        metric_rows.append({"metric": name, **values})
    pd.DataFrame(metric_rows).to_csv(
        output_root / "is_reproduction_metrics.csv", index=False
    )
    summary = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "exact_reproduction": True,
        "closed_operations": report["closed_operations"],
        "ledger_rows": report["ledger_rows"],
        "locked_opened": False,
        "output_root": str(output_root),
    }
    print(json.dumps(summary, sort_keys=True))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    reproduce = subparsers.add_parser("reproduce-is")
    reproduce.add_argument("--pack-root", type=Path, required=True)
    reproduce.add_argument("--source-result", dest="source_result_path", type=Path, required=True)
    reproduce.add_argument(
        "--source-trade-ledger",
        dest="source_trade_ledger_path",
        type=Path,
        required=True,
    )
    reproduce.add_argument(
        "--source-selection",
        dest="source_selection_path",
        type=Path,
        required=True,
    )
    reproduce.add_argument("--output-root", type=Path, required=True)
    reproduce.add_argument("--implementation-commit", required=True)
    return parser


def main() -> int:
    args = vars(_parser().parse_args())
    command = args.pop("command")
    if command == "reproduce-is":
        reproduce_is(**args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
