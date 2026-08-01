"""Verify benchmark and optional smoke evidence against one GTBI V7 plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from infra.gtbi_v7_new_reference.campaign import (
    validate_benchmark_evidence,
    validate_smoke_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--smoke-validation", type=Path)
    args = parser.parse_args(argv)
    if args.benchmark is None and args.smoke_validation is None:
        parser.error("at least one of --benchmark or --smoke-validation is required")
    result = {}
    if args.benchmark is not None:
        benchmark = validate_benchmark_evidence(
            campaign_manifest_path=args.campaign_manifest,
            benchmark_path=args.benchmark,
        )
        result.update(
            {
                "benchmark_valid": True,
                "campaign_fingerprint": benchmark["campaign_fingerprint"],
                "selected_processes_per_runner": benchmark["selected_processes_per_runner"],
                "selected_symbol_workers_per_process": benchmark[
                    "selected_symbol_workers_per_process"
                ],
                "effective_cpu_count": benchmark["effective_cpu_count"],
            }
        )
    if args.smoke_validation is not None:
        smoke = validate_smoke_evidence(
            campaign_manifest_path=args.campaign_manifest,
            smoke_validation_path=args.smoke_validation,
        )
        result["smoke_valid"] = True
        result["smoke_worker_count"] = smoke["worker_count"]
        result.setdefault("campaign_fingerprint", smoke["campaign_fingerprint"])
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
