"""Build a controlled GitHub-only replan fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.replan_fixture import (
    build_replan_fixture,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-plan-root", type=Path, required=True)
    parser.add_argument("--source-state-root", type=Path, required=True)
    parser.add_argument("--source-attempts-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--artifact-prefix", required=True)
    args = parser.parse_args()
    require_github_execution("build replan fixture")
    report = build_replan_fixture(
        source_plan_root=args.source_plan_root,
        source_state_root=args.source_state_root,
        source_attempts_root=args.source_attempts_root,
        output_root=args.output_root,
        artifact_prefix=args.artifact_prefix,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
