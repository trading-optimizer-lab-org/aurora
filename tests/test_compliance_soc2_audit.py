"""Tests for quantforge.compliance.soc2_audit."""
from __future__ import annotations

import json

import pytest

from aurora.compliance.soc2_audit import (
    GENESIS_HASH,
    SOC2AuditTrail,
    SOC2Config,
)


@pytest.fixture
def trail(tmp_path) -> SOC2AuditTrail:
    cfg = SOC2Config(log_path=str(tmp_path / "audit.jsonl"))
    return SOC2AuditTrail(cfg)


def test_first_event_chains_to_genesis(trail):
    rec = trail.append("login", {"user": "alice"})
    assert rec["prior_hash"] == GENESIS_HASH
    assert len(rec["this_hash"]) == 64


def test_chain_links_consecutive_events(trail):
    a = trail.append("login", {"user": "alice"})
    b = trail.append("trade_exec", {"order_id": "O-1"})
    assert b["prior_hash"] == a["this_hash"]


def test_verify_clean_chain(trail):
    trail.append("e1", {})
    trail.append("e2", {})
    trail.append("e3", {})
    report = trail.verify()
    assert report["ok"] is True
    assert report["broken_index"] is None


def test_verify_detects_tampering(trail, tmp_path):
    trail.append("e1", {"x": 1})
    trail.append("e2", {"x": 2})
    trail.append("e3", {"x": 3})
    # Tamper: rewrite the second line with altered payload but keep its hash.
    log_path = tmp_path / "audit.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["payload"] = {"x": 999}
    lines[1] = json.dumps(rec, sort_keys=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = trail.verify()
    assert report["ok"] is False
    assert report["broken_index"] == 1


def test_tip_returns_last(trail):
    trail.append("e1", {})
    last = trail.append("e2", {"final": True})
    tip = trail.tip()
    assert tip["this_hash"] == last["this_hash"]


def test_tip_empty_returns_none(trail):
    assert trail.tip() is None


def test_verify_empty_log_is_ok(trail):
    report = trail.verify()
    assert report["ok"] is True
    assert report["n_events"] == 0


def test_actor_default(trail):
    cfg = SOC2Config(log_path=str(trail._path), actor_default="qf-bot")
    t2 = SOC2AuditTrail(cfg)
    rec = t2.append("system_event")
    assert rec["actor"] == "qf-bot"
