"""Verify 1/2/4 process equivalence and select the fastest equal workload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_new_reference.campaign import CAMPAIGN_ID
from infra.gtbi_v7_new_reference.runner import assert_batch_outputs_equal
from infra.gtbi_v7_readiness.canonical import canonical_bytes


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return dict(value)


def summarize(mode_roots: dict[int, Path], output_path: Path) -> dict[str, Any]:
    if set(mode_roots) != {1, 2, 4}:
        raise ValueError("benchmark requires exactly process modes 1, 2 and 4")
    equivalence = assert_batch_outputs_equal([mode_roots[mode] for mode in (1, 2, 4)])
    receipts = {
        mode: _json(Path(root) / "v7_batch_receipt.json") for mode, root in mode_roots.items()
    }
    fingerprints = {str(receipt.get("campaign_fingerprint") or "") for receipt in receipts.values()}
    memberships = {tuple(receipt.get("worker_ids") or []) for receipt in receipts.values()}
    cpu_counts = {int(receipt.get("effective_cpu_count", 0)) for receipt in receipts.values()}
    if (
        len(fingerprints) != 1
        or "" in fingerprints
        or len(memberships) != 1
        or len(cpu_counts) != 1
        or min(cpu_counts) <= 0
    ):
        raise ValueError("benchmark modes do not cover one identical campaign workload")
    for mode, receipt in receipts.items():
        if int(receipt.get("processes_per_runner", 0)) != mode:
            raise ValueError(f"benchmark receipt mode mismatch: {mode}")
        if receipt.get("locked_data_accessed") is not False:
            raise ValueError("benchmark reports locked access")
        expected_symbol_workers = 1
        if int(receipt.get("symbol_workers_per_process", 0)) != expected_symbol_workers:
            raise ValueError(f"benchmark receipt symbol-worker mismatch: {mode}")
    selected = min(receipts, key=lambda mode: float(receipts[mode]["wall_seconds"]))
    reference = float(receipts[1]["wall_seconds"])
    selected_seconds = float(receipts[selected]["wall_seconds"])
    reduction = 0.0 if reference <= 0 else 100.0 * (reference - selected_seconds) / reference
    result = {
        "schema_version": "gtbi_v7_new_reference_benchmark_v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": next(iter(fingerprints)),
        "equivalent": bool(equivalence["equivalent"]),
        "worker_ids": list(next(iter(memberships))),
        "mode_receipts": {str(mode): receipts[mode] for mode in (1, 2, 4)},
        "worker_scientific_digests": equivalence["worker_scientific_digests"],
        "selected_processes_per_runner": int(selected),
        "selected_symbol_workers_per_process": int(receipts[selected]["symbol_workers_per_process"]),
        "effective_cpu_count": int(next(iter(cpu_counts))),
        "reference_one_process_wall_seconds": reference,
        "selected_wall_seconds": selected_seconds,
        "equal_workload_runtime_reduction_pct": reduction,
        "queue_time_included": False,
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
    parser.add_argument("--mode-1", type=Path, required=True)
    parser.add_argument("--mode-2", type=Path, required=True)
    parser.add_argument("--mode-4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = summarize({1: args.mode_1, 2: args.mode_2, 4: args.mode_4}, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
