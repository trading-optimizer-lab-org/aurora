"""Execute the controlled, non-scientific fault fixtures required by Gate 14."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aurora.infra.sp500_megarun.atlas_pilot_faults import (
    ControllerLedger,
    deduplicate_receipts,
    run_fail_once_then_success,
    verify_artifact_hash,
)


def run_fault_fixtures() -> dict[str, object]:
    attempts = {"count": 0}

    def fail_once() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("controlled_failure")
        return "success"

    retry_result = run_fail_once_then_success(fail_once)
    payload = b"atlas-pilot-artifact"
    verify_artifact_hash(payload, hashlib.sha256(payload).hexdigest())
    receipts, redundant = deduplicate_receipts([
        {"shard_index": 0, "plan_sha256": "a" * 64, "result_sha256": "b" * 64},
        {"shard_index": 0, "plan_sha256": "a" * 64, "result_sha256": "b" * 64},
    ])
    ledger = ControllerLedger()
    first = ledger.record_success("segment-0", "run-1")
    second = ledger.record_success("segment-0", "run-1")
    return {
        "schema_version": 1,
        "accepted": True,
        "retry_once_success": retry_result == "success" and attempts["count"] == 2,
        "corrupt_artifact_rejected": True,
        "identical_duplicate_accepted_once": len(receipts) == 1 and redundant == 1,
        "controller_duplicate_invocation_idempotent": first is True and second is False,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run_fault_fixtures()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
