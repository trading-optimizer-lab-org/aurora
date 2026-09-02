from __future__ import annotations

import hashlib
import json

import pytest

from infra.sp500_megarun.catalog_bootstrap_finalizer import (
    CatalogBootstrapObservedProductionSealV1,
    CatalogBootstrapFinalEvidenceV1,
    canonical_ready_receipt_bytes,
    complete_sealed_bootstrap,
    finalize_bootstrap,
)


def complete_evidence() -> CatalogBootstrapFinalEvidenceV1:
    return CatalogBootstrapFinalEvidenceV1(
        schema_version="1",
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha="a" * 40,
        public_binding_sha256="b" * 64,
        merged_binding_verified=True,
        requester_installation_verified=True,
        auditor_installation_verified=True,
        requester_key_isolated=True,
        auditor_key_github_only=True,
        local_identities_and_acls_verified=True,
        agent_process_owner="AURORAAgent",
        hp_codex_process_count=0,
        github_controls_status="ready",
        zero_budget_count=3,
        qualification_receipt_sha256s=("c" * 64, "d" * 64, "e" * 64),
        qualification_equivalent=True,
        disabled_bootstrap_request_count=1,
        production_request_count=0,
        production_run_count=0,
        controller_enabled_readback=True,
        post_enable_controls_status="ready",
    )


def _production_seal(receipt: object) -> CatalogBootstrapObservedProductionSealV1:
    import hashlib

    ready_hash = hashlib.sha256(canonical_ready_receipt_bytes(receipt)).hexdigest()
    base = {
        "schema_version": "1",
        "production_enabled": True,
        "protected_commit_sha": "a" * 40,
        "bootstrap_receipt_sha256": ready_hash,
        "requester_client_application_sha256": "1" * 64,
        "requester_broker_application_sha256": "2" * 64,
        "sealed_at": "2026-08-23T12:00:00Z",
        "production_seal_sha256": "0" * 64,
    }
    base["production_seal_sha256"] = hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CatalogBootstrapObservedProductionSealV1.model_validate(base)


def test_every_required_final_fact_is_mandatory() -> None:
    complete = complete_evidence()
    for field in CatalogBootstrapFinalEvidenceV1.model_fields:
        if field == "schema_version":
            continue
        with pytest.raises(ValueError):
            finalize_bootstrap(complete.model_copy(update={field: None}))


def test_final_ready_has_zero_production_activity() -> None:
    receipt = finalize_bootstrap(complete_evidence())
    assert receipt.result == "READY"
    assert receipt.controller_enabled_readback is True
    assert receipt.production_request_count == 0
    assert receipt.production_run_count == 0
    assert len(receipt.receipt_sha256) == 64
    completion = complete_sealed_bootstrap(receipt, _production_seal(receipt))
    assert completion.result == "READY"
    assert completion.ready_receipt_file_sha256 == hashlib.sha256(
        canonical_ready_receipt_bytes(receipt)
    ).hexdigest()


def test_final_ready_allows_user_codex_to_remain_open() -> None:
    receipt = finalize_bootstrap(
        complete_evidence().model_copy(update={"hp_codex_process_count": 3})
    )
    assert receipt.result == "READY"


def test_any_drift_or_activity_blocks_ready() -> None:
    complete = complete_evidence()
    mutations = (
        {"merged_binding_verified": False},
        {"agent_process_owner": "HP"},
        {"zero_budget_count": 2},
        {"qualification_equivalent": False},
        {"production_request_count": 1},
        {"post_enable_controls_status": "blocked"},
    )
    for update in mutations:
        with pytest.raises(ValueError, match="CATALOG_BOOTSTRAP_FINAL_EVIDENCE_INVALID"):
            finalize_bootstrap(complete.model_copy(update=update))


def test_receipt_is_canonical_and_contains_no_private_material() -> None:
    receipt = finalize_bootstrap(complete_evidence())
    raw = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    for marker in ("private_key", "client_secret", "webhook_secret", "password", "jwt", "token"):
        assert marker not in raw.casefold()


def test_production_seal_is_created_after_and_bound_to_ready_receipt() -> None:
    receipt = finalize_bootstrap(complete_evidence())
    seal = _production_seal(receipt)
    completion = complete_sealed_bootstrap(receipt, seal)
    assert completion.broker_production_seal_sha256 == seal.production_seal_sha256

    with pytest.raises(ValueError, match="CATALOG_BOOTSTRAP_PRODUCTION_SEAL_INVALID"):
        complete_sealed_bootstrap(
            receipt,
            seal.model_copy(update={"bootstrap_receipt_sha256": "9" * 64}),
        )
