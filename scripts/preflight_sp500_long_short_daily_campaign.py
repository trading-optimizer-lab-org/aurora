"""Fail-closed preflight for the frozen SP500 long/short daily campaign."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.infra.github_performance.preflight import validate_run_spec
from aurora.infra.sp500_long_short_daily.contracts import (
    CampaignPackage,
    LockedBoundaryError,
)
from aurora.infra.sp500_long_short_daily.data import (
    DataGateError,
    load_state_street_distributions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign = repo / "campaigns" / "sp500_long_short_daily"
    issues: list[str] = []

    package = CampaignPackage.load(
        campaign / "research_input",
        campaign
        / "input_package"
        / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )
    spec_report = validate_run_spec(
        repo / "config" / "sp500_long_short_daily_train_v3.yaml"
    )
    if not spec_report.valid:
        issues.extend(
            f"RUN_SPEC:{item.code}" for item in spec_report.violations
        )

    sponsor_path = (
        campaign
        / "official_inputs"
        / "state_street_spy_distributions_through_2010.csv"
    )
    try:
        load_state_street_distributions(
            sponsor_path,
            "1993-01-22",
            "2010-12-31",
            split="train",
        )
    except (DataGateError, LockedBoundaryError) as exc:
        issues.append(str(exc))
    if not os.environ.get("FRED_API_KEY", "").strip():
        issues.append("FRED_API_KEY_REQUIRED_FOR_INITIAL_RELEASE_VINTAGES")

    workflow = (
        repo / ".github" / "workflows" / "sp500-long-short-daily-campaign.yml"
    )
    workflow_text = workflow.read_text(encoding="utf-8")
    if "C:\\" in workflow_text:
        issues.append("WINDOWS_PATH_IN_GITHUB_WORKFLOW")
    if "self-hosted" in workflow_text:
        issues.append("SELF_HOSTED_RUNNER_FORBIDDEN")

    report = {
        "schema_version": "1",
        "campaign_id": "sp500_long_short_daily_zero_cost_v1",
        "status": "PASS" if not issues else "TECHNICAL_FAILURE_INPUTS",
        "candidate_count": len(package.candidates),
        "family_count": len({row["family"] for row in package.candidates}),
        "feature_count": len(package.features),
        "benchmark_count": 5,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "locked_opened": False,
        "performance_calculated": False,
        "issues": sorted(set(issues)),
    }
    (output / "preflight_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "RESULT_STATUS.md").write_text(
        "# Preflight result\n\n"
        f"Status: `{report['status']}`\n\n"
        + ("No blocking issues.\n" if not issues else "\n".join(f"- `{issue}`" for issue in sorted(set(issues))) + "\n"),
        encoding="utf-8",
    )
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
