#!/usr/bin/env python3
"""Create one content-hashed runtime audit from fixed local GitHub snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_runtime_audit import (
    allowed_skips_from_verified_outputs,
    build_catalog_runtime_audit,
)


def _json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_RUNTIME_AUDIT_INPUT_INVALID")
    return json.loads(path.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify one catalog runtime.")
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--verified-skip-evidence", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--jobs-confirmation", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--artifacts-confirmation", required=True, type=Path)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--components-reused", type=int)
    parser.add_argument("--components-computed-once", type=int)
    parser.add_argument("--selective-retries", type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("CATALOG_RUNTIME_AUDIT_OUTPUT_EXISTS")
        binding = _json(args.binding)
        run = _json(args.run)
        repository = _json(args.repository)
        if not isinstance(binding, dict) or not isinstance(run, dict) or not isinstance(repository, dict):
            raise ValueError("CATALOG_RUNTIME_AUDIT_INPUT_INVALID")
        receipt = build_catalog_runtime_audit(
            allowed_skipped_job_names=allowed_skips_from_verified_outputs(
                _json(args.verified_skip_evidence), binding=binding,
            ),
            binding=binding,
            run=run,
            repository=repository,
            jobs_pages=_json(args.jobs),
            jobs_confirmation_pages=_json(args.jobs_confirmation),
            artifacts_pages=_json(args.artifacts),
            artifacts_confirmation_pages=_json(args.artifacts_confirmation),
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            audited_at=datetime.fromisoformat(args.audited_at.replace("Z", "+00:00")),
            components_reused=args.components_reused,
            components_computed_once=args.components_computed_once,
            selective_retries=args.selective_retries,
        )
        args.output.write_bytes(canonical_model_bytes(receipt) + b"\n")
        print(receipt.receipt_sha256)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
