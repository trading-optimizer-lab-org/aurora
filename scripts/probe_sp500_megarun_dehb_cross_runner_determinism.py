"""Replay every material cache conflict on one independent GitHub runner."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import load_and_validate_campaign_contract
from aurora.infra.sp500_megarun.dehb_evaluation_cache import scientific_result_sha256
from aurora.infra.sp500_megarun.dehb_lane_registry import default_lane_configurations
from aurora.infra.sp500_megarun.dehb_numeric_runtime import capture_numeric_runtime_report
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import evaluate_physical_lane_candidate
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract


def _material_cases(path: Path) -> list[dict[str, object]]:
    report = json.loads(path.read_text("utf-8"))
    conflicts = report.get("conflicts") if isinstance(report, dict) else None
    if not isinstance(conflicts, list):
        raise ValueError("DETERMINISM_PROBE_CONFLICT_REPORT_INVALID")
    cases: list[dict[str, object]] = []
    seen: set[str] = set()
    for conflict in conflicts:
        if not isinstance(conflict, dict) or conflict.get("classification") != "material":
            continue
        key = str(conflict.get("cache_key_sha256", ""))
        sources = conflict.get("representative_sources")
        if len(key) != 64 or key in seen or not isinstance(sources, list) or not sources:
            raise ValueError("DETERMINISM_PROBE_MATERIAL_CASE_INVALID")
        source = sources[0]
        if not isinstance(source, dict) or not isinstance(source.get("configuration"), dict):
            raise ValueError("DETERMINISM_PROBE_MATERIAL_SOURCE_INVALID")
        island_id = str(source.get("island_id", ""))
        cases.append(
            {
                "cache_key_sha256": key,
                "lane_id": island_id.split("-", 1)[0],
                "fidelity": int(source["fidelity"]),
                "configuration": dict(source["configuration"]),
            }
        )
        seen.add(key)
    if len(cases) != int(report.get("material_conflict_count", -1)) or not cases:
        raise ValueError("DETERMINISM_PROBE_MATERIAL_COUNT_MISMATCH")
    return cases


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_CROSS_RUNNER_DETERMINISM_PROBE")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--conflict-report", type=Path, required=True)
    parser.add_argument("--replica", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    numeric_runtime = capture_numeric_runtime_report()

    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
    pack = args.runtime_input_pack.resolve()
    runtime_manifest = json.loads((pack / "runtime_input_manifest.json").read_text("utf-8"))
    verify_runtime_input_pack(
        pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(campaign),
        expected_aggregate_sha256=str(runtime_manifest["aggregate_sha256"]),
    )
    defaults = default_lane_configurations(feature_contract)
    fidelity_years = {
        int(spec.budget): tuple(int(year) for year in spec.years)
        for spec in campaign.fidelities
    }
    results: list[dict[str, object]] = []
    for case in _material_cases(args.conflict_report):
        result = evaluate_physical_lane_candidate(
            case["configuration"],
            float(case["fidelity"]),
            lane_id=str(case["lane_id"]),
            train_snapshot=str(pack / "train_snapshot_1993_2010"),
            expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
            expected_spy_sha256=campaign.train_spy_sha256,
            default_configurations=defaults,
            baseline_feature_dirs={
                "price": str(pack / "baseline_price"),
                "market": str(pack / "baseline_market"),
                "macro": str(pack / "baseline_macro"),
            },
            fidelity_years=fidelity_years,
            allowed_end=campaign.search_end,
        )
        results.append(
            {
                **case,
                "result_sha256": scientific_result_sha256(result),
                "position_fingerprint": result["info"]["position_fingerprint"],
                "strategy_fingerprint": result["info"]["strategy_fingerprint"],
                "fitness": result["fitness"],
                "weekly_spy_beat_rate": result["info"]["weekly_spy_beat_rate"],
                "weeks_beating_spy": result["info"]["weeks_beating_spy"],
            }
        )
    report = {
        "schema_version": 1,
        "replica": args.replica,
        "github_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "github_job": os.environ.get("GITHUB_JOB", ""),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "numpy_version": numeric_runtime["numpy_version"],
        "numeric_runtime_profile_sha256": numeric_runtime["profile_sha256"],
        "numeric_runtime": numeric_runtime,
        "case_count": len(results),
        "results": results,
        "validation_opened": False,
        "locked_opened": False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
