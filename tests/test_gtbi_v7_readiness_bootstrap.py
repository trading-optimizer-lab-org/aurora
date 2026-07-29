from __future__ import annotations

import base64
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from infra.gtbi_v7_readiness.canonical import (
    CanonicalizationError,
    canonical_bytes,
    canonical_text,
    domain_digest,
    git_blob_id,
    raw_sha256,
)
from infra.gtbi_v7_readiness.quality import validate_quality_evidence
from infra.gtbi_v7_readiness.structure import validate_master_plan_structure
from scripts.assemble_gtbi_v7_master_plan_quality_set import assemble
from scripts.create_gtbi_v7_master_plan_audit_receipt import create_receipt

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def _canonical_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def _copy_bootstrap_tree(target: Path) -> None:
    files = [
        "docs/plans/gtbi-v7-master-plan.md",
        "docs/readiness/gtbi-v7/master_plan_audit_scope_manifest.json",
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        "config/gtbi/contracts/canonical_serialization_v1.json",
        "config/gtbi/contracts/hash_domain_registry_v1.json",
        (
            "config/gtbi/schemas/v7/operational/"
            "master_plan_audit_scope_manifest_v1.schema.json"
        ),
        (
            "config/gtbi/schemas/v7/operational/"
            "master_plan_audit_receipt_v1.schema.json"
        ),
        (
            "config/gtbi/schemas/v7/operational/"
            "master_plan_quality_receipt_set_v1.schema.json"
        ),
        (
            "config/gtbi/schemas/v7/operational/"
            "master_plan_audit_trusted_keys_v1.schema.json"
        ),
        (
            "config/gtbi/schemas/v7/operational/"
            "master_plan_quality_audit_report_v1.schema.json"
        ),
    ]
    for relative in files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signed_quality_package(root: Path) -> Path:
    _copy_bootstrap_tree(root)
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    profile_path = root / "config/gtbi/contracts/canonical_serialization_v1.json"
    registry_path = root / "config/gtbi/contracts/hash_domain_registry_v1.json"
    scope = json.loads(
        (root / "docs/readiness/gtbi-v7/master_plan_audit_scope_manifest.json")
        .read_text(encoding="utf-8")
    )
    plan_bytes = plan_path.read_bytes()
    identity = {
        "reviewed_master_plan_sha256": raw_sha256(plan_bytes),
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
    }
    keys = []
    receipts = []
    start = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    for sequence in range(1, 4):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        actor_id = f"external-auditor-{sequence}"
        key_id = f"external-audit-key-{sequence}"
        keys.append(
            {
                "signing_key_id": key_id,
                "auditor_actor_id": actor_id,
                "algorithm": "ed25519",
                "public_key_base64url": _b64url(public_key),
                "identity_evidence_digest": raw_sha256(
                    f"identity-evidence-{sequence}".encode("utf-8")
                ),
                "valid_from_utc": "2026-07-29T00:00:00Z",
                "valid_until_utc": "2026-07-30T00:00:00Z",
            }
        )
        round_start = start + timedelta(hours=(sequence - 1) * 2)
        round_end = round_start + timedelta(hours=1)
        payload = {
            "schema_version": "master_plan_audit_payload_v1",
            "round_sequence": sequence,
            "auditor_actor_id": actor_id,
            "auditor_role": "independent_master_plan_quality_auditor",
            "auditor_independence_attestation": {
                "document_author": False,
                "implementation_author": False,
                "independent_of_other_auditors": True,
                "complete_scope_reviewed": True,
                "audit_report_digest": raw_sha256(
                    f"audit-report-{sequence}".encode("utf-8")
                ),
                "structural_validation_report_digest": raw_sha256(
                    f"structural-report-{sequence}".encode("utf-8")
                ),
                "identity_evidence_digest": raw_sha256(
                    f"identity-evidence-{sequence}".encode("utf-8")
                ),
                "attestation": "Independent complete review of the frozen bytes.",
            },
            "tool_or_model_identity": f"external-audit-tool-{sequence}",
            "tool_or_model_version": "1.0",
            "scope_manifest_digest": scope["scope_manifest_digest"],
            "canonical_serialization_profile_digest": raw_sha256(profile_path),
            "hash_domain_registry_digest": raw_sha256(registry_path),
            **identity,
            "started_at_utc": round_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended_at_utc": round_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finding_count": 0,
            "result": "CLEAN",
        }
        payload["audit_payload_digest"] = domain_digest(
            "GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1", payload
        )
        signature = private_key.sign(
            bytes.fromhex(payload["audit_payload_digest"].removeprefix("sha256:"))
        )
        receipt = {
            "schema_version": "master_plan_audit_receipt_v1",
            "signed_payload": payload,
            "signature_algorithm": "ed25519",
            "signing_key_id": key_id,
            "signature": _b64url(signature),
        }
        receipt["receipt_digest"] = domain_digest(
            "GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1", receipt
        )
        receipts.append(receipt)

    receipt_path = root / "docs/readiness/gtbi-v7/master_plan_quality_receipts.jsonl"
    receipt_path.write_bytes(
        b"".join(canonical_bytes(receipt) + b"\n" for receipt in receipts)
    )
    receipt_set = {
        "schema_version": "master_plan_quality_receipt_set_v1",
        **identity,
        "canonical_serialization_profile_digest": raw_sha256(profile_path),
        "hash_domain_registry_digest": raw_sha256(registry_path),
        "scope_manifest_digest": scope["scope_manifest_digest"],
        "ordered_receipt_digests": [
            receipt["receipt_digest"] for receipt in receipts
        ],
        "auditor_actor_ids": [
            receipt["signed_payload"]["auditor_actor_id"] for receipt in receipts
        ],
        "signing_key_ids": [receipt["signing_key_id"] for receipt in receipts],
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
    _canonical_write(
        root / "docs/readiness/gtbi-v7/master_plan_quality_receipt_set.json",
        receipt_set,
    )
    key_registry = {
        "schema_version": "master_plan_audit_trusted_keys_v1",
        "keys": keys,
    }
    key_path = root / "trusted-audit-keys.json"
    _canonical_write(key_path, key_registry)
    return key_path


def test_canonical_json_orders_objects_and_normalizes_number_spelling() -> None:
    assert canonical_text({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_text([1.0, 1e-6, 1e20, 1e30, -0.0]) == (
        "[1,0.000001,100000000000000000000,1e+30,0]"
    )


def test_canonical_json_rejects_ambiguous_values() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_bytes({"unsafe": 9_007_199_254_740_992})
    with pytest.raises(CanonicalizationError):
        canonical_bytes({"not_finite": float("nan")})
    with pytest.raises(CanonicalizationError):
        canonical_bytes({"surrogate": "\ud800"})


def test_domain_separator_changes_digest() -> None:
    payload = {"same": "payload"}
    assert domain_digest("DOMAIN_A", payload) != domain_digest("DOMAIN_B", payload)


def test_current_master_plan_passes_all_structural_checks() -> None:
    scope = json.loads(
        (READINESS / "master_plan_audit_scope_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    result = validate_master_plan_structure(
        ROOT / "docs/plans/gtbi-v7-master-plan.md",
        forbidden_term_rules=scope["ordered_forbidden_term_rules"],
    )
    assert result.passed, result.errors
    assert len(result.checks) == 10


def test_duplicate_task_id_is_rejected(tmp_path: Path) -> None:
    source = (ROOT / "docs/plans/gtbi-v7-master-plan.md").read_text(encoding="utf-8")
    first_row = (
        "| PREV7-0000 | P0 | Implementer | None | Master plan, "
        "canonical-serialization/hash-domain bootstrap objects"
    )
    row_start = source.index(first_row)
    row_end = source.index("\n", row_start) + 1
    duplicate = source[row_start:row_end]
    plan = tmp_path / "plan.md"
    plan.write_text(source[:row_end] + duplicate + source[row_end:], encoding="utf-8", newline="\n")
    result = validate_master_plan_structure(plan)
    check = next(item for item in result.checks if item.check_id == "unique_task_ids")
    assert not check.passed


def test_owner_directive_replaces_external_receipts() -> None:
    result = validate_quality_evidence(repository_root=ROOT)
    assert result.status == "CLEAN", result.errors
    assert result.passed
    assert result.owner_simplification_directive_digest


def test_legacy_signed_rounds_do_not_override_owner_directive(tmp_path: Path) -> None:
    key_registry = _signed_quality_package(tmp_path)
    result = validate_quality_evidence(
        repository_root=tmp_path,
        trusted_key_registry_path=key_registry,
    )
    assert result.status == "CLEAN", result.errors
    assert result.master_plan_quality_receipt_set_digest is None
    assert result.owner_simplification_directive_digest


def test_plan_byte_change_invalidates_signed_rounds(tmp_path: Path) -> None:
    key_registry = _signed_quality_package(tmp_path)
    plan = tmp_path / "docs/plans/gtbi-v7-master-plan.md"
    plan.write_bytes(plan.read_bytes() + b"changed\n")
    result = validate_quality_evidence(
        repository_root=tmp_path,
        trusted_key_registry_path=key_registry,
    )
    assert result.status == "INVALID"
    assert any("mismatch" in error for error in result.errors)


def test_auditor_tool_binds_complete_report_identity_and_structure(
    tmp_path: Path,
) -> None:
    _copy_bootstrap_tree(tmp_path)
    scope = json.loads(
        (
            tmp_path
            / "docs/readiness/gtbi-v7/master_plan_audit_scope_manifest.json"
        ).read_text(encoding="utf-8")
    )
    structural = validate_master_plan_structure(
        tmp_path / "docs/plans/gtbi-v7-master-plan.md",
        forbidden_term_rules=scope["ordered_forbidden_term_rules"],
    )
    report = {
        "schema_version": "master_plan_quality_audit_report_v1",
        "round_sequence": 1,
        "auditor_actor_id": "external-auditor-1",
        "reviewed_master_plan_sha256": scope["reviewed_master_plan_sha256"],
        "scope_manifest_digest": scope["scope_manifest_digest"],
        "review_dimensions": [
            {
                "dimension_id": dimension,
                "reviewed": True,
                "finding_count": 0,
                "result": "CLEAN",
                "evidence_summary": f"Complete review of {dimension}.",
            }
            for dimension in scope["ordered_review_dimensions"]
        ],
        "structural_checks": [
            {
                "check_id": check.check_id,
                "passed": check.passed,
                "details": list(check.details),
            }
            for check in structural.checks
        ],
        "findings": [],
        "finding_count": 0,
        "result": "CLEAN",
    }
    report_path = tmp_path / "audit-report.json"
    _canonical_write(report_path, report)
    identity_path = tmp_path / "identity-evidence.bin"
    identity_path.write_bytes(b"authenticated external identity evidence")
    private_key = Ed25519PrivateKey.generate()
    private_key_path = tmp_path / "auditor-private-key.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    receipt, structural_report, key_record = create_receipt(
        repository_root=tmp_path,
        report_path=report_path,
        identity_evidence_path=identity_path,
        private_key_path=private_key_path,
        round_sequence=1,
        auditor_actor_id="external-auditor-1",
        signing_key_id="external-audit-key-1",
        tool_or_model_identity="external-audit-tool",
        tool_or_model_version="1.0",
        started_at_utc="2026-07-29T08:00:00Z",
        ended_at_utc="2026-07-29T09:00:00Z",
        key_valid_from_utc="2026-07-29T00:00:00Z",
        key_valid_until_utc="2026-07-30T00:00:00Z",
        attestation="Independent complete review of the frozen bytes.",
    )
    attestation = receipt["signed_payload"]["auditor_independence_attestation"]
    assert attestation["audit_report_digest"] == raw_sha256(report_path)
    assert attestation["identity_evidence_digest"] == raw_sha256(identity_path)
    assert structural_report["passed"]
    assert key_record["public_key_base64url"]


def test_assembler_rebuilds_and_verifies_three_round_package(
    tmp_path: Path,
) -> None:
    key_registry_path = _signed_quality_package(tmp_path)
    readiness = tmp_path / "docs/readiness/gtbi-v7"
    receipts = [
        json.loads(line)
        for line in (
            readiness / "master_plan_quality_receipts.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    key_records = json.loads(
        key_registry_path.read_text(encoding="utf-8")
    )["keys"]
    receipt_paths = []
    key_paths = []
    for index, (receipt, key_record) in enumerate(
        zip(receipts, key_records, strict=True), 1
    ):
        receipt_path = tmp_path / f"round-{index}-receipt.json"
        key_path = tmp_path / f"round-{index}-key.json"
        _canonical_write(receipt_path, receipt)
        _canonical_write(key_path, key_record)
        receipt_paths.append(receipt_path)
        key_paths.append(key_path)
    for path in (
        readiness / "master_plan_quality_receipts.jsonl",
        readiness / "master_plan_quality_receipt_set.json",
        key_registry_path,
    ):
        path.unlink()
    result = assemble(
        repository_root=tmp_path,
        receipt_paths=receipt_paths,
        public_key_record_paths=key_paths,
        output_directory=readiness,
    )
    assert result["status"] == "CLEAN"


def test_bootstrap_schemas_and_generated_json_are_canonical() -> None:
    import jsonschema

    paths = [
        *(
            ROOT / "config/gtbi/schemas/v7/operational"
        ).glob("master_plan_*_v1.schema.json"),
        ROOT / "config/gtbi/contracts/canonical_serialization_v1.json",
        ROOT / "config/gtbi/contracts/hash_domain_registry_v1.json",
        READINESS / "master_plan_audit_scope_manifest.json",
        READINESS / "master_plan_quality_status.json",
        READINESS / "owner_simplification_directive.json",
    ]
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert path.read_bytes() == canonical_bytes(payload) + b"\n"
        if path.name.endswith(".schema.json"):
            jsonschema.Draft202012Validator.check_schema(payload)


def test_quality_workflow_is_read_only_pinned_and_github_hosted() -> None:
    workflow = ROOT / ".github/workflows/gtbi-v7-master-plan-quality.yml"
    text = workflow.read_text(encoding="utf-8")
    yaml.safe_load(text)
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "contents: read" in text
    uses = [
        line.strip().removeprefix("uses: ")
        for line in text.splitlines()
        if line.strip().startswith("uses: ")
    ]
    assert uses
    assert all(
        value.rsplit("@", 1)[-1].isalnum()
        and len(value.rsplit("@", 1)[-1]) == 40
        for value in uses
    )
