"""Run one recipe-worker segment and seal any caught failure before exiting."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_worker_failure import (
    build_catalog_worker_failure_receipt,
    classify_worker_exception,
    normalized_exception_frame,
)
from scripts.run_sp500_optimized_recipe_worker import main as worker_main


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure-receipt", type=Path, required=True)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--execution-plan-sha256", required=True)
    parser.add_argument("--protected-commit-sha", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--stage", default="recipe_worker")
    parser.add_argument("worker_args", nargs=argparse.REMAINDER)
    return parser


def _write_receipt(path: Path, receipt_json: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(receipt_json + "\n", encoding="utf-8")
    temporary.replace(path)


def execute_guarded(
    argv: Sequence[str],
    *,
    run_worker: Callable[[Sequence[str]], int] = worker_main,
    created_at: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    worker_args = list(args.worker_args)
    if worker_args[:1] == ["--"]:
        worker_args = worker_args[1:]
    try:
        result = run_worker(worker_args)
        if result == 0:
            return 0
        raise SystemExit(result)
    except (Exception, SystemExit) as exc:
        reason_code, exit_code, exception_type = classify_worker_exception(exc)
        receipt = build_catalog_worker_failure_receipt(
            authority_id=args.authority_id,
            campaign_id=args.campaign_id,
            execution_plan_sha256=args.execution_plan_sha256,
            protected_commit_sha=args.protected_commit_sha,
            worker_id=args.worker_id,
            attempt_id=args.attempt_id,
            stage=args.stage,
            reason_code=reason_code,
            exit_code=exit_code,
            exception_type=exception_type,
            normalized_frame=normalized_exception_frame(exc),
            source_error_code=(
                str(exc.code).strip().upper()
                if isinstance(exc, SystemExit) and isinstance(exc.code, str)
                else None
            ),
            created_at=created_at or datetime.now(UTC),
        )
        _write_receipt(args.failure_receipt, receipt.model_dump_json())
        return exit_code or 1


def main(argv: Sequence[str] | None = None) -> int:
    return execute_guarded(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
