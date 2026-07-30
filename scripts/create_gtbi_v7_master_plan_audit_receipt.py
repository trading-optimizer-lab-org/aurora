"""Create one externally signed GTBI V7 master-plan audit receipt.

Run this tool in the independent auditor's environment. It never generates an
auditor identity, finding result or private key. The supplied report must
already be complete, canonical and CLEAN.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

import jsonschema
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    git_blob_id,
    raw_sha256,
)
from infra.gtbi_v7_readiness.structure import (  # noqa: E402
    validate_master_plan_structure,
)


def _canonical_load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path} is not canonical JSON plus one LF")
    return payload


def _canonical_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("audit timestamps must end in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def create_receipt(
    *,
    repository_root: Path,
    report_path: Path,
    identity_evidence_path: Path,
    private_key_path: Path,
    round_sequence: int,
    auditor_actor_id: str,
    signing_key_id: str,
    tool_or_model_identity: str,
    tool_or_model_version: str,
    started_at_utc: str,
    ended_at_utc: str,
    key_valid_from_utc: str,
    key_valid_until_utc: str,
    attestation: str,
) -> tuple[dict, dict, dict]:
    root = repository_root
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    profile_path = root / "config/gtbi/contracts/canonical_serialization_v1.json"
    registry_path = root / "config/gtbi/contracts/hash_domain_registry_v1.json"
    scope_path = root / "docs/readiness/gtbi-v7/master_plan_audit_scope_manifest.json"
    schema_root = root / "config/gtbi/schemas/v7/operational"
    scope = _canonical_load(scope_path)
    report = _canonical_load(report_path)
    report_schema = json.loads(
        (schema_root / "master_plan_quality_audit_report_v1.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(report_schema).validate(report)
    if report["round_sequence"] != round_sequence:
        raise ValueError("audit report round_sequence does not match CLI input")
    if report["auditor_actor_id"] != auditor_actor_id:
        raise ValueError("audit report auditor_actor_id does not match CLI input")
    if report["finding_count"] != 0 or report["result"] != "CLEAN":
        raise ValueError("only a complete zero-finding CLEAN report can be signed")
    if report["reviewed_master_plan_sha256"] != scope["reviewed_master_plan_sha256"]:
        raise ValueError("audit report reviewed master-plan digest mismatch")
    if report["scope_manifest_digest"] != scope["scope_manifest_digest"]:
        raise ValueError("audit report scope digest mismatch")

    structural = validate_master_plan_structure(
        plan_path,
        forbidden_term_rules=scope["ordered_forbidden_term_rules"],
    )
    if not structural.passed:
        raise ValueError(f"structural validation failed: {structural.errors}")
    structural_report = {
        "schema_version": "master_plan_structural_validation_report_v1",
        "reviewed_master_plan_sha256": raw_sha256(plan_path),
        "scope_manifest_digest": scope["scope_manifest_digest"],
        **structural.to_dict(),
    }
    if report["structural_checks"] != structural_report["checks"]:
        raise ValueError("audit report structural checks do not match the validator")

    started = _utc(started_at_utc)
    ended = _utc(ended_at_utc)
    valid_from = _utc(key_valid_from_utc)
    valid_until = _utc(key_valid_until_utc)
    if started >= ended:
        raise ValueError("audit start must precede audit end")
    if valid_from > started or valid_until < ended:
        raise ValueError("signing key validity must cover the complete audit round")

    loaded_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=None
    )
    if not isinstance(loaded_key, Ed25519PrivateKey):
        raise TypeError("private key must be an unencrypted Ed25519 PKCS8 PEM")
    public_key = loaded_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    plan_bytes = plan_path.read_bytes()
    identity_evidence_digest = raw_sha256(identity_evidence_path)
    payload = {
        "schema_version": "master_plan_audit_payload_v1",
        "round_sequence": round_sequence,
        "auditor_actor_id": auditor_actor_id,
        "auditor_role": "independent_master_plan_quality_auditor",
        "auditor_independence_attestation": {
            "document_author": False,
            "implementation_author": False,
            "independent_of_other_auditors": True,
            "complete_scope_reviewed": True,
            "audit_report_digest": raw_sha256(report_path),
            "structural_validation_report_digest": raw_sha256(
                canonical_bytes(structural_report) + b"\n"
            ),
            "identity_evidence_digest": identity_evidence_digest,
            "attestation": attestation,
        },
        "tool_or_model_identity": tool_or_model_identity,
        "tool_or_model_version": tool_or_model_version,
        "scope_manifest_digest": scope["scope_manifest_digest"],
        "canonical_serialization_profile_digest": raw_sha256(profile_path),
        "hash_domain_registry_digest": raw_sha256(registry_path),
        "reviewed_master_plan_sha256": raw_sha256(plan_bytes),
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "finding_count": 0,
        "result": "CLEAN",
    }
    payload["audit_payload_digest"] = domain_digest(
        "GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1", payload
    )
    signature = loaded_key.sign(
        bytes.fromhex(payload["audit_payload_digest"].removeprefix("sha256:"))
    )
    receipt = {
        "schema_version": "master_plan_audit_receipt_v1",
        "signed_payload": payload,
        "signature_algorithm": "ed25519",
        "signing_key_id": signing_key_id,
        "signature": _b64url(signature),
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1", receipt
    )
    receipt_schema = json.loads(
        (schema_root / "master_plan_audit_receipt_v1.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(receipt_schema).validate(receipt)
    public_key_record = {
        "signing_key_id": signing_key_id,
        "auditor_actor_id": auditor_actor_id,
        "algorithm": "ed25519",
        "public_key_base64url": _b64url(public_key),
        "identity_evidence_digest": identity_evidence_digest,
        "valid_from_utc": key_valid_from_utc,
        "valid_until_utc": key_valid_until_utc,
    }
    return receipt, structural_report, public_key_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--identity-evidence", type=Path, required=True)
    parser.add_argument("--private-key-pem", type=Path, required=True)
    parser.add_argument("--round-sequence", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--auditor-actor-id", required=True)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--tool-or-model-identity", required=True)
    parser.add_argument("--tool-or-model-version", required=True)
    parser.add_argument("--started-at-utc", required=True)
    parser.add_argument("--ended-at-utc", required=True)
    parser.add_argument("--key-valid-from-utc", required=True)
    parser.add_argument("--key-valid-until-utc", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    parser.add_argument("--structural-report-output", type=Path, required=True)
    parser.add_argument("--public-key-record-output", type=Path, required=True)
    args = parser.parse_args()
    receipt, structural_report, public_key_record = create_receipt(
        repository_root=args.repository_root.resolve(),
        report_path=args.report.resolve(),
        identity_evidence_path=args.identity_evidence.resolve(),
        private_key_path=args.private_key_pem.resolve(),
        round_sequence=args.round_sequence,
        auditor_actor_id=args.auditor_actor_id,
        signing_key_id=args.signing_key_id,
        tool_or_model_identity=args.tool_or_model_identity,
        tool_or_model_version=args.tool_or_model_version,
        started_at_utc=args.started_at_utc,
        ended_at_utc=args.ended_at_utc,
        key_valid_from_utc=args.key_valid_from_utc,
        key_valid_until_utc=args.key_valid_until_utc,
        attestation=args.attestation,
    )
    for path in (
        args.receipt_output,
        args.structural_report_output,
        args.public_key_record_output,
    ):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")
    _canonical_write(args.receipt_output, receipt)
    _canonical_write(args.structural_report_output, structural_report)
    _canonical_write(args.public_key_record_output, public_key_record)
    print(receipt["receipt_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
