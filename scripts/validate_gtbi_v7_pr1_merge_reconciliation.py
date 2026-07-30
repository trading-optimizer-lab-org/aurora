"""Validate the checked-in GTBI V7 PR-1 merge reconciliation receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.post_merge import (  # noqa: E402
    validate_pr1_merge_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    receipt = validate_pr1_merge_receipt(args.repository_root)
    print(
        json.dumps(
            {
                "formal_effect": receipt["formal_effect"],
                "merge_sha": receipt["merge_sha"],
                "successful_ci_runs": len(receipt["ci_runs"]),
                "successful_matrix_jobs": len(receipt["test_matrix"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
