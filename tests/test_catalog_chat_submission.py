"""Local binding/spool integration; mocked authority is NOT live authorization."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

from aurora.infra.sp500_megarun import catalog_chat_submission as subject
from aurora.infra.sp500_megarun.catalog_chat_intent import CatalogChatIntentV1
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunIntentDraftV1, canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_requester import (
    CatalogBrokerCapacityReceiptV1,
    CatalogRequesterConfigV1,
)

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
CAMPAIGN = "sp500-optimized-catalog-v1"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "broker"
    for directory in ("config", "chat-intents", "campaign-status", "inbox", "receipts"):
        (root / directory).mkdir(parents=True)
    config_bytes = (Path(__file__).parents[1] / "config/catalog_requester_v1.json").read_bytes()
    (root / "config/catalog_requester_v1.json").write_bytes(config_bytes)
    config = CatalogRequesterConfigV1.model_validate_json(config_bytes)
    draft = CatalogRunIntentDraftV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000001",
        campaign_key=CAMPAIGN, launch_generation=1, launch_ticket_sha256="1" * 64,
        previous_terminal_request_sha256=None, campaign_definition_sha256="2" * 64,
        prompt_sha256="3" * 64, authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True, automatic_recovery=True, max_same_failure_count=3,
    )
    monkeypatch.setattr(subject, "_load_verified_production_seal", lambda **kw: None)
    monkeypatch.setattr(subject, "build_registered_catalog_draft", lambda **kw: (config, draft))
    monkeypatch.setattr(subject, "_load_fresh_broker_capacity", lambda **kw: CatalogBrokerCapacityReceiptV1.create(
        observed_at=NOW, available=True, pending_entry_count=0, pending_bytes=0,
        maximum_pending_entries=32, maximum_inbox_bytes=131072,
    ))
    intent = CatalogChatIntentV1(schema_version="1", campaign_key=CAMPAIGN, intent_id=str(uuid4()))
    return root, intent


def test_retry_after_ticket_change_reuses_one_spool_request(installed, monkeypatch):
    root, intent = installed
    first = subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    def must_not_resolve(**kwargs):
        pytest.fail("Replay must not resolve today's different ticket")
    monkeypatch.setattr(subject, "build_registered_catalog_draft", must_not_resolve)
    second = subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    assert first == second
    assert len(list((root / "inbox").glob("*.request.json"))) == 1


def test_binding_survives_interruption_before_spool(installed, monkeypatch):
    root, intent = installed
    original = subject.submit_catalog_intent_to_spool
    def interrupt(**kwargs):
        raise OSError("simulated interruption")
    monkeypatch.setattr(subject, "submit_catalog_intent_to_spool", interrupt)
    with pytest.raises(OSError, match="simulated interruption"):
        subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    assert not list((root / "inbox").iterdir())
    monkeypatch.setattr(subject, "submit_catalog_intent_to_spool", original)
    def must_not_resolve(**kwargs):
        pytest.fail("Durable binding lost after interruption")
    monkeypatch.setattr(subject, "build_registered_catalog_draft", must_not_resolve)
    result = subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    assert result.status == "pending"
    assert len(list((root / "inbox").glob("*.request.json"))) == 1


def test_replay_still_requires_production_seal(installed, monkeypatch):
    root, intent = installed
    subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    def revoked(**kwargs):
        raise ValueError("SEAL_REVOKED")
    monkeypatch.setattr(subject, "_load_verified_production_seal", revoked)
    with pytest.raises(ValueError, match="SEAL_REVOKED"):
        subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)


def test_existing_exact_receipt_does_not_require_new_capacity(installed, monkeypatch):
    root, intent = installed
    first = subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    (root / "receipts" / f"{first.submission_key_sha256}.receipt.json").write_bytes(
        canonical_model_bytes(first) + b"\n"
    )
    def stale_capacity(**kwargs):
        raise ValueError("REQUEST_BROKER_CAPACITY_UNPROVEN")
    monkeypatch.setattr(subject, "_load_fresh_broker_capacity", stale_capacity)
    assert subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW) == first


def test_malformed_status_blocks_new_intent_without_binding(installed):
    root, intent = installed
    (root / "campaign-status" / f"{CAMPAIGN}.status.json").write_text(json.dumps({"state": "active"}))
    with pytest.raises(ValueError):
        subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    assert not list((root / "chat-intents").iterdir())
    assert not list((root / "inbox").iterdir())


def test_read_bound_receipt_never_resubmits_or_resolves_a_ticket(installed, monkeypatch):
    root, intent = installed
    first = subject.submit_registered_chat_intent(broker_root=root, intent=intent, observed_at=NOW)
    original = {p.name: p.read_bytes() for p in (root / "inbox").iterdir()}
    def forbidden(**kwargs):
        pytest.fail("Observation must never create or send a request")
    monkeypatch.setattr(subject, "build_registered_catalog_draft", forbidden)
    monkeypatch.setattr(subject, "submit_catalog_intent_to_spool", forbidden)
    assert subject.read_bound_chat_receipt(broker_root=root, intent_id=intent.intent_id) is None
    (root / "receipts" / f"{first.submission_key_sha256}.receipt.json").write_bytes(canonical_model_bytes(first) + b"\n")
    assert subject.read_bound_chat_receipt(broker_root=root, intent_id=intent.intent_id) == first
    assert {p.name: p.read_bytes() for p in (root / "inbox").iterdir()} == original


def test_read_unknown_intent_does_not_create_a_binding(installed):
    root, intent = installed
    with pytest.raises(ValueError, match="CHAT_INTENT_NOT_BOUND"):
        subject.read_bound_chat_receipt(broker_root=root, intent_id=intent.intent_id)
    assert not list((root / "chat-intents").iterdir())


def test_read_receipt_rejects_invalid_identifier_before_path_use(installed):
    root, _ = installed
    with pytest.raises(ValueError, match="CHAT_INTENT_ID_INVALID"):
        subject.read_bound_chat_receipt(broker_root=root, intent_id="invalid")
