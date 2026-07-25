"""Validate every tracked GitHub workflow against Aurora adoption policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aurora.infra.github_performance.preflight import (
    classify_workflow,
    load_legacy_workflow_allowlist,
    validate_workflow_policy,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--allowlist",
        default="config/legacy_workflow_allowlist.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    allowlist = load_legacy_workflow_allowlist(
        root / args.allowlist
    )
    rows: list[dict[str, object]] = []
    invalid = False
    workflows = sorted(
        {
            *root.glob(".github/workflows/*.yml"),
            *root.glob(".github/workflows/*.yaml"),
        }
    )
    for path in workflows:
        classification = classify_workflow(path, allowlist, root)
        violations = validate_workflow_policy(path, root, allowlist)
        invalid = invalid or bool(violations)
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "classification": classification,
                "violations": [
                    {
                        "code": item.code,
                        "path": list(item.path),
                        "message": item.message,
                    }
                    for item in violations
                ],
            }
        )
    print(
        json.dumps(
            {
                "schema_version": "1",
                "valid": not invalid,
                "workflow_count": len(rows),
                "workflows": rows,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
