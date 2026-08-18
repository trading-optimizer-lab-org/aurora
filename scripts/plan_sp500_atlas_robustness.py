"""Freeze the complete candidate order and perturbations before robustness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from scripts.run_sp500_atlas_robustness import _read_jsonl, build_robustness_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-results", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    reduction = json.loads((args.final_results / "reduction_receipt.json").read_text("utf-8"))
    if reduction.get("plan_sha256") != plan.plan_sha256:
        raise ValueError("ATLAS_ROBUSTNESS_PLAN_MISMATCH")
    policy = json.loads(args.policy.read_text("utf-8"))
    frontier = list(_read_jsonl(args.final_results / "pareto_frontier.jsonl"))
    manifest = build_robustness_manifest(
        policy,
        [str(row["strategy_id"]) for row in frontier],
        plan_sha256=plan.plan_sha256,
        reduction_sha256=str(reduction["frontier_sha256"]),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "accepted": True,
        "robustness_sha256": manifest["robustness_sha256"],
        "candidate_count": len(manifest["candidate_strategy_ids"]),
        "validation_opened": False,
        "locked_opened": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
