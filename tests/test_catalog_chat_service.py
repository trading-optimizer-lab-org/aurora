"""Fixed lifecycle wiring, with delivery replaced by a no-production callback."""

from pathlib import Path
from threading import Event
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun import catalog_chat_service as service

IDENTIFIER = "018f47a2-6e91-4c34-8000-000000000001"


class _NoSleepEvent(Event):
    def wait(self, timeout=None):
        return self.is_set()


class _ScandirStream:
    def __init__(self, names):
        self._entries = iter(SimpleNamespace(name=name) for name in names)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._entries)

    def close(self):
        self.closed = True


def _service_scandir(monkeypatch, *, inbox_names, reply_names):
    streams = {
        "chat-inbox": _ScandirStream(inbox_names),
        "chat-replies": _ScandirStream(reply_names),
    }

    def scandir(path):
        return streams[path.name]

    monkeypatch.setattr(service.os, "scandir", scandir)
    return streams


def test_service_resumes_pending_reply_even_if_input_is_absent(tmp_path, monkeypatch):
    for name in ("chat-inbox", "chat-replies", "chat-intents"):
        (tmp_path / name).mkdir()
    (tmp_path / "chat-replies" / f"{IDENTIFIER}.delivery.json").write_text("test-marker")
    stop = Event()
    seen = []
    monkeypatch.setattr(service, "_load_config", lambda root: SimpleNamespace(sender_sid="S-1-5-21-1-2-3-1001"))
    monkeypatch.setattr(service, "_exclusive_service_lock", lambda root: nullcontext())
    def process(**kwargs):
        seen.append(kwargs["intent_id"])
        stop.set()
        return SimpleNamespace(status="pending")
    monkeypatch.setattr(service, "process_chat_delivery", process)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)
    assert seen == [IDENTIFIER]


def test_service_config_requires_administrator_owned_closed_json(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    def read(**kwargs):
        assert kwargs["path"] == tmp_path / "config/chat-entry-v1.json"
        assert kwargs["expected_owner_sid"] == "S-1-5-32-544"
        return b'{"schema_version":"1","sender_sid":"S-1-5-21-1-2-3-1001","command":"forbidden"}'
    monkeypatch.setattr(service, "read_authenticated_intent_file", read)
    with pytest.raises(ValueError):
        service._load_config(tmp_path)


def test_real_windows_exclusive_lock_releases_after_context(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows only")
    (tmp_path / "chat-intents").mkdir()
    with service._exclusive_service_lock(tmp_path):
        with pytest.raises(ValueError, match="CHAT_SERVICE_LOCK_UNAVAILABLE"):
            with service._exclusive_service_lock(tmp_path):
                pytest.fail("must not acquire twice")
    with service._exclusive_service_lock(tmp_path):
        pass


def test_service_restart_observes_durable_reply_without_second_submission(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import json
    from aurora.infra.sp500_megarun.catalog_requester import CatalogRequesterReceiptV1

    for name in ("chat-inbox", "chat-replies", "chat-intents"):
        (tmp_path / name).mkdir()
    source = tmp_path / "chat-inbox" / f"{IDENTIFIER}.intent.json"
    source.write_text("input is authenticated at the replaced external boundary")
    monkeypatch.setattr(service, "_load_config", lambda root: SimpleNamespace(sender_sid="S-1-5-21-1-2-3-1001"))
    stop = Event()
    def receipt(status):
        return CatalogRequesterReceiptV1.create(
            status=status, reason_code="REQUEST_BROKER_PENDING" if status == "pending" else "REQUEST_SUBMITTED",
            submission_key_sha256="a" * 64,
            request_id="018f47a2-6e91-7c34-8000-000000000001",
            campaign_key="sp500-optimized-catalog-v1", launch_generation=1,
            observed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
            issue_number=7 if status == "submitted" else None,
            request_sha256="b" * 64 if status == "submitted" else None,
        )
    def deliver(**kwargs):
        assert kwargs["input_name"] == f"{IDENTIFIER}.intent.json"
        stop.set()
        return receipt("pending")
    monkeypatch.setattr(service, "consume_authenticated_chat_file", deliver)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)
    path = tmp_path / "chat-replies" / f"{IDENTIFIER}.delivery.json"
    assert json.loads(path.read_text())["status"] == "pending"
    source.unlink()
    stop.clear()
    monkeypatch.setattr(service, "consume_authenticated_chat_file", lambda **kw: pytest.fail("restart resubmitted"))
    def observe(**kwargs):
        assert kwargs["intent_id"] == IDENTIFIER
        stop.set()
        return receipt("submitted")
    monkeypatch.setattr(service, "read_bound_chat_receipt", observe)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)
    saved = json.loads(path.read_text())
    assert saved["status"] == "submitted"
    assert saved["attempts"] == 1
    assert saved["receipt"]["issue_number"] == 7


def test_service_observes_reply_before_effectively_unending_inbox(tmp_path, monkeypatch):
    for name in ("chat-inbox", "chat-replies", "chat-intents"):
        (tmp_path / name).mkdir()
    reply_id = "018f47a2-6e91-4c34-8000-000000000099"
    inbox_names = (f"018f47a2-6e91-4c34-8000-{index:012x}.intent.json" for index in range(1, 1_000_000))
    streams = _service_scandir(
        monkeypatch,
        inbox_names=inbox_names,
        reply_names=(f"{reply_id}.delivery.json",),
    )
    monkeypatch.setattr(service, "_load_config", lambda root: SimpleNamespace(sender_sid="S-1-5-21-1-2-3-1001"))
    monkeypatch.setattr(service, "_exclusive_service_lock", lambda root: nullcontext())
    stop = _NoSleepEvent()
    observed = []

    def process(**kwargs):
        observed.append(kwargs["intent_id"])
        assert kwargs["intent_id"] == reply_id
        stop.set()
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(service, "process_chat_delivery", process)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)

    assert observed == [reply_id]
    assert streams["chat-inbox"].closed
    assert streams["chat-replies"].closed


def test_service_rechecks_evicted_terminal_cache_entry_without_redelivery(tmp_path, monkeypatch):
    for name in ("chat-inbox", "chat-replies", "chat-intents"):
        (tmp_path / name).mkdir()
    identifiers = [
        f"018f47a2-6e91-4c34-8000-{index:012x}"
        for index in range(1, 1_026)
    ]
    streams = _service_scandir(
        monkeypatch,
        inbox_names=[*(f"{identifier}.intent.json" for identifier in identifiers),
                     f"{identifiers[0]}.intent.json"],
        reply_names=(),
    )
    monkeypatch.setattr(service, "_load_config", lambda root: SimpleNamespace(sender_sid="S-1-5-21-1-2-3-1001"))
    monkeypatch.setattr(service, "_exclusive_service_lock", lambda root: nullcontext())
    stop = _NoSleepEvent()
    processed = []

    def process(**kwargs):
        processed.append(kwargs["intent_id"])
        if len(processed) == 1_026:
            stop.set()
        return SimpleNamespace(status="submitted")

    monkeypatch.setattr(service, "process_chat_delivery", process)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)

    assert len(processed) == 1_026
    assert processed.count(identifiers[0]) == 2
    assert streams["chat-inbox"].closed


def test_reply_backlog_yields_to_new_input_after_one_bounded_batch(tmp_path, monkeypatch):
    for name in ("chat-inbox", "chat-replies", "chat-intents"):
        (tmp_path / name).mkdir()
    _service_scandir(
        monkeypatch, inbox_names=(f"{IDENTIFIER}.intent.json",),
        reply_names=(f"018f47a2-6e91-4c34-9000-{index:012x}.delivery.json" for index in range(10000)),
    )
    monkeypatch.setattr(service, "_load_config", lambda root: SimpleNamespace(sender_sid="S-1-5-21-1-2-3-1001"))
    monkeypatch.setattr(service, "_exclusive_service_lock", lambda root: nullcontext())
    stop = _NoSleepEvent()
    observed = []
    def process(**kwargs):
        observed.append(kwargs["intent_id"])
        if kwargs["intent_id"] == IDENTIFIER:
            stop.set()
        elif len(observed) > 32:
            pytest.fail("reply backlog starved the new input")
        return SimpleNamespace(status="pending")
    monkeypatch.setattr(service, "process_chat_delivery", process)
    service.serve_chat_entry(broker_root=tmp_path, _stop=stop)
    assert observed[-1] == IDENTIFIER
    assert len(observed) == 33
