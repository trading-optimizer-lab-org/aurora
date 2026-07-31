"""Validate every tracked GitHub workflow against Aurora adoption policy."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]

# Validate this exact checkout even when another Aurora worktree is the active
# editable install. Layout B maps the repository root to the ``aurora`` package.
source_spec = importlib.util.spec_from_file_location(
    "aurora",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
if source_spec is None:
    raise RuntimeError("cannot construct the source Aurora package spec")
source_package = importlib.util.module_from_spec(source_spec)
sys.modules["aurora"] = source_package
source_infra = ModuleType("aurora.infra")
source_infra.__path__ = [str(ROOT / "infra")]  # type: ignore[attr-defined]
sys.modules["aurora.infra"] = source_infra

from aurora.infra.github_performance.preflight import (  # noqa: E402
    classify_workflow,
    load_legacy_workflow_allowlist,
    load_legacy_workflow_migrations,
    validate_workflow_policy,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--allowlist",
        default="config/legacy_workflow_allowlist.json",
    )
    parser.add_argument(
        "--migrations",
        default="config/legacy_workflow_migrations.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    allowlist = load_legacy_workflow_allowlist(
        root / args.allowlist
    )
    migrations = load_legacy_workflow_migrations(
        root / args.migrations,
        root,
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
        classification = classify_workflow(
            path,
            allowlist,
            root,
            migrations,
        )
        violations = validate_workflow_policy(
            path,
            root,
            allowlist,
            migrations,
        )
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
