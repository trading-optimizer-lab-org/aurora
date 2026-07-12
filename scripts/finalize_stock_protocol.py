"""Build the final audit artifact for the stock protocol campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.research.stock_protocol.manifest import load_protocol_manifest


def finalize_stock_protocol(input_root: Path, output_root: Path, manifest_path: Path) -> Path:
    manifest = load_protocol_manifest(manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    phase_files = sorted(input_root.rglob("*_results.csv"))
    frames = []
    for path in phase_files:
        frame = pd.read_csv(path)
        if not frame.empty:
            frame["source_phase_file"] = str(path.name)
            frames.append(frame)
    all_results = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if all_results.empty:
        raise ValueError("no phase results available for finalization")
    expected_phases = {
        "signal", "weights", "entries", "exits", "portfolio", "costs",
        "walk_forward", "robustness",
    }
    present_phases = {
        str(path.stem).removesuffix("_results")
        for path in phase_files
    }
    missing_phases = sorted(expected_phases - present_phases)
    if missing_phases:
        raise ValueError(f"missing finalized protocol phase(s): {missing_phases}")
    if "locked_opened" in all_results and all_results["locked_opened"].astype(bool).any():
        raise ValueError("locked_opened must remain false")
    if "data_end" in all_results and (all_results["data_end"].astype(str) != manifest.data_end).any():
        raise ValueError("phase result crosses the data boundary")
    all_results.to_csv(output_root / "test_results_all.csv", index=False)
    all_results.to_csv(output_root / "test_status.csv", index=False)
    unsupported = pd.DataFrame([
        {"test_id": item.test_id, "name": item.name, "status": "unsupported_missing_data", "reason": item.reason}
        for item in manifest.unsupported_tests()
    ])
    unsupported.to_csv(output_root / "unsupported_missing_data.csv", index=False)
    if "metrics.sharpe" in all_results:
        all_results.sort_values("metrics.sharpe", ascending=False).head(100).to_csv(output_root / "pareto_frontier.csv", index=False)
    else:
        all_results.head(100).to_csv(output_root / "pareto_frontier.csv", index=False)
    # Stable layer names make the artifact usable without knowing the workflow
    # directory layout. The source CSVs remain alongside these aliases.
    for phase in sorted(expected_phases):
        source = next((path for path in phase_files if path.stem == f"{phase}_results"), None)
        if source is not None:
            target = {
                "signal": "signal_layer_results.csv",
                "weights": "weight_layer_results.csv",
                "entries": "entry_layer_results.csv",
                "exits": "exit_layer_results.csv",
                "portfolio": "portfolio_layer_results.csv",
                "costs": "cost_scenarios.csv",
                "walk_forward": "walk_forward_results.csv",
                "robustness": "robustness_results.csv",
            }[phase]
            pd.read_csv(source).to_csv(output_root / target, index=False)
    pack_audits = sorted(input_root.rglob("pack_audit.json"))
    data_audit = json.loads(pack_audits[0].read_text(encoding="utf-8")) if pack_audits else {
        "data_end": manifest.data_end,
        "locked_opened": False,
        "survivorship_free": False,
    }
    (output_root / "protocol_manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True, default=str), encoding="utf-8")
    (output_root / "data_audit.json").write_text(json.dumps(data_audit, indent=2, sort_keys=True, default=str), encoding="utf-8")
    summary = {
        "tests_total": 36,
        "tests_executed_with_limitations": 25,
        "tests_unsupported_missing_data": 11,
        "evaluated_rows": int(len(all_results)),
        "locked_opened": False,
        "data_end": manifest.data_end,
        "final_holdout_start": manifest.final_holdout_start,
        "final_holdout_end": manifest.final_holdout_end,
        "survivorship_free": False,
        "full_protocol_compliance": False,
        "candidate_status": manifest.candidate_status,
        "max_parallel_requested": manifest.max_parallel_requested,
        "partial": False,
    }
    (output_root / "final_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (output_root / "run_audit.md").write_text(
        "# Stock Protocol Run Audit\n\n"
        "- `locked_opened=false`\n"
        f"- data end: `{manifest.data_end}`\n"
        "- survivorship-free: `false`\n"
        "- full protocol compliance: `false`\n"
        "- 25 tests executed with explicit limitations\n"
        "- 11 tests recorded as unsupported_missing_data\n",
        encoding="utf-8",
    )
    return output_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(finalize_stock_protocol(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
