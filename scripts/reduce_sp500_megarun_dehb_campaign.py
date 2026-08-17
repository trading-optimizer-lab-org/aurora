from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
    validate_campaign_bindings,
)
from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision
from aurora.infra.sp500_megarun.dehb_launch_contract import (
    load_and_validate_launch_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_results(root: Path) -> list[Mapping[str, Any]]:
    paths = sorted(root.rglob("worker_result.json"))
    results: list[Mapping[str, Any]] = []
    for path in paths:
        value = json.loads(path.read_text("utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError(f"WORKER_RESULT_NOT_MAPPING:{path}")
        results.append(value)
    return results


def _load_planned_job_payloads(root: Path) -> dict[int, Mapping[str, Any]]:
    payloads: dict[int, Mapping[str, Any]] = {}
    for shard in "ABC":
        path = root / f"matrix_{shard}.json"
        value = json.loads(path.read_text("utf-8"))
        rows = value.get("include") if isinstance(value, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError(f"WAVE_PLAN_MATRIX_INVALID:{shard}")
        for payload in rows:
            if not isinstance(payload, Mapping):
                raise ValueError("WAVE_PLAN_PAYLOAD_INVALID")
            if str(payload.get("job_id", "")).startswith("SKIP-"):
                continue
            job_index = int(payload.get("job_index", -1))
            if job_index in payloads:
                raise ValueError(f"WAVE_PLAN_DUPLICATE_JOB:{job_index}")
            payloads[job_index] = payload
    if not payloads:
        raise ValueError("WAVE_PLAN_HAS_NO_JOBS")
    return payloads


def _write_github_outputs(path: Path, decision: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"action={decision['action']}\n")
        for key in (
            "next_wave",
            "next_restart_ordinal",
            "strategy_fingerprint",
            "lane_id",
        ):
            if key in decision:
                handle.write(f"{key}={decision[key]}\n")
        handle.write(
            "retry_job_indices="
            + json.dumps(decision.get("retry_job_indices", []), separators=(",", ":"))
            + "\n"
        )


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_CAMPAIGN_REDUCE")
    parser = argparse.ArgumentParser(
        description="Reduce 360 exact worker results without opening validation."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO_ROOT / "config" / "sp500_megarun_dehb_campaign_v1.json",
    )
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--expected-code-commit-sha", required=True)
    parser.add_argument("--wave", type=int, required=True)
    parser.add_argument("--wave-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--global-robustness", type=Path)
    args = parser.parse_args()

    contract = load_and_validate_campaign_contract(args.contract)
    launch = load_and_validate_launch_contract(
        args.launch_contract,
        contract,
        expected_code_commit_sha=args.expected_code_commit_sha,
    )
    validate_campaign_bindings(contract, repo_root=REPO_ROOT)
    results = _load_results(args.results_root)
    global_robustness = (
        json.loads(args.global_robustness.read_text("utf-8"))
        if args.global_robustness is not None
        else None
    )
    decision = controller_decision(
        contract,
        results,
        wave=args.wave,
        launch_contract_sha256=launch.sha256,
        planned_job_payloads=_load_planned_job_payloads(args.wave_plan),
        global_robustness=global_robustness,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    github_output = args.github_output
    if github_output is None and os.environ.get("GITHUB_OUTPUT"):
        github_output = Path(os.environ["GITHUB_OUTPUT"])
    if github_output is not None:
        _write_github_outputs(github_output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
