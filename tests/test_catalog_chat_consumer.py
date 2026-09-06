"""Consumer wiring only; Windows owner checks are tested separately."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun import catalog_chat_consumer as consumer

INTENT_ID = "018f47a2-6e91-4c34-8000-000000000001"
NAME = f"{INTENT_ID}.intent.json"
PAYLOAD = ('{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
           f'"intent_id":"{INTENT_ID}"}}').encode()


def test_consumer_authenticates_before_submitting(tmp_path, monkeypatch):
    (tmp_path / "chat-inbox").mkdir()
    events = []
    def reader(**kw):
        assert kw == {"path": tmp_path / "chat-inbox" / NAME, "expected_owner_sid": "S-1-5-21-123"}
        events.append("read")
        return PAYLOAD
    def submit(**kw):
        assert kw["intent"].intent_id == INTENT_ID
        assert kw["broker_root"] == tmp_path
        events.append("submit")
        return "test-receipt"
    monkeypatch.setattr(consumer, "read_authenticated_intent_file", reader)
    monkeypatch.setattr(consumer, "submit_registered_chat_intent", submit)
    result = consumer.consume_authenticated_chat_file(
        broker_root=tmp_path, input_name=NAME, expected_sender_sid="S-1-5-21-123",
        observed_at=datetime.now(timezone.utc),
    )
    assert result == "test-receipt"
    assert events == ["read", "submit"]


@pytest.mark.parametrize("name", ["../other", "input.json", "C:/other.intent.json", NAME + ":ads"])
def test_consumer_rejects_noncanonical_names_before_read(tmp_path, monkeypatch, name):
    monkeypatch.setattr(consumer, "read_authenticated_intent_file", lambda **kw: pytest.fail("must not read"))
    with pytest.raises(ValueError, match="CHAT_INPUT_NAME_INVALID"):
        consumer.consume_authenticated_chat_file(
            broker_root=tmp_path, input_name=name, expected_sender_sid="S-1-5-21-123",
            observed_at=datetime.now(timezone.utc),
        )


def test_consumer_never_submits_an_unauthenticated_file(tmp_path, monkeypatch):
    (tmp_path / "chat-inbox").mkdir()
    def denied(**kw):
        raise ValueError("CHAT_INPUT_OWNER_MISMATCH")
    monkeypatch.setattr(consumer, "read_authenticated_intent_file", denied)
    monkeypatch.setattr(consumer, "submit_registered_chat_intent", lambda **kw: pytest.fail("must not submit"))
    with pytest.raises(ValueError, match="CHAT_INPUT_OWNER_MISMATCH"):
        consumer.consume_authenticated_chat_file(
            broker_root=tmp_path, input_name=NAME, expected_sender_sid="S-1-5-21-123",
            observed_at=datetime.now(timezone.utc),
        )


def test_consumer_requires_payload_identity_to_match_filename(tmp_path, monkeypatch):
    (tmp_path / "chat-inbox").mkdir()
    payload = PAYLOAD.replace(INTENT_ID.encode(), b"018f47a2-6e91-4c34-8000-000000000002")
    monkeypatch.setattr(consumer, "read_authenticated_intent_file", lambda **kw: payload)
    monkeypatch.setattr(consumer, "submit_registered_chat_intent", lambda **kw: pytest.fail("must not submit"))
    with pytest.raises(ValueError, match="CHAT_INPUT_ID_MISMATCH"):
        consumer.consume_authenticated_chat_file(
            broker_root=tmp_path, input_name=NAME, expected_sender_sid="S-1-5-21-123",
            observed_at=datetime.now(timezone.utc),
        )
