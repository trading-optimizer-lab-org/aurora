"""Final fail-closed proof for assisted catalog controller bootstrap."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Literal

from pydantic import Field

from .catalog_request_contract import FrozenModel, Sha256


class CatalogBootstrapFinalEvidenceV1(FrozenModel):
    schema_version: Literal["1"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    public_binding_sha256: Sha256
    merged_binding_verified: bool
    requester_installation_verified: bool
    auditor_installation_verified: bool
    requester_key_isolated: bool
    auditor_key_github_only: bool
    local_identities_and_acls_verified: bool
    agent_process_owner: str
    hp_codex_process_count: int = Field(ge=0)
    github_controls_status: Literal["ready", "blocked"]
    zero_budget_count: int = Field(ge=0)
    qualification_receipt_sha256s: tuple[Sha256, ...]
    qualification_equivalent: bool
    disabled_bootstrap_request_count: int = Field(ge=0)
    production_request_count: int = Field(ge=0)
    production_run_count: int = Field(ge=0)
    controller_enabled_readback: bool
    post_enable_controls_status: Literal["ready", "blocked"]


class CatalogBootstrapFinalReceiptV1(FrozenModel):
    schema_version: Literal["1"]
    result: Literal["READY"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    public_binding_sha256: Sha256
    qualification_receipt_sha256s: tuple[Sha256, Sha256, Sha256]
    controller_enabled_readback: Literal[True]
    production_request_count: Literal[0]
    production_run_count: Literal[0]
    receipt_sha256: Sha256


class CatalogBootstrapObservedProductionSealV1(FrozenModel):
    schema_version: Literal["1"]
    production_enabled: Literal[True]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    bootstrap_receipt_sha256: Sha256
    requester_client_application_sha256: Sha256
    requester_broker_application_sha256: Sha256
    sealed_at: datetime
    production_seal_sha256: Sha256


class CatalogBootstrapCompletionReceiptV1(FrozenModel):
    schema_version: Literal["1"]
    result: Literal["READY"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    ready_receipt_file_sha256: Sha256
    broker_production_seal_sha256: Sha256
    completion_receipt_sha256: Sha256


def _canonical_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def finalize_bootstrap(
    evidence: CatalogBootstrapFinalEvidenceV1,
) -> CatalogBootstrapFinalReceiptV1:
    checked = CatalogBootstrapFinalEvidenceV1.model_validate(
        evidence.model_dump(mode="json")
    )
    exact_true = (
        checked.merged_binding_verified,
        checked.requester_installation_verified,
        checked.auditor_installation_verified,
        checked.requester_key_isolated,
        checked.auditor_key_github_only,
        checked.local_identities_and_acls_verified,
        checked.qualification_equivalent,
        checked.controller_enabled_readback,
    )
    valid = (
        all(exact_true)
        and checked.agent_process_owner == "AURORAAgent"
        and checked.hp_codex_process_count == 0
        and checked.github_controls_status == "ready"
        and checked.zero_budget_count == 3
        and len(checked.qualification_receipt_sha256s) == 3
        and len(set(checked.qualification_receipt_sha256s)) == 3
        and checked.disabled_bootstrap_request_count == 1
        and checked.production_request_count == 0
        and checked.production_run_count == 0
        and checked.post_enable_controls_status == "ready"
    )
    if not valid:
        raise ValueError("CATALOG_BOOTSTRAP_FINAL_EVIDENCE_INVALID")
    payload: dict[str, object] = {
        "schema_version": "1",
        "result": "READY",
        "repository": checked.repository,
        "protected_commit_sha": checked.protected_commit_sha,
        "public_binding_sha256": checked.public_binding_sha256,
        "qualification_receipt_sha256s": list(
            checked.qualification_receipt_sha256s
        ),
        "controller_enabled_readback": True,
        "production_request_count": 0,
        "production_run_count": 0,
    }
    return CatalogBootstrapFinalReceiptV1.model_validate(
        {
            **payload,
            "receipt_sha256": hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        }
    )


def canonical_ready_receipt_bytes(receipt: CatalogBootstrapFinalReceiptV1) -> bytes:
    checked = CatalogBootstrapFinalReceiptV1.model_validate(
        receipt.model_dump(mode="json")
    )
    return _canonical_bytes(checked.model_dump(mode="json")) + b"\n"


def complete_sealed_bootstrap(
    receipt: CatalogBootstrapFinalReceiptV1,
    production_seal: CatalogBootstrapObservedProductionSealV1,
) -> CatalogBootstrapCompletionReceiptV1:
    """Verify the post-receipt seal without creating a cryptographic cycle."""

    ready = CatalogBootstrapFinalReceiptV1.model_validate(
        receipt.model_dump(mode="json")
    )
    seal = CatalogBootstrapObservedProductionSealV1.model_validate(
        production_seal.model_dump(mode="json")
    )
    ready_file_sha256 = hashlib.sha256(canonical_ready_receipt_bytes(ready)).hexdigest()
    unsigned_seal = seal.model_copy(update={"production_seal_sha256": "0" * 64})
    expected_seal_sha256 = hashlib.sha256(
        _canonical_bytes(unsigned_seal.model_dump(mode="json"))
    ).hexdigest()
    if (
        seal.protected_commit_sha != ready.protected_commit_sha
        or seal.bootstrap_receipt_sha256 != ready_file_sha256
        or seal.production_seal_sha256 != expected_seal_sha256
    ):
        raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_SEAL_INVALID")
    payload: dict[str, object] = {
        "schema_version": "1",
        "result": "READY",
        "repository": ready.repository,
        "protected_commit_sha": ready.protected_commit_sha,
        "ready_receipt_file_sha256": ready_file_sha256,
        "broker_production_seal_sha256": seal.production_seal_sha256,
    }
    return CatalogBootstrapCompletionReceiptV1.model_validate(
        {
            **payload,
            "completion_receipt_sha256": hashlib.sha256(
                _canonical_bytes(payload)
            ).hexdigest(),
        }
    )
