"""Bounded durable delivery-state tests; receipts are synthetic model fixtures."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from aurora.infra.sp500_megarun import catalog_chat_delivery as subject
from aurora.infra.sp500_megarun.catalog_requester import CatalogRequesterReceiptV1


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
CAMPAIGN = "sp500-optimized-catalog-v1"
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"
SUBMISSION_KEY = "a" * 64


def _receipt(
    status: Literal["pending", "submitted", "existing", "blocked"] = "pending",
    *,
    submission_key: str = SUBMISSION_KEY,
) -> CatalogRequesterReceiptV1:
    submitted = status in {"submitted", "existing"}
    return CatalogRequesterReceiptV1.create(
        status=status,
        reason_code=("REQUEST_SUBMITTED" if submitted else "REQUEST_BROKER_PENDING"),
        submission_key_sha256=submission_key,
        request_id=REQUEST_ID,
        campaign_key=CAMPAIGN,
        launch_generation=1,
        observed_at=NOW,
        issue_number=7 if submitted else None,
        request_sha256="b" * 64 if submitted else None,
    )


def _state(
    intent_id: str,
    status: Literal[
        "delivering", "retryable", "pending", "submitted", "existing", "blocked"
    ],
    attempts: int,
    receipt: CatalogRequesterReceiptV1 | None,
    reason_code: str,
) -> subject.ChatDeliveryV1:
    return subject.ChatDeliveryV1(
        schema_version="1",
        intent_id=intent_id,
        status=status,
        attempts=attempts,
        receipt=receipt,
        reason_code=reason_code,
    )


def _write_state(reply_dir: Path, state: subject.ChatDeliveryV1) -> Path:
    path = reply_dir / f"{state.intent_id}.delivery.json"
    path.write_bytes(subject.canonical_model_bytes(state) + b"\n")
    return path


@pytest.fixture
def delivery_dir(tmp_path: Path) -> Path:
    replies = tmp_path / "replies"
    replies.mkdir()
    return replies


@pytest.mark.parametrize("status", ["pending", "submitted"])
def test_reply_for_another_intent_is_rejected_without_overwrite(
    delivery_dir: Path, status: Literal["pending", "submitted"]
) -> None:
    requested_id, other_id = str(uuid4()), str(uuid4())
    stored = _state(other_id, status, 1, _receipt(status), "CHAT_DELIVERY_PENDING")
    path = delivery_dir / f"{requested_id}.delivery.json"
    original = subject.canonical_model_bytes(stored) + b"\n"
    path.write_bytes(original)
    result = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=requested_id,
        deliver=lambda: pytest.fail("mismatched state must not deliver"),
        observe=lambda previous: pytest.fail("mismatched state must not observe"),
    )
    assert result.status == "blocked"
    assert result.intent_id == requested_id
    assert result.reason_code == "CHAT_DELIVERY_STATE_INVALID"
    assert path.read_bytes() == original


def test_pending_observes_without_delivering(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    pending = _receipt()
    _write_state(delivery_dir, _state(intent_id, "pending", 1, pending, "CHAT_DELIVERY_PENDING"))
    calls: list[str] = []

    def observe_pending(receipt: CatalogRequesterReceiptV1) -> CatalogRequesterReceiptV1:
        calls.append(receipt.status)
        return _receipt("submitted")

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=lambda: pytest.fail("pending state must never deliver"),
        observe=observe_pending,
    )

    assert calls == ["pending"]
    assert result.status == "submitted"
    assert result.receipt is not None and result.receipt.status == "submitted"


def test_observed_receipt_mismatch_blocks_deterministically(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    pending = _receipt()
    path = _write_state(delivery_dir, _state(intent_id, "pending", 1, pending, "CHAT_DELIVERY_PENDING"))

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=lambda: pytest.fail("mismatch must not deliver"),
        observe=lambda receipt: _receipt("submitted", submission_key="c" * 64),
    )

    assert result.status == "blocked"
    assert result.reason_code == "CHAT_DELIVERY_RECEIPT_MISMATCH"
    assert subject.ChatDeliveryV1.model_validate_json(path.read_bytes()[:-1]).status == "blocked"


def test_malformed_state_blocks_without_overwrite(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    path = delivery_dir / f"{intent_id}.delivery.json"
    original = b'{"schema_version":"1","status":'
    path.write_bytes(original)
    calls: list[str] = []

    def deliver_malformed() -> CatalogRequesterReceiptV1:
        calls.append("deliver")
        return _receipt("submitted")

    def observe_malformed(_receipt_value: CatalogRequesterReceiptV1) -> None:
        calls.append("observe")

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=deliver_malformed,
        observe=observe_malformed,
    )

    assert result.status == "blocked"
    assert result.reason_code == "CHAT_DELIVERY_STATE_INVALID"
    assert calls == []
    assert path.read_bytes() == original


def test_interrupted_delivering_recovery_consumes_next_bounded_attempt(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    _write_state(delivery_dir, _state(intent_id, "delivering", 1, None, "CHAT_DELIVERY_ATTEMPTING"))
    observed_attempts: list[int] = []

    def deliver() -> CatalogRequesterReceiptV1:
        on_disk = subject.ChatDeliveryV1.model_validate_json(
            (delivery_dir / f"{intent_id}.delivery.json").read_bytes()[:-1]
        )
        observed_attempts.append(on_disk.attempts)
        return _receipt("submitted")

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=deliver,
        observe=lambda receipt: pytest.fail("delivering state must not observe"),
    )

    assert observed_attempts == [2]
    assert result.status == "submitted" and result.attempts == 2


def test_maximum_three_callback_attempts_survive_restarts(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    calls = 0

    def deliver() -> CatalogRequesterReceiptV1:
        nonlocal calls
        calls += 1
        raise OSError("private detail")

    for expected_attempt in (1, 2, 3):
        result = subject.process_chat_delivery(
            reply_dir=delivery_dir,
            intent_id=intent_id,
            deliver=deliver,
            observe=lambda receipt: pytest.fail("retryable delivery must not observe"),
        )
        expected_status = "retryable" if expected_attempt < 3 else "blocked"
        assert result.status == expected_status and result.attempts == expected_attempt

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=deliver,
        observe=lambda receipt: pytest.fail("max attempts must not deliver or observe"),
    )
    assert calls == 3
    assert result.status == "blocked" and result.attempts == 3


def test_deterministic_value_error_does_not_retry(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    calls = 0

    def deliver() -> CatalogRequesterReceiptV1:
        nonlocal calls
        calls += 1
        raise ValueError("CHAT_CAMPAIGN_TICKET_NOT_AVAILABLE: secret detail")

    first = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=intent_id, deliver=deliver, observe=lambda receipt: None
    )
    second = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=intent_id, deliver=deliver, observe=lambda receipt: None
    )

    assert calls == 1
    assert first.status == second.status == "blocked"
    assert first.reason_code == second.reason_code == "CHAT_CAMPAIGN_TICKET_NOT_AVAILABLE"


def test_transient_os_error_recovers(delivery_dir: Path) -> None:
    intent_id = str(uuid4())
    calls = 0

    def deliver() -> CatalogRequesterReceiptV1:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("not persisted")
        return _receipt("existing")

    first = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=intent_id, deliver=deliver, observe=lambda receipt: None
    )
    second = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=intent_id, deliver=deliver, observe=lambda receipt: None
    )

    assert first.status == "retryable" and first.reason_code == "CHAT_DELIVERY_IO"
    assert second.status == "existing" and calls == 2


def test_persist_failure_prevents_callback(delivery_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    intent_id = str(uuid4())
    calls: list[str] = []

    def fail_persist(*args: object, **kwargs: object) -> None:
        raise OSError("secret path")

    monkeypatch.setattr(subject, "_persist_state", fail_persist)
    def deliver_persist_failure() -> CatalogRequesterReceiptV1:
        calls.append("deliver")
        return _receipt("submitted")

    def observe_persist_failure(_receipt_value: CatalogRequesterReceiptV1) -> None:
        calls.append("observe")

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir,
        intent_id=intent_id,
        deliver=deliver_persist_failure,
        observe=observe_persist_failure,
    )

    assert result.status == "blocked" and result.reason_code == "CHAT_DELIVERY_IO"
    assert calls == []


def test_raw_exception_details_never_enter_state(delivery_dir: Path) -> None:
    intent_id = str(uuid4())

    def deliver() -> CatalogRequesterReceiptV1:
        raise RuntimeError("SECRET /private/path token")

    result = subject.process_chat_delivery(
        reply_dir=delivery_dir, intent_id=intent_id, deliver=deliver, observe=lambda receipt: None
    )
    encoded = (delivery_dir / f"{intent_id}.delivery.json").read_text(encoding="utf-8")

    assert result.status == "blocked"
    assert result.reason_code == "CHAT_DELIVERY_INVALID_INPUT"
    assert "SECRET" not in encoded and "/private/path" not in encoded and "token" not in encoded
