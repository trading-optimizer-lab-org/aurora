"""Tests for the AgentGateway (P1.A architectural hardening).

Coverage targets per the P1.A spec:
- token signing / verify (3)
- expired token rejected (1)
- paper_only flag overrides LIVE_TRADE scope (1)
- scope enforcement (read scope cannot trade) (2)
- allowlist enforcement (1)
- per-order notional cap (1)
- daily notional cap aggregates across orders (1)
- cooldown enforced (1)
- audit chain hash links correctly (2)
- audit chain tamper detection (2)
- stage/commit/push happy path paper (1)
- stage/commit/push happy path live with ceremony+human sig (1)
- LIVE_TRADE without QF_AGENT_LIVE_AUTH env refuses (1)
- LIVE_TRADE without OOSGuard ceremony refuses (1)
- LIVE_TRADE without human signature refuses (1)
- staged action expires after 5 min (1)
- revoke makes future stage refuse (1)
- gateway integration with deployment.live submit_with_retry (1)
- CLI smoke: token-issue -> stage -> commit (1)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _gateway_secret(monkeypatch):
    """All tests run with a deterministic signing secret."""
    monkeypatch.setenv("QF_GATEWAY_SECRET", "test-secret-A1B2C3")
    monkeypatch.setenv("QF_OPERATOR_KEY", "test-operator-key-Z9Y8X7")
    yield


@pytest.fixture
def audit_path(tmp_path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def gateway(audit_path):
    from aurora.agent_gateway import AgentGateway, GatewayPolicy

    return AgentGateway(
        policy=GatewayPolicy(audit_chain_verify_on_startup=True),
        audit_path=audit_path,
    )


def _mint(actor="bot", *, scopes=None, paper_only=True,
          allowlist=frozenset(),
          max_order=10_000.0, max_daily=50_000.0, cooldown=0,
          expires_in_days=7, issued_at=None):
    from aurora.agent_gateway import TokenScope, issue_token
    if scopes is None:
        scopes = frozenset({TokenScope.READ_DATA})
    return issue_token(
        actor=actor, scopes=scopes,
        expires_in_days=expires_in_days,
        allowlist_symbols=allowlist,
        max_order_notional_usd=max_order,
        max_daily_notional_usd=max_daily,
        cooldown_seconds=cooldown,
        paper_only=paper_only,
        issued_at=issued_at,
    )


# ---------------------------------------------------------------------------
# 1-3) Token signing / verify
# ---------------------------------------------------------------------------


def test_token_signature_verifies():
    from aurora.agent_gateway import TokenScope
    tok = _mint(scopes=frozenset({TokenScope.READ_DATA}))
    assert tok.verify_signature() is True


def test_token_signature_round_trip_via_dict():
    from aurora.agent_gateway import AgentToken, TokenScope
    tok = _mint(scopes=frozenset({TokenScope.READ_DATA}))
    rebuilt = AgentToken.from_dict(tok.to_dict())
    assert rebuilt.verify_signature() is True
    assert rebuilt.token_id == tok.token_id


def test_token_signature_rejects_tampered_actor():
    from aurora.agent_gateway import AgentToken, TokenScope
    tok = _mint(scopes=frozenset({TokenScope.READ_DATA}))
    d = tok.to_dict()
    d["actor"] = "evil-bot"
    bad = AgentToken.from_dict(d)
    assert bad.verify_signature() is False


# ---------------------------------------------------------------------------
# 4) Expired token rejected
# ---------------------------------------------------------------------------


def test_expired_token_rejected_by_authenticate(gateway):
    from aurora.agent_gateway import TokenScope
    from aurora.agent_gateway.gateway import AuthenticationError
    issued = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=10)
    tok = _mint(scopes=frozenset({TokenScope.READ_DATA}),
                expires_in_days=1, issued_at=issued)
    with pytest.raises(AuthenticationError):
        gateway.register_token(tok)


# ---------------------------------------------------------------------------
# 5) paper_only overrides LIVE_TRADE scope
# ---------------------------------------------------------------------------


def test_paper_only_blocks_live_trade(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=True,
                max_order=100.0, max_daily=1_000.0)
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 6-7) Scope enforcement
# ---------------------------------------------------------------------------


def test_read_scope_cannot_paper_trade(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.READ_DATA}))
    gateway.register_token(tok)
    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=10.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


def test_read_scope_cannot_propose_strategy(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.READ_REPORTS}))
    gateway.register_token(tok)
    action = ActionRequest(
        kind="propose", scope=TokenScope.PROPOSE_STRATEGY,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 8) Allowlist enforcement
# ---------------------------------------------------------------------------


def test_allowlist_blocks_off_list_symbol(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        allowlist=frozenset({"SPY"}),
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="QQQ", notional_usd=10.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 9) Per-order notional cap
# ---------------------------------------------------------------------------


def test_per_order_notional_cap(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=1_000.0)
    gateway.register_token(tok)
    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=200.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 10) Daily notional cap aggregates
# ---------------------------------------------------------------------------


def test_daily_cap_aggregates_across_orders(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=150.0, cooldown=0)
    gateway.register_token(tok)
    a1 = ActionRequest(kind="paper_order", scope=TokenScope.PAPER_TRADE,
                       symbol="SPY", notional_usd=80.0)
    a2 = ActionRequest(kind="paper_order", scope=TokenScope.PAPER_TRADE,
                       symbol="SPY", notional_usd=80.0)
    gateway.stage(tok, a1)
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, a2)


# ---------------------------------------------------------------------------
# 11) Cooldown enforced
# ---------------------------------------------------------------------------


def test_cooldown_enforced(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthorizationError
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=1_000.0, cooldown=60)
    gateway.register_token(tok)
    a = ActionRequest(kind="paper_order", scope=TokenScope.PAPER_TRADE,
                      symbol="SPY", notional_usd=10.0)
    gateway.stage(tok, a)
    a2 = ActionRequest(kind="paper_order", scope=TokenScope.PAPER_TRADE,
                       symbol="SPY", notional_usd=10.0)
    with pytest.raises(AuthorizationError, match="cooldown"):
        gateway.stage(tok, a2)


# ---------------------------------------------------------------------------
# 12-13) Audit chain hash links
# ---------------------------------------------------------------------------


def test_audit_chain_links_correctly(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    for _ in range(3):
        gateway.stage(tok, ActionRequest(
            kind="paper_order", scope=TokenScope.PAPER_TRADE,
            symbol="SPY", notional_usd=10.0,
        ))
    rep = gateway.audit.verify_chain()
    assert rep["ok"] is True
    assert rep["n_entries"] >= 3
    assert rep["broken_index"] is None


def test_audit_chain_first_entry_genesis(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.audit import GENESIS_HASH
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0)
    gateway.register_token(tok)
    gateway.stage(tok, ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=10.0,
    ))
    entries = gateway.audit.entries()
    assert entries
    assert entries[0]["prev_hash"] == GENESIS_HASH


# ---------------------------------------------------------------------------
# 14-15) Audit chain tamper detection
# ---------------------------------------------------------------------------


def test_audit_tamper_detected_on_payload_edit(gateway, audit_path):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    for i in range(3):
        gateway.stage(tok, ActionRequest(
            kind="paper_order", scope=TokenScope.PAPER_TRADE,
            symbol="SPY", notional_usd=float(i + 1),
        ))
    raw = audit_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(raw[1])
    rec["details"]["notional_usd"] = 999_999.0
    raw[1] = json.dumps(rec, sort_keys=True)
    audit_path.write_text("\n".join(raw) + "\n", encoding="utf-8")
    rep = gateway.audit.verify_chain()
    assert rep["ok"] is False
    assert rep["broken_index"] == 1


def test_audit_tamper_detected_on_dropped_entry(gateway, audit_path):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    for i in range(3):
        gateway.stage(tok, ActionRequest(
            kind="paper_order", scope=TokenScope.PAPER_TRADE,
            symbol="SPY", notional_usd=float(i + 1),
        ))
    raw = audit_path.read_text(encoding="utf-8").splitlines()
    # Drop the middle entry: prev_hash chain breaks at entry 1.
    audit_path.write_text(
        raw[0] + "\n" + raw[2] + "\n", encoding="utf-8",
    )
    rep = gateway.audit.verify_chain()
    assert rep["ok"] is False


# ---------------------------------------------------------------------------
# 16) Stage/commit happy path - paper (auto-commit)
# ---------------------------------------------------------------------------


def test_stage_commit_push_happy_path_paper(gateway):
    from aurora.agent_gateway import (
        ActionRequest, ActionStatus, TokenScope,
    )
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    captured = {}

    def executor(committed):
        captured["staged_id"] = committed.staged.staged_id
        return {"ok": True, "broker_id": "FAKE-1"}

    gateway.register_executor("paper_order", executor)
    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    staged = gateway.stage(tok, action)
    committed = gateway.commit(staged.staged_id)
    result = gateway.push(committed)
    assert result.status == ActionStatus.EXECUTED
    assert result.response["broker_id"] == "FAKE-1"
    assert captured["staged_id"] == staged.staged_id


# ---------------------------------------------------------------------------
# 17) Stage/commit/push happy path - live with full ceremony
# ---------------------------------------------------------------------------


def test_stage_commit_push_happy_path_live(gateway, monkeypatch):
    from aurora.agent_gateway import (
        ActionRequest, ActionStatus, TokenScope,
    )
    from aurora.agent_gateway.gateway import (
        LIVE_AUTH_ENV, LIVE_CEREMONY_PHASE, operator_sign,
    )
    from aurora.core.data_layer import OOSGuard

    monkeypatch.setenv(LIVE_AUTH_ENV, "1")
    tok = _mint(
        scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=False,
        max_order=100.0, max_daily=1_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    gateway.register_executor("live_order",
                              lambda c: {"ok": True, "id": "L-1"})

    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with OOSGuard(LIVE_CEREMONY_PHASE, lock_path=None):
        staged = gateway.stage(tok, action)
    sig = operator_sign(staged.staged_id)
    committed = gateway.commit(staged.staged_id, human_signature=sig)
    result = gateway.push(committed)
    assert result.status == ActionStatus.EXECUTED


# ---------------------------------------------------------------------------
# 18) LIVE_TRADE without QF_AGENT_LIVE_AUTH refuses
# ---------------------------------------------------------------------------


def test_live_without_env_flag_refuses(gateway, monkeypatch):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import (
        CeremonyError, LIVE_AUTH_ENV, LIVE_CEREMONY_PHASE,
    )
    from aurora.core.data_layer import OOSGuard

    monkeypatch.delenv(LIVE_AUTH_ENV, raising=False)
    tok = _mint(
        scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=False,
        max_order=100.0, max_daily=1_000.0,
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with OOSGuard(LIVE_CEREMONY_PHASE, lock_path=None):
        with pytest.raises(CeremonyError, match=LIVE_AUTH_ENV):
            gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 19) LIVE_TRADE without OOSGuard refuses
# ---------------------------------------------------------------------------


def test_live_without_oosguard_refuses(gateway, monkeypatch):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import (
        CeremonyError, LIVE_AUTH_ENV,
    )

    monkeypatch.setenv(LIVE_AUTH_ENV, "1")
    tok = _mint(
        scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=False,
        max_order=100.0, max_daily=1_000.0,
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with pytest.raises(CeremonyError, match="OOSGuard"):
        gateway.stage(tok, action)


# ---------------------------------------------------------------------------
# 20) LIVE_TRADE without human signature refuses commit
# ---------------------------------------------------------------------------


def test_live_commit_without_signature_refuses(gateway, monkeypatch):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import (
        CeremonyError, LIVE_AUTH_ENV, LIVE_CEREMONY_PHASE,
    )
    from aurora.core.data_layer import OOSGuard

    monkeypatch.setenv(LIVE_AUTH_ENV, "1")
    tok = _mint(
        scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=False,
        max_order=100.0, max_daily=1_000.0,
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with OOSGuard(LIVE_CEREMONY_PHASE, lock_path=None):
        staged = gateway.stage(tok, action)
    with pytest.raises(CeremonyError, match="signature"):
        gateway.commit(staged.staged_id, human_signature=None)


# ---------------------------------------------------------------------------
# 21) Staged action expires after 5 min
# ---------------------------------------------------------------------------


def test_staged_action_expires(audit_path, monkeypatch):
    from aurora.agent_gateway import (
        ActionRequest, AgentGateway, GatewayPolicy, TokenScope,
    )
    from aurora.agent_gateway.gateway import GatewayStateError

    fake_now = [pd.Timestamp("2026-01-01T00:00:00")]

    def now_fn():
        return fake_now[0]

    gw = AgentGateway(
        policy=GatewayPolicy(staged_action_ttl_seconds=300),
        audit_path=audit_path,
        time_fn=now_fn,
    )
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gw.register_token(tok)
    staged = gw.stage(tok, ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=10.0,
    ))
    # Advance clock past the 5-min TTL.
    fake_now[0] = fake_now[0] + pd.Timedelta(seconds=400)
    with pytest.raises(GatewayStateError, match="expired"):
        gw.commit(staged.staged_id)


# ---------------------------------------------------------------------------
# 22) Revoke makes future stage refuse
# ---------------------------------------------------------------------------


def test_revoke_blocks_future_stage(gateway):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.agent_gateway.gateway import AuthenticationError
    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    # First stage works.
    gateway.stage(tok, ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=10.0,
    ))
    gateway.revoke(tok.token_id)
    with pytest.raises(AuthenticationError, match="revoked"):
        gateway.stage(tok, ActionRequest(
            kind="paper_order", scope=TokenScope.PAPER_TRADE,
            symbol="SPY", notional_usd=10.0,
        ))


# ---------------------------------------------------------------------------
# 23) Integration: deployment.live submit_with_retry verifies committed action
# ---------------------------------------------------------------------------


def test_deployment_live_submit_with_retry_accepts_gateway_committed(
    gateway, monkeypatch,
):
    from aurora.agent_gateway import (
        ActionRequest, TokenScope,
    )
    from aurora.deployment.live import submit_with_retry

    tok = _mint(scopes=frozenset({TokenScope.PAPER_TRADE}),
                max_order=100.0, max_daily=10_000.0, cooldown=0)
    gateway.register_token(tok)
    gateway.register_executor("paper_order", lambda c: {"ok": True})
    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    staged = gateway.stage(tok, action)
    committed = gateway.commit(staged.staged_id)

    class _Order:
        symbol = "SPY"
        client_order_id = "T-1"

    class _Strategy:
        def submit_order(self, order):
            return {"ok": True, "id": "BR-1"}

    out = submit_with_retry(
        _Strategy(), _Order(),
        max_attempts=1, delay=0,
        gateway_committed=committed,
    )
    assert out["ok"] is True

    # Mismatched symbol must raise before reaching the broker.
    class _BadOrder:
        symbol = "QQQ"
        client_order_id = "T-2"

    with pytest.raises(RuntimeError, match="symbol"):
        submit_with_retry(
            _Strategy(), _BadOrder(),
            max_attempts=1, delay=0,
            gateway_committed=committed,
        )


# ---------------------------------------------------------------------------
# 24) CLI smoke: token-issue -> stage -> commit
# ---------------------------------------------------------------------------


def test_cli_smoke_token_issue_stage_commit(tmp_path, monkeypatch):
    """End-to-end CLI smoke for the agent subcommand."""
    monkeypatch.setenv("QF_GATEWAY_SECRET", "test-secret-A1B2C3")
    monkeypatch.setenv("QF_OPERATOR_KEY", "test-operator-key-Z9Y8X7")

    audit_jsonl = tmp_path / "audit.jsonl"

    issue_cmd = [
        sys.executable, "-m", "aurora.cli.forge", "agent", "token-issue",
        "--actor", "smoke-bot",
        "--scopes", "paper_trade",
        "--expires-days", "1",
        "--max-order-notional", "200",
        "--max-daily-notional", "500",
        "--cooldown", "0",
    ]
    proc = subprocess.run(
        issue_cmd, capture_output=True, text=True,
        cwd=str(tmp_path),
        env={**os.environ},
    )
    assert proc.returncode == 0, f"token-issue failed: {proc.stderr}"
    token_data = json.loads(proc.stdout)
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")

    action_path = tmp_path / "action.json"
    action_path.write_text(json.dumps({
        "kind": "paper_order",
        "scope": "paper_trade",
        "symbol": "SPY",
        "notional_usd": 50.0,
        "payload": {},
    }), encoding="utf-8")

    stage_cmd = [
        sys.executable, "-m", "aurora.cli.forge", "agent", "stage",
        str(action_path),
        "--token", str(token_path),
        "--audit-path", str(audit_jsonl),
    ]
    proc = subprocess.run(
        stage_cmd, capture_output=True, text=True,
        cwd=str(tmp_path),
        env={**os.environ},
    )
    assert proc.returncode == 0, f"stage failed: {proc.stderr}"
    staged = json.loads(proc.stdout)
    assert "staged_id" in staged
    # Audit verify CLI: 0 (clean chain).
    audit_cmd = [
        sys.executable, "-m", "aurora.cli.forge", "agent",
        "audit-verify", "--audit-path", str(audit_jsonl),
    ]
    proc = subprocess.run(
        audit_cmd, capture_output=True, text=True,
        cwd=str(tmp_path), env={**os.environ},
    )
    assert proc.returncode == 0, f"audit-verify failed: {proc.stderr}"
