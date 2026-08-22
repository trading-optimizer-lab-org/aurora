#!/usr/bin/env python3
"""Prepare bounded catalog terminal evidence before the fresh controls audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_terminal_adapter import (
    prepare_terminal_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and bind fixed catalog evidence before terminal audit."
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--admission-root", required=True, type=Path)
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--routing-root", required=True, type=Path)
    parser.add_argument("--admission-controls", required=True, type=Path)
    parser.add_argument("--engine-outcome-root", required=True, type=Path)
    parser.add_argument("--runtime-prepared-root", required=True, type=Path)
    parser.add_argument("--component-seal-root", required=True, type=Path)
    parser.add_argument("--final-root", required=True, type=Path)
    parser.add_argument("--science-root", required=True, type=Path)
    parser.add_argument("--runtime-audit-root", required=True, type=Path)
    parser.add_argument("--recovery-root", required=True, type=Path)
    parser.add_argument(
        "--engine-result",
        required=True,
        choices=("success", "failure", "cancelled", "skipped"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        index = prepare_terminal_evidence(
            repo_root=args.repo_root,
            admission_root=args.admission_root,
            sealed_plan=args.sealed_plan,
            routing_root=args.routing_root,
            admission_controls_path=args.admission_controls,
            engine_outcome_root=args.engine_outcome_root,
            runtime_prepared_root=args.runtime_prepared_root,
            component_seal_root=args.component_seal_root,
            final_root=args.final_root,
            science_root=args.science_root,
            runtime_audit_root=args.runtime_audit_root,
            recovery_root=args.recovery_root,
            engine_result=args.engine_result,
            output_dir=args.output_dir,
        )
        if args.github_output is not None:
            if args.github_output.is_symlink():
                raise ValueError("CATALOG_TERMINAL_GITHUB_OUTPUT_INVALID")
            values = {
                "protected_commit_sha": index["protected_commit_sha"],
                "controls_commit_sha": index.get(
                    "github_controls_commit_sha", index["protected_commit_sha"]
                ),
                "audit_context_sha256": index["audit_context_sha256"],
                "prepared_evidence_sha256": index["index_sha256"],
            }
            with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                for key, value in values.items():
                    stream.write(f"{key}={value}\n")
        print(
            json.dumps(
                {
                    "audit_context_sha256": index["audit_context_sha256"],
                    "index_sha256": index["index_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(f"CATALOG_TERMINAL_EVIDENCE_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
