"""Validate the exact 100-job GTBI V7 smoke without expanding aliases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_new_reference.campaign import CAMPAIGN_ID, HISTORICAL_EXCLUSION_START
from infra.gtbi_v7_new_reference.runner import scientific_output_digest
from infra.gtbi_v7_readiness.canonical import canonical_bytes


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return dict(value)


def validate_smoke(root: Path, output_path: Path, *, expected_workers: int = 100) -> dict[str, Any]:
    source = Path(root)
    receipts: dict[int, tuple[dict[str, Any], Path]] = {}
    for path in sorted(source.rglob("v7_worker_receipt.json")):
        receipt = _json(path)
        worker_id = int(receipt.get("worker_id", -1))
        if worker_id in receipts:
            raise ValueError(f"duplicate smoke worker {worker_id}")
        receipts[worker_id] = (receipt, path.parent)
    expected = set(range(int(expected_workers)))
    if set(receipts) != expected:
        raise ValueError(f"smoke worker membership mismatch: missing={sorted(expected - set(receipts))}")
    fingerprints = {str(receipt["campaign_fingerprint"]) for receipt, _ in receipts.values()}
    if len(fingerprints) != 1:
        raise ValueError("smoke workers used different campaign fingerprints")
    canonical_terminal_count = 0
    evaluated = 0
    early = 0
    for worker_id, (receipt, worker_root) in receipts.items():
        if receipt.get("locked_authorized") is not False or receipt.get("locked_data_accessed") is not False:
            raise ValueError(f"smoke worker {worker_id} reports locked access")
        if receipt.get("scientific_output_digest") != scientific_output_digest(worker_root):
            raise ValueError(f"smoke worker {worker_id} scientific digest mismatch")
        summary = _json(worker_root / "worker_summary.json")
        failure = sum(
            int(summary.get(name, 0) or 0)
            for name in (
                "total_strategies_timed_out",
                "total_strategies_runtime_error",
                "total_strategies_unsupported",
                "total_strategies_slow_deferred",
            )
        )
        if failure:
            raise ValueError(f"smoke worker {worker_id} contains failures")
        worker_evaluated = int(summary.get("total_strategies_evaluated", 0) or 0)
        worker_early = int(summary.get("total_strategies_early_rejected", 0) or 0)
        canonical = int(summary.get("canonical_group_count", 0) or 0)
        if worker_evaluated + worker_early != canonical:
            raise ValueError(f"smoke worker {worker_id} terminal count mismatch")
        canonical_terminal_count += canonical
        evaluated += worker_evaluated
        early += worker_early
    result = {
        "schema_version": "gtbi_v7_new_reference_smoke_validation_v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": next(iter(fingerprints)),
        "valid": True,
        "worker_count": int(expected_workers),
        "worker_ids": sorted(receipts),
        "canonical_terminal_count": canonical_terminal_count,
        "strategies_evaluated": evaluated,
        "strategies_early_rejected": early,
        "strategies_timed_out": 0,
        "strategies_runtime_error": 0,
        "strategies_unsupported": 0,
        "strategies_slow_deferred": 0,
        "historical_exclusion_start": HISTORICAL_EXCLUSION_START,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_only_run": True,
    }
    result["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(result)).hexdigest()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_bytes(result) + b"\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-workers", type=int, default=100)
    args = parser.parse_args(argv)
    result = validate_smoke(args.input_root, args.output, expected_workers=args.expected_workers)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
