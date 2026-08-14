"""Diagnose conflicting DEHB evaluation cache evidence in GitHub Actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_global_merge import (
    diagnose_evaluation_result_conflicts,
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_CACHE_CONFLICT_DIAGNOSTIC")
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-key-sha256")
    args = parser.parse_args()

    report = diagnose_evaluation_result_conflicts(
        args.worker_root,
        cache_key_sha256=args.cache_key_sha256,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
