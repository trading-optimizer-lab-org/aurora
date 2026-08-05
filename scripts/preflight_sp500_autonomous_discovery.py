"""Fail-closed, lightweight preflight for autonomous SPY discovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.infra.github_performance.preflight import load_github_yaml, validate_run_spec
from aurora.infra.sp500_autonomous_discovery.contracts import (
    LOCKED_START,
    TRAIN_END,
    VALIDATION_END,
    VALIDATION_START,
    boundary_payload,
)
from aurora.infra.sp500_autonomous_discovery.registry import generate_candidates


def _workflow_checks(path: Path) -> dict[str, bool]:
    text = path.read_text(encoding="utf-8")
    return {
        "no_windows_paths": "C:\\" not in text and "C:/" not in text,
        "no_self_hosted": "self-hosted" not in text,
        "github_actions_only": "runs-on: ubuntu-24.04" in text and "actions/checkout@" in text,
        "locked_boundary_in_workflow": LOCKED_START in text,
        "validation_end_in_workflow": VALIDATION_END in text,
    }


def run(repo_root: Path, output_dir: Path) -> dict[str, object]:
    if os.environ.get("GITHUB_ACTIONS", "false").lower() != "true":
        raise RuntimeError("GITHUB_ACTIONS_REQUIRED_FOR_CAMPAIGN_PREFLIGHT")
    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = repo_root / "config" / "sp500_autonomous_discovery.yaml"
    workflow_path = repo_root / ".github" / "workflows" / "sp500-autonomous-discovery.yml"
    payload = load_github_yaml(spec_path)
    report = validate_run_spec(spec_path)
    if not report.valid:
        raise RuntimeError(
            "RUN_SPEC_INVALID:" + ";".join(item.code for item in report.violations)
        )
    candidates = generate_candidates(0, count=8)
    checks = {
        "run_spec_valid": report.valid,
        "train_end": payload["policy"]["train_end"] == TRAIN_END,
        "validation_window": (
            payload["policy"]["validation_start"] == VALIDATION_START
            and payload["policy"]["validation_end"] == VALIDATION_END
        ),
        "locked_closed": payload["policy"]["locked_opened"] is False,
        "zero_costs": payload["data"]["cash_yield_policy"] == "no cash state",
        "candidate_contracts": all(
            row["position_values"] == [-1, 1]
            and row["locked_boundary"] == ">=2021-01-01 unopened"
            for row in candidates
        ),
        "candidate_ids_unique": len({row["strategy_id"] for row in candidates}) == len(candidates),
        "candidate_hashes_unique": len({row["canonical_hash"] for row in candidates}) == len(candidates),
    }
    checks.update({f"workflow_{key}": value for key, value in _workflow_checks(workflow_path).items()})
    if not all(checks.values()):
        failed = [key for key, value in checks.items() if not value]
        raise RuntimeError("PREFLIGHT_CHECK_FAILED:" + ",".join(failed))
    result = {
        "schema_version": "1",
        "campaign_id": "sp500-autonomous-discovery",
        "checks": checks,
        "spec_hash": report.spec_hash,
        "sample_candidate_count": len(candidates),
        "previous_trial_count": 312,
        **boundary_payload(),
        "github_only": True,
        "local_runs_allowed": False,
    }
    (output_dir / "preflight_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.repo_root, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
