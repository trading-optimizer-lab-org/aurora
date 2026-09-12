"""Seal only an unknown setup failure when the offline runtime never activated.

This producer intentionally uses only the standard library. Its output remains
subject to CatalogWorkerFailureReceiptV1 validation by the recovery consumer;
it cannot label a failure transient or authorize a retry.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def _sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(
        payload, allow_nan=False, ensure_ascii=True,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--execution-plan-sha256", required=True)
    parser.add_argument("--protected-commit-sha", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if (
        not 1 <= len(args.authority_id) <= 96
        or not 1 <= len(args.campaign_id) <= 96
        or not re.fullmatch(r"[0-9a-f]{64}", args.execution_plan_sha256)
        or not re.fullmatch(r"[0-9a-f]{40}", args.protected_commit_sha)
        or not 0 <= args.worker_id <= 359
        or not 1 <= len(args.attempt_id) <= 220
        or not args.attempt_id.startswith(
            f"{args.authority_id}:worker:{args.worker_id:03d}:"
        )
    ):
        parser.error("CATALOG_WORKER_FAILURE_BINDING_INVALID")
    fingerprint = _sha256({
        "schema_version": "catalog-failure-fingerprint-v1",
        "failure_class": "unknown",
        "reason_code": "UNKNOWN_WORKER_FAILURE",
        "stage": "setup",
        "logical_scope_id": f"worker:{args.worker_id}",
        "exit_code": 1,
        "exception_type": "workflowstepfailure",
        "normalized_frame": None,
    })
    payload: dict[str, object] = {
        "schema_version": "catalog-worker-failure-v1",
        "authority_id": args.authority_id,
        "campaign_id": args.campaign_id,
        "execution_plan_sha256": args.execution_plan_sha256,
        "protected_commit_sha": args.protected_commit_sha,
        "worker_id": args.worker_id,
        "attempt_id": args.attempt_id,
        "stage": "setup",
        "reason_code": "UNKNOWN_WORKER_FAILURE",
        "failure_class": "unknown",
        "failure_fingerprint": fingerprint,
        "exit_code": 1,
        "exception_type": "WorkflowStepFailure",
        "normalized_frame": None,
        "source_error_code": "WORKER_STEP_FAILED_WITHOUT_CLASSIFIED_RECEIPT",
        "retry_after_seconds": None,
        "rate_limit_reset": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_opened": False,
        "locked_opened": False,
    }
    payload["receipt_sha256"] = _sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, allow_nan=False) + "\n", encoding="utf-8")
    attempt_sha256 = hashlib.sha256(args.attempt_id.encode("utf-8")).hexdigest()
    artifact = (f"catalog-failure-attempt-{args.execution_plan_sha256[:16]}-"
                f"{args.worker_id:03d}-{attempt_sha256[:16]}")
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"failure_artifact={artifact}\n")
            output.write(f"failure_fingerprint={fingerprint}\n")
            output.write("failure_reason_code=UNKNOWN_WORKER_FAILURE\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
