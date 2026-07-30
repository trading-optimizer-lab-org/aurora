"""Deterministic owner-authorized quality validation for GTBI V7."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .canonical import canonical_bytes, domain_digest, git_blob_id, raw_sha256
from .structure import validate_master_plan_structure

AUDIT_SCOPE_DOMAIN = "GTBI_MASTER_PLAN_AUDIT_SCOPE_V1"
OWNER_DIRECTIVE_SCHEMA = "gtbi_v7_owner_simplification_directive_v1"
OWNER_DIRECTIVE_PRECEDENCE = (
    "supersedes_conflicting_independence_dual_control_external_custody_"
    "and_external_audit_requirements"
)


@dataclass(frozen=True)
class QualityValidationResult:
    status: str
    errors: tuple[str, ...]
    reviewed_master_plan_sha256: str | None = None
    master_plan_quality_receipt_set_digest: str | None = None
    owner_simplification_directive_digest: str | None = None

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
            "owner_simplification_directive_digest": (
                self.owner_simplification_directive_digest
            ),
        }


def _canonical_json_file(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(data) + b"\n":
        raise ValueError(f"{path} is not canonical JSON plus one LF")
    return data


def _schema_validate(payload: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def validate_quality_evidence(
    *,
    repository_root: str | Path,
    trusted_key_registry_path: str | Path | None = None,
) -> QualityValidationResult:
    """Validate the owner directive and exact deterministic plan contracts.

    ``trusted_key_registry_path`` is accepted only for compatibility with the
    retired external-audit tooling. It has no effect on current acceptance.
    """

    del trusted_key_registry_path
    root = Path(repository_root)
    readiness = root / "docs/readiness/gtbi-v7"
    schemas = root / "config/gtbi/schemas/v7/operational"
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    profile_path = root / "config/gtbi/contracts/canonical_serialization_v1.json"
    registry_path = root / "config/gtbi/contracts/hash_domain_registry_v1.json"
    scope_path = readiness / "master_plan_audit_scope_manifest.json"
    owner_directive_path = readiness / "owner_simplification_directive.json"
    required = [
        plan_path,
        profile_path,
        registry_path,
        scope_path,
        owner_directive_path,
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        return QualityValidationResult(
            "BLOCKED",
            tuple(f"missing bootstrap file: {path}" for path in missing),
        )

    plan_bytes = plan_path.read_bytes()
    plan_digest = raw_sha256(plan_bytes)
    try:
        _canonical_json_file(profile_path)
        _canonical_json_file(registry_path)
        scope = _canonical_json_file(scope_path)
        owner_directive = _canonical_json_file(owner_directive_path)
    except Exception as exc:
        return QualityValidationResult("INVALID", (str(exc),), plan_digest)

    profile_digest = raw_sha256(profile_path)
    registry_digest = raw_sha256(registry_path)
    errors: list[str] = []
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
        AUDIT_SCOPE_DOMAIN,
        scope,
        omit_top_level_fields=("scope_manifest_digest",),
    )
    if scope.get("scope_manifest_digest") != expected_scope_digest:
        errors.append("scope manifest digest mismatch")
    try:
        _schema_validate(
            scope,
            schemas / "master_plan_audit_scope_manifest_v1.schema.json",
        )
    except Exception as exc:
        errors.append(f"scope schema validation failed: {exc}")

    structural = validate_master_plan_structure(
        plan_path,
        forbidden_term_rules=scope.get("ordered_forbidden_term_rules", []),
    )
    actual_checks = [check.check_id for check in structural.checks]
    if scope.get("ordered_structural_checks") != actual_checks:
        errors.append("scope structural-check registry does not match validator")
    errors.extend(structural.errors)
    if owner_directive.get("schema_version") != OWNER_DIRECTIVE_SCHEMA:
        errors.append("owner simplification directive schema version mismatch")
    if owner_directive.get("accepted") is not True:
        errors.append("owner simplification directive is not accepted")
    if owner_directive.get("precedence") != OWNER_DIRECTIVE_PRECEDENCE:
        errors.append("owner simplification directive precedence mismatch")

    return QualityValidationResult(
        "INVALID" if errors else "CLEAN",
        tuple(errors),
        plan_digest,
        None,
        raw_sha256(owner_directive_path),
    )
