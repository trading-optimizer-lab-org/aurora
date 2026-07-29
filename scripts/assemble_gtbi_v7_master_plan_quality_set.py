"""Assemble and verify exactly three independent GTBI V7 audit receipts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    git_blob_id,
    raw_sha256,
)
from infra.gtbi_v7_readiness.quality import validate_quality_evidence  # noqa: E402


def _canonical_load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path} is not canonical JSON plus one LF")
    return payload


def _canonical_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def assemble(
    *,
    repository_root: Path,
    receipt_paths: list[Path],
    public_key_record_paths: list[Path],
    output_directory: Path,
) -> dict:
    if len(receipt_paths) != 3 or len(public_key_record_paths) != 3:
        raise ValueError("exactly three receipt and three public-key files are required")
    receipts = [_canonical_load(path) for path in receipt_paths]
    receipts.sort(key=lambda row: row["signed_payload"]["round_sequence"])
    if [row["signed_payload"]["round_sequence"] for row in receipts] != [1, 2, 3]:
        raise ValueError("receipt round_sequence values must be exactly 1, 2, 3")
    actor_ids = [row["signed_payload"]["auditor_actor_id"] for row in receipts]
    key_ids = [row["signing_key_id"] for row in receipts]
    if len(set(actor_ids)) != 3 or len(set(key_ids)) != 3:
        raise ValueError("auditor actor IDs and signing-key IDs must be distinct")
    previous_end: datetime | None = None
    for receipt in receipts:
        payload = receipt["signed_payload"]
        started = datetime.fromisoformat(payload["started_at_utc"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(payload["ended_at_utc"].replace("Z", "+00:00"))
        if previous_end is not None and started <= previous_end:
            raise ValueError("audit rounds overlap or are not strictly sequential")
        previous_end = ended

    key_records = [_canonical_load(path) for path in public_key_record_paths]
    key_by_id = {row["signing_key_id"]: row for row in key_records}
    if len(key_by_id) != 3 or set(key_by_id) != set(key_ids):
        raise ValueError("public-key records do not match the three receipts")
    ordered_keys = [key_by_id[key_id] for key_id in key_ids]
    trusted_keys = {
        "schema_version": "master_plan_audit_trusted_keys_v1",
        "keys": ordered_keys,
    }

    first = receipts[0]["signed_payload"]
    plan_path = repository_root / "docs/plans/gtbi-v7-master-plan.md"
    plan_bytes = plan_path.read_bytes()
    identity = {
        "reviewed_master_plan_sha256": raw_sha256(plan_bytes),
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
    }
    for receipt in receipts:
        for field, expected in identity.items():
            if receipt["signed_payload"][field] != expected:
                raise ValueError(f"receipt {field} does not match current plan")
    receipt_set = {
        "schema_version": "master_plan_quality_receipt_set_v1",
        **identity,
        "canonical_serialization_profile_digest": first[
            "canonical_serialization_profile_digest"
        ],
        "hash_domain_registry_digest": first["hash_domain_registry_digest"],
        "scope_manifest_digest": first["scope_manifest_digest"],
        "ordered_receipt_digests": [row["receipt_digest"] for row in receipts],
        "auditor_actor_ids": actor_ids,
        "signing_key_ids": key_ids,
        "pairwise_actor_independence_verified": True,
        "pairwise_key_independence_verified": True,
        "non_author_non_implementer_verified": True,
        "strict_nonoverlap_verified": True,
        "complete_scope_verified": True,
        "all_results_clean": True,
    }
    receipt_set["master_plan_quality_receipt_set_digest"] = domain_digest(
        "GTBI_MASTER_PLAN_QUALITY_RECEIPT_SET_V1", receipt_set
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    targets = [
        output_directory / "master_plan_quality_receipts.jsonl",
        output_directory / "master_plan_quality_receipt_set.json",
        output_directory / "master_plan_audit_trusted_keys.json",
    ]
    if any(path.exists() for path in targets):
        raise FileExistsError("refusing to overwrite an existing quality package")
    targets[0].write_bytes(
        b"".join(canonical_bytes(receipt) + b"\n" for receipt in receipts)
    )
    _canonical_write(targets[1], receipt_set)
    _canonical_write(targets[2], trusted_keys)
    result = validate_quality_evidence(
        repository_root=repository_root,
        trusted_key_registry_path=targets[2],
    )
    if not result.passed:
        for path in targets:
            path.unlink(missing_ok=True)
        raise ValueError(f"assembled quality package failed validation: {result.errors}")
    return result.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument(
        "--public-key-record", type=Path, action="append", required=True
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=REPOSITORY_ROOT / "docs/readiness/gtbi-v7",
    )
    args = parser.parse_args()
    result = assemble(
        repository_root=args.repository_root.resolve(),
        receipt_paths=[path.resolve() for path in args.receipt],
        public_key_record_paths=[
            path.resolve() for path in args.public_key_record
        ],
        output_directory=args.output_directory.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
