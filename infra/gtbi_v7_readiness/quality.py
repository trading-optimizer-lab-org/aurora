"""Fail-closed validation of GTBI V7 master-plan audit evidence."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from .canonical import (
    canonical_bytes,
    domain_digest,
    git_blob_id,
    raw_sha256,
)
from .structure import validate_master_plan_structure

AUDIT_SCOPE_DOMAIN = "GTBI_MASTER_PLAN_AUDIT_SCOPE_V1"
AUDIT_PAYLOAD_DOMAIN = "GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1"
AUDIT_RECEIPT_DOMAIN = "GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1"
RECEIPT_SET_DOMAIN = "GTBI_MASTER_PLAN_QUALITY_RECEIPT_SET_V1"


@dataclass(frozen=True)
class QualityValidationResult:
    status: str
    errors: tuple[str, ...]
    reviewed_master_plan_sha256: str | None = None
    master_plan_quality_receipt_set_digest: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "CLEAN"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "errors": list(self.errors),
            "reviewed_master_plan_sha256": self.reviewed_master_plan_sha256,
            "master_plan_quality_receipt_set_digest": (
                self.master_plan_quality_receipt_set_digest
            ),
        }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json_file(path: Path) -> Any:
    data = _load_json(path)
    expected = canonical_bytes(data) + b"\n"
    if path.read_bytes() != expected:
        raise ValueError(f"{path} is not canonical JSON plus one LF")
    return data


def _load_jsonl(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError(f"{path} must be LF-terminated canonical JSONL")
    rows = []
    for number, line in enumerate(raw.splitlines(), 1):
        row = json.loads(line)
        if line != canonical_bytes(row):
            raise ValueError(f"{path}:{number} is not canonical JSON")
        rows.append(row)
    return rows


def _schema_validate(payload: dict, schema_path: Path) -> None:
    schema = _load_json(schema_path)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def _decode_base64url(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _verify_ed25519(public_key: bytes, signature: bytes, message: bytes) -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("cryptography is required for Ed25519 verification") from exc
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)


def validate_quality_evidence(
    *,
    repository_root: str | Path,
    trusted_key_registry_path: str | Path | None = None,
) -> QualityValidationResult:
    """Validate the complete three-round quality package.

    Missing externally signed evidence returns ``BLOCKED``. Invalid or stale
    evidence returns ``INVALID``. Only a complete, cryptographically valid set
    over the current exact bytes returns ``CLEAN``.
    """
    root = Path(repository_root)
    readiness = root / "docs/readiness/gtbi-v7"
    schemas = root / "config/gtbi/schemas/v7/operational"
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    profile_path = root / "config/gtbi/contracts/canonical_serialization_v1.json"
    registry_path = root / "config/gtbi/contracts/hash_domain_registry_v1.json"
    scope_path = readiness / "master_plan_audit_scope_manifest.json"
    receipts_path = readiness / "master_plan_quality_receipts.jsonl"
    receipt_set_path = readiness / "master_plan_quality_receipt_set.json"
    trusted_key_path = (
        Path(trusted_key_registry_path)
        if trusted_key_registry_path is not None
        else readiness / "master_plan_audit_trusted_keys.json"
    )
    required = [plan_path, profile_path, registry_path, scope_path]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        return QualityValidationResult(
            "BLOCKED", tuple(f"missing bootstrap file: {path}" for path in missing)
        )

    plan_bytes = plan_path.read_bytes()
    plan_digest = raw_sha256(plan_bytes)
    errors: list[str] = []
    try:
        profile = _canonical_json_file(profile_path)
        registry = _canonical_json_file(registry_path)
        scope = _canonical_json_file(scope_path)
    except Exception as exc:
        return QualityValidationResult("INVALID", (str(exc),), plan_digest)

    profile_digest = raw_sha256(profile_path)
    registry_digest = raw_sha256(registry_path)
    expected_plan_identity = {
        "reviewed_master_plan_sha256": plan_digest,
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
    }
    for field, expected in expected_plan_identity.items():
        if scope.get(field) != expected:
            errors.append(f"scope {field} mismatch")
    if scope.get("canonical_serialization_profile_digest") != profile_digest:
        errors.append("scope canonical serialization profile digest mismatch")
    if scope.get("hash_domain_registry_digest") != registry_digest:
        errors.append("scope hash-domain registry digest mismatch")
    expected_scope_digest = domain_digest(
        AUDIT_SCOPE_DOMAIN, scope, omit_top_level_fields=("scope_manifest_digest",)
    )
    if scope.get("scope_manifest_digest") != expected_scope_digest:
        errors.append("scope manifest digest mismatch")
    try:
        _schema_validate(
            scope, schemas / "master_plan_audit_scope_manifest_v1.schema.json"
        )
    except Exception as exc:
        errors.append(f"scope schema validation failed: {exc}")

    structural = validate_master_plan_structure(
        plan_path,
        forbidden_term_rules=scope.get("ordered_forbidden_term_rules", []),
    )
    actual_structural_checks = [check.check_id for check in structural.checks]
    if scope.get("ordered_structural_checks") != actual_structural_checks:
        errors.append("scope structural-check registry does not match validator")
    errors.extend(structural.errors)
    if errors:
        return QualityValidationResult("INVALID", tuple(errors), plan_digest)

    missing_external = [
        path
        for path in (receipts_path, receipt_set_path)
        if not path.exists()
    ]
    if not trusted_key_path.exists():
        missing_external.append(trusted_key_path)
    if missing_external:
        return QualityValidationResult(
            "BLOCKED",
            tuple(f"missing external quality evidence: {path}" for path in missing_external),
            plan_digest,
        )

    try:
        receipts = _load_jsonl(receipts_path)
        receipt_set = _canonical_json_file(receipt_set_path)
        key_registry = _canonical_json_file(trusted_key_path)
    except Exception as exc:
        return QualityValidationResult("INVALID", (str(exc),), plan_digest)
    try:
        _schema_validate(
            key_registry,
            schemas / "master_plan_audit_trusted_keys_v1.schema.json",
        )
    except Exception as exc:
        errors.append(f"trusted-key registry schema validation failed: {exc}")
    if len(receipts) != 3:
        errors.append(f"expected exactly 3 receipts, got {len(receipts)}")

    key_rows = [
        row
        for row in key_registry.get("keys", [])
        if isinstance(row, dict) and "signing_key_id" in row
    ]
    keys = {row["signing_key_id"]: row for row in key_rows}
    if len(keys) != len(key_rows):
        errors.append("trusted-key registry contains duplicate signing_key_id")
    registered_actor_ids = [row.get("auditor_actor_id") for row in key_rows]
    if len(registered_actor_ids) != len(set(registered_actor_ids)):
        errors.append("trusted-key registry contains duplicate auditor_actor_id")
    actor_ids: list[str] = []
    signing_key_ids: list[str] = []
    receipt_digests: list[str] = []
    previous_end: datetime | None = None
    for index, receipt in enumerate(receipts, 1):
        try:
            _schema_validate(
                receipt, schemas / "master_plan_audit_receipt_v1.schema.json"
            )
        except Exception as exc:
            errors.append(f"receipt {index} schema validation failed: {exc}")
            continue
        payload = receipt["signed_payload"]
        actor_ids.append(payload["auditor_actor_id"])
        signing_key_ids.append(receipt["signing_key_id"])
        receipt_digests.append(receipt["receipt_digest"])
        if payload["round_sequence"] != index:
            errors.append(f"receipt {index} has wrong round_sequence")
        for field, expected in expected_plan_identity.items():
            if payload.get(field) != expected:
                errors.append(f"receipt {index} {field} mismatch")
        if payload.get("scope_manifest_digest") != expected_scope_digest:
            errors.append(f"receipt {index} scope digest mismatch")
        if payload.get("canonical_serialization_profile_digest") != profile_digest:
            errors.append(f"receipt {index} profile digest mismatch")
        if payload.get("hash_domain_registry_digest") != registry_digest:
            errors.append(f"receipt {index} registry digest mismatch")
        if payload.get("finding_count") != 0 or payload.get("result") != "CLEAN":
            errors.append(f"receipt {index} is not zero-finding CLEAN")
        expected_payload_digest = domain_digest(
            AUDIT_PAYLOAD_DOMAIN,
            payload,
            omit_top_level_fields=("audit_payload_digest",),
        )
        if payload.get("audit_payload_digest") != expected_payload_digest:
            errors.append(f"receipt {index} audit payload digest mismatch")
        expected_receipt_digest = domain_digest(
            AUDIT_RECEIPT_DOMAIN,
            receipt,
            omit_top_level_fields=("receipt_digest",),
        )
        if receipt.get("receipt_digest") != expected_receipt_digest:
            errors.append(f"receipt {index} outer digest mismatch")
        started = datetime.fromisoformat(payload["started_at_utc"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(payload["ended_at_utc"].replace("Z", "+00:00"))
        if started >= ended:
            errors.append(f"receipt {index} has non-positive duration")
        if previous_end is not None and started <= previous_end:
            errors.append(f"receipt {index} overlaps the previous round")
        previous_end = ended
        key = keys.get(receipt["signing_key_id"])
        if key is None:
            errors.append(f"receipt {index} uses an untrusted signing key")
            continue
        if key.get("auditor_actor_id") != payload["auditor_actor_id"]:
            errors.append(f"receipt {index} actor/key binding mismatch")
        if key.get("algorithm") != receipt["signature_algorithm"]:
            errors.append(f"receipt {index} signature algorithm mismatch")
        if (
            key.get("identity_evidence_digest")
            != payload["auditor_independence_attestation"][
                "identity_evidence_digest"
            ]
        ):
            errors.append(f"receipt {index} identity evidence digest mismatch")
        try:
            key_valid_from = datetime.fromisoformat(
                key["valid_from_utc"].replace("Z", "+00:00")
            )
            key_valid_until = datetime.fromisoformat(
                key["valid_until_utc"].replace("Z", "+00:00")
            )
            if key_valid_from > started or key_valid_until < ended:
                errors.append(f"receipt {index} falls outside key validity")
        except Exception as exc:
            errors.append(f"receipt {index} key validity is invalid: {exc}")
        try:
            digest_bytes = bytes.fromhex(expected_payload_digest.removeprefix("sha256:"))
            _verify_ed25519(
                _decode_base64url(key["public_key_base64url"]),
                _decode_base64url(receipt["signature"]),
                digest_bytes,
            )
        except Exception as exc:
            errors.append(f"receipt {index} signature verification failed: {exc}")

    try:
        _schema_validate(
            receipt_set,
            schemas / "master_plan_quality_receipt_set_v1.schema.json",
        )
    except Exception as exc:
        errors.append(f"receipt-set schema validation failed: {exc}")
    expected_set_digest = domain_digest(
        RECEIPT_SET_DOMAIN,
        receipt_set,
        omit_top_level_fields=("master_plan_quality_receipt_set_digest",),
    )
    if receipt_set.get("master_plan_quality_receipt_set_digest") != expected_set_digest:
        errors.append("receipt-set digest mismatch")
    expected_set_fields = {
        **expected_plan_identity,
        "canonical_serialization_profile_digest": profile_digest,
        "hash_domain_registry_digest": registry_digest,
        "scope_manifest_digest": expected_scope_digest,
        "ordered_receipt_digests": receipt_digests,
        "auditor_actor_ids": actor_ids,
        "signing_key_ids": signing_key_ids,
    }
    for field, expected in expected_set_fields.items():
        if receipt_set.get(field) != expected:
            errors.append(f"receipt-set {field} mismatch")
    if len(set(actor_ids)) != 3:
        errors.append("auditor actor IDs are not pairwise distinct")
    if len(set(signing_key_ids)) != 3:
        errors.append("signing key IDs are not pairwise distinct")
    for flag in (
        "pairwise_actor_independence_verified",
        "pairwise_key_independence_verified",
        "non_author_non_implementer_verified",
        "strict_nonoverlap_verified",
        "complete_scope_verified",
        "all_results_clean",
    ):
        if receipt_set.get(flag) is not True:
            errors.append(f"receipt-set flag {flag} is not true")
    return QualityValidationResult(
        "INVALID" if errors else "CLEAN",
        tuple(errors),
        plan_digest,
        expected_set_digest,
    )
