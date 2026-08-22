"""Create or verify one exact catalog worker-failure receipt."""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_worker_failure import (
    CatalogWorkerFailureReceiptV1,
    build_catalog_worker_failure_receipt,
    worker_failure_artifact_name,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--execution-plan-sha256", required=True)
    parser.add_argument("--protected-commit-sha", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--stage")
    parser.add_argument("--reason-code")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--exception-type")
    parser.add_argument("--normalized-frame")
    parser.add_argument("--source-error-code")
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


def _validate_binding(
    receipt: CatalogWorkerFailureReceiptV1,
    args: argparse.Namespace,
) -> None:
    expected = {
        "authority_id": args.authority_id,
        "campaign_id": args.campaign_id,
        "execution_plan_sha256": args.execution_plan_sha256,
        "protected_commit_sha": args.protected_commit_sha,
        "worker_id": args.worker_id,
        "attempt_id": args.attempt_id,
    }
    if any(getattr(receipt, key) != value for key, value in expected.items()):
        raise SystemExit("CATALOG_WORKER_FAILURE_BINDING_INVALID")


def main() -> int:
    args = _parser().parse_args()
    if args.existing is not None:
        if args.stage is not None or args.reason_code is not None:
            raise SystemExit("CATALOG_WORKER_FAILURE_MODE_INVALID")
        receipt = CatalogWorkerFailureReceiptV1.model_validate_json(
            args.existing.read_text(encoding="utf-8")
        )
        _validate_binding(receipt, args)
    else:
        if args.stage is None or args.reason_code is None:
            raise SystemExit("CATALOG_WORKER_FAILURE_MODE_INVALID")
        receipt = build_catalog_worker_failure_receipt(
            authority_id=args.authority_id,
            campaign_id=args.campaign_id,
            execution_plan_sha256=args.execution_plan_sha256,
            protected_commit_sha=args.protected_commit_sha,
            worker_id=args.worker_id,
            attempt_id=args.attempt_id,
            stage=args.stage,
            reason_code=args.reason_code,
            exit_code=args.exit_code,
            exception_type=args.exception_type,
            normalized_frame=args.normalized_frame,
            source_error_code=args.source_error_code,
            created_at=datetime.now(UTC),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.existing is not None and args.existing.resolve() != args.output.resolve():
        shutil.copyfile(args.existing, args.output)
    else:
        args.output.write_text(receipt.model_dump_json() + "\n", encoding="utf-8")
    artifact_name = worker_failure_artifact_name(
        execution_plan_sha256=receipt.execution_plan_sha256,
        worker_id=receipt.worker_id,
        attempt_id=receipt.attempt_id,
    )
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"failure_artifact={artifact_name}\n")
            output.write(f"failure_fingerprint={receipt.failure_fingerprint}\n")
            output.write(f"failure_reason_code={receipt.reason_code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
