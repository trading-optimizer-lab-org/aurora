"""Fail-closed preflight for the frozen SP500 long/short daily V2 campaign."""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

from aurora.infra.github_performance.preflight import validate_run_spec
from aurora.infra.sp500_long_short_daily_v2.contracts import CampaignPackage
from aurora.infra.sp500_long_short_daily_v2.statistics import load_v1_evidence
from aurora.infra.sp500_long_short_daily_v2.workload import BENCHMARK_IDS, TRAIN_WORKLOAD


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign = repo / "campaigns" / "sp500_long_short_daily_v2"
    issues: list[str] = []
    package = CampaignPackage.load(
        campaign / "research_input",
        campaign / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_V2_NEW_STRATEGIES.zip",
    )
    spec = validate_run_spec(repo / "config" / "sp500_long_short_daily_v2_train_v3.yaml")
    if not spec.valid:
        issues.extend(f"RUN_SPEC:{row.code}" for row in spec.violations)
    try:
        v1_daily, v1_eligibility, _ = load_v1_evidence(
            campaign / "prior_campaign" / "sp500-ls-train-yahoo-fallback-r8-results.zip"
        )
        if v1_daily.loc[~v1_daily["unit_key"].astype(str).str.startswith("BENCHMARK::"), "unit_key"].nunique() != 65:
            issues.append("V1_DAILY_STREAM_COUNT")
        if len(v1_eligibility.loc[~v1_eligibility["unit_key"].astype(str).str.startswith("BENCHMARK::")]) != 168:
            issues.append("V1_DECLARED_COUNT")
    except Exception as exc:
        issues.append(f"V1_INGESTION:{type(exc).__name__}:{exc}")
    definitions = TRAIN_WORKLOAD._unit_definitions()
    if len(definitions) != 149 or len(BENCHMARK_IDS) != 5:
        issues.append("TERMINAL_UNIT_COUNT")
    workflow = repo / ".github" / "workflows" / "sp500-long-short-daily-v2-campaign.yml"
    text = workflow.read_text("utf-8")
    if "C:\\" in text:
        issues.append("WINDOWS_PATH_IN_WORKFLOW")
    if "self-hosted" in text:
        issues.append("SELF_HOSTED_RUNNER_FORBIDDEN")
    report = {
        "schema_version": "2",
        "campaign_id": "sp500_long_short_daily_zero_cost_v2_new_strategies",
        "status": "PASS" if not issues else "TECHNICAL_FAILURE_INPUTS",
        "candidate_count": len(package.candidates),
        "family_count": len({row["family"] for row in package.candidates}),
        "feature_count": len(package.features),
        "benchmark_count": len(BENCHMARK_IDS),
        "terminal_units": len(definitions),
        "cumulative_declared_trials": 312,
        "v1_daily_streams": 65,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "validation_opened": False,
        "locked_opened": False,
        "performance_calculated": False,
        "issues": sorted(set(issues)),
    }
    (output / "preflight_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "RESULT_STATUS.md").write_text(f"# Preflight result\n\nStatus: `{report['status']}`\n", encoding="utf-8")
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
