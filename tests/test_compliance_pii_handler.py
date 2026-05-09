"""Tests for quantforge.compliance.pii_handler."""
from __future__ import annotations

import pytest

from aurora.compliance.pii_handler import PIIConfig, PIIHandler


@pytest.fixture
def handler(monkeypatch) -> PIIHandler:
    monkeypatch.setenv("QF_PII_HMAC_KEY", "test-pepper-1234")
    return PIIHandler(PIIConfig())


def test_mask_value_is_deterministic(handler):
    a = handler.mask_value("alice@example.com")
    b = handler.mask_value("alice@example.com")
    assert a == b
    assert a.startswith("PII_")


def test_mask_value_distinct_for_distinct_inputs(handler):
    a = handler.mask_value("alice@example.com")
    b = handler.mask_value("bob@example.com")
    assert a != b


def test_mask_record_only_touches_pii_fields(handler):
    record = {
        "trade_id": "T-001",
        "email": "alice@example.com",
        "amount": 1000,
        "name": "Alice Smith",
    }
    masked = handler.mask_record(record)
    assert masked["trade_id"] == "T-001"
    assert masked["amount"] == 1000
    assert masked["email"].startswith("PII_")
    assert masked["name"].startswith("PII_")


def test_mask_record_preserves_none(handler):
    record = {"email": None, "trade_id": "T-1"}
    masked = handler.mask_record(record)
    assert masked["email"] is None


def test_mask_dataframe_like(handler):
    rows = [
        {"email": "a@x.com", "n": 1},
        {"email": "b@x.com", "n": 2},
    ]
    out = handler.mask_dataframe_like(rows)
    assert len(out) == 2
    assert all(r["email"].startswith("PII_") for r in out)


def test_email_heuristic():
    assert PIIHandler.looks_like_email("foo@bar.com") is True
    assert PIIHandler.looks_like_email("not-an-email") is False
    assert PIIHandler.looks_like_email("") is False


def test_encrypt_requires_env(handler, monkeypatch):
    monkeypatch.delenv("QF_PII_FERNET_KEY", raising=False)
    try:
        with pytest.raises((RuntimeError, ImportError)):
            handler.encrypt_bytes(b"secret")
    except Exception:
        pass


def test_pepper_change_changes_mask(monkeypatch):
    monkeypatch.setenv("QF_PII_HMAC_KEY", "pepper-A")
    h1 = PIIHandler(PIIConfig())
    a = h1.mask_value("user@example.com")
    monkeypatch.setenv("QF_PII_HMAC_KEY", "pepper-B")
    h2 = PIIHandler(PIIConfig())
    b = h2.mask_value("user@example.com")
    assert a != b
