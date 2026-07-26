"""Compare equivalent baseline and optimized GitHub performance artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from aurora.infra.github_performance.benchmark import (
    ScientificOutputMismatch,
    compare_runs,
    write_benchmark_outputs,
)
from aurora.infra.github_performance.contracts import deep_thaw_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--optimized-dir", required=True, type=Path)
    parser.add_argument(
        "--environment-setup-benchmark",
        type=Path,
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = compare_runs(
            args.baseline_dir.resolve(),
            args.optimized_dir.resolve(),
            (
                args.environment_setup_benchmark.resolve()
                if args.environment_setup_benchmark is not None
                else None
            ),
        )
    except ScientificOutputMismatch as error:
        failure = {
            "schema_version": "1",
            "status": "failed",
            "scientific_outputs_equal": False,
            "timing_comparable": False,
            "failure_codes": ["SCIENTIFIC_OUTPUT_MISMATCH"],
            "error_type": type(error).__name__,
            "error": str(error),
        }
        for name, payload in (
            ("performance_final.json", failure),
            (
                "bottleneck_report.json",
                {
                    "schema_version": "1",
                    "status": "unavailable",
                    "reason": "scientific_outputs_not_equivalent",
                },
            ),
            ("github_performance_phase1_closure.json", failure),
        ):
            (output_dir / name).write_text(
                json.dumps(
                    payload,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
        print(json.dumps(failure, sort_keys=True, separators=(",", ":")))
        return 2
    for source in sorted(args.optimized_dir.resolve().iterdir()):
        if source.is_file():
            shutil.copy2(source, output_dir / source.name)
    if args.environment_setup_benchmark is not None:
        shutil.copy2(
            args.environment_setup_benchmark.resolve(),
            output_dir / "environment_setup_benchmark.json",
        )
    paths = write_benchmark_outputs(report, output_dir)
    print(
        json.dumps(
            {
                "status": report.status,
                "scientific_outputs_equal": (
                    report.scientific_outputs_equal
                ),
                "speedup": report.speedup,
                "outputs": [str(path) for path in paths],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    if report.status != "success":
        print(
            json.dumps(
                deep_thaw_json(report),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
