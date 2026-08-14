"""Require exact normalized results from independent GitHub runners."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_CROSS_RUNNER_DETERMINISM_REDUCE")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-replicas", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(path.read_text("utf-8")) for path in sorted(args.root.rglob("report.json"))]
    if len(reports) != args.expected_replicas:
        raise ValueError("CROSS_RUNNER_REPORT_COUNT_MISMATCH")
    by_key: dict[str, set[str]] = {}
    for report in reports:
        if report.get("validation_opened") is not False or report.get("locked_opened") is not False:
            raise ValueError("CROSS_RUNNER_BOUNDARY_OPEN")
        for row in report.get("results", []):
            by_key.setdefault(str(row["cache_key_sha256"]), set()).add(
                str(row["result_sha256"])
            )
    conflicts = {key: sorted(values) for key, values in by_key.items() if len(values) != 1}
    summary = {
        "schema_version": 1,
        "replica_count": len(reports),
        "case_count": len(by_key),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "passed": not conflicts,
        "validation_opened": False,
        "locked_opened": False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(summary, sort_keys=True))
    if conflicts:
        raise ValueError(f"CROSS_RUNNER_DETERMINISM_CONFLICTS:{len(conflicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
