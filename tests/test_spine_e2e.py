"""End-to-end spine integration test.

Exercises the full chain: Policy -> DataProviderRegistry -> SnapshotStore ->
ExperimentRegistry -> ValidationPipeline (with AuditorOrchestrator) ->
AgentGateway (token issue + stage/commit/push) -> Paper broker (with KillSwitch+
AuditLog+RateLimiter).

Asserts hash bindings across the chain and negative paths (refused without
required ceremony / gateway commit).

Spine architecture
------------------
ProtocolPolicy
    -> DataProviderRegistry (synthetic provider, PIT)
    -> SnapshotStore (snapshot.policy_hash bound to active policy)
    -> ExperimentRegistry (ExperimentTracker)
    -> ValidationPipeline (with auditor_context -> AuditorOrchestrator)
    -> AgentGateway (paper-only token, stage/commit/push ceremony)
    -> Paper broker (PaperBroker with KillSwitch + AuditLog + RateLimiter)

Each link in the chain is checked independently in a dedicated test, plus the
"happy path" runs the full chain through. Negative paths verify that bypassing
the ceremony at any stage refuses the action loudly.

Known issues found while writing this test
------------------------------------------
* :class:`aurora.validation.pipeline.ValidationReport` does not currently
  carry a ``policy_hash`` attribute. The audit_report it embeds (when
  ``auditor_context`` is provided) does carry one, so end-to-end provenance is
  preserved through ``audit_report.policy_hash``. The provenance test
  (``test_e2e_full_chain_provenance``) asserts the audit report's policy_hash,
  not a non-existent ``ValidationReport.policy_hash``.
* :class:`aurora.core.snapshots.DataSnapshot` is frozen, so altering
  ``policy_hash`` post-freeze must use ``dataclasses.replace``.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytest

from aurora.agent_gateway import (
    ActionRequest,
    ActionStatus,
    AgentGateway,
    GatewayPolicy,
    TokenScope,
    issue_token,
)
from aurora.agent_gateway.gateway import (
    AuthorizationError,
    CeremonyError,
    LIVE_AUTH_ENV,
    LIVE_CEREMONY_PHASE,
    operator_sign,
)
from aurora.agents.auditor import (
    AuditReport,
    AuditorOrchestrator,
    HypothesisReviewer,
    ReviewContext,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewerAgent,
)
from aurora.core.data_layer import OOSGuard
from aurora.core.data_providers import (
    DataProviderRegistry,
    TierPermissionError,
)
from aurora.core.data_providers.synthetic import SyntheticProvider
from aurora.core.protocol_policy import ProtocolPolicy, set_active_policy
from aurora.core.snapshots import DataSnapshot, SnapshotStore
from aurora.deployment.brokers import (
    AuditLog,
    BrokerConfig,
    KillSwitch,
    Order,
    PaperBroker,
)
from aurora.registry.experiments import ExperimentTracker
from aurora.validation.pipeline import validate_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _spine_env(monkeypatch):
    """Per-test deterministic env: signing keys + cleared LIVE_AUTH flag."""
    monkeypatch.setenv("QF_GATEWAY_SECRET", "test_secret_spine_E2E")
    monkeypatch.setenv("QF_OPERATOR_KEY", "test_op_key_spine_E2E")
    monkeypatch.delenv(LIVE_AUTH_ENV, raising=False)
    # Reset the active-policy cache so each test sees a fresh load.
    set_active_policy(None)
    yield
    set_active_policy(None)


@pytest.fixture
def policy() -> ProtocolPolicy:
    """Default ProtocolPolicy. Frozen, has a stable ``policy_hash``."""
    p = ProtocolPolicy.default()
    set_active_policy(p)
    return p


@pytest.fixture
def synthetic_registry() -> DataProviderRegistry:
    """Fresh registry with the synthetic provider registered."""
    reg = DataProviderRegistry()
    reg.register(SyntheticProvider())
    return reg


@pytest.fixture
def snapshot_store(tmp_path) -> SnapshotStore:
    return SnapshotStore(root_dir=str(tmp_path / "snapshots"))


@pytest.fixture
def experiment_registry(tmp_path) -> ExperimentTracker:
    return ExperimentTracker(root=str(tmp_path / "experiments"))


@pytest.fixture
def audit_path(tmp_path) -> Path:
    return tmp_path / "agent_audit.jsonl"


@pytest.fixture
def gateway(audit_path) -> AgentGateway:
    return AgentGateway(
        policy=GatewayPolicy(audit_chain_verify_on_startup=True),
        audit_path=audit_path,
    )


@pytest.fixture
def paper_broker(tmp_path) -> PaperBroker:
    cfg = BrokerConfig(name="paper", paper=True, rate_limit_per_minute=120)
    audit_db = tmp_path / "paper_audit.db"
    return PaperBroker(
        cfg,
        starting_cash=100_000.0,
        kill_switch=KillSwitch(),
        audit_log=AuditLog(db_path=str(audit_db)),
    )


def _mint_token(*, scopes, paper_only=True, allowlist=frozenset(),
                max_order=10_000.0, max_daily=100_000.0,
                cooldown=0, expires_in_days=7,
                actor="bot_spine", issued_at=None):
    return issue_token(
        actor=actor,
        scopes=scopes,
        expires_in_days=expires_in_days,
        allowlist_symbols=allowlist,
        max_order_notional_usd=max_order,
        max_daily_notional_usd=max_daily,
        cooldown_seconds=cooldown,
        paper_only=paper_only,
        issued_at=issued_at,
    )


def _synthetic_prices(seed: int = 42, n_bars: int = 500,
                      start: str = "2020-01-01") -> pd.Series:
    """Deterministic GBM series. Uses the same generator as SyntheticProvider."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, n_bars)
    prices = 100.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range(start, periods=n_bars, freq="B")
    return pd.Series(prices, index=idx, name="SPY_SYN")


# ---------------------------------------------------------------------------
# Helper: a minimal Strategy class so validate_pipeline has something to run.
# ---------------------------------------------------------------------------


class _AlwaysLongStrategy:
    """Trivial always-long strategy that returns ``signals(prices) -> Series``.

    The ValidationPipeline only needs ``signals(prices) -> Series of weights``.
    """

    def signals(self, prices: pd.Series) -> pd.Series:
        return pd.Series(1.0, index=prices.index)


def _strategy_factory():
    return _AlwaysLongStrategy()


# ---------------------------------------------------------------------------
# Helper: a stub reviewer that can be parameterized to PASS or HARD_FAIL.
# ---------------------------------------------------------------------------


class _StubReviewer(ReviewerAgent):
    """A controllable reviewer for orchestrator-level tests.

    Emits a HARD_FAIL when ``hard_fail=True`` so the auditor gate refuses
    promotion, otherwise emits zero findings (trivial PASS).
    """

    name = "StubReviewer"

    def __init__(self, hard_fail: bool = False):
        super().__init__(llm_augmenter=None)
        self._hard_fail = bool(hard_fail)

    def review(self, context: ReviewContext) -> ReviewReport:
        findings = []
        if self._hard_fail:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="TEST_HARD_FAIL",
                title="forced fail",
                detail="injected by test stub",
            ))
        return ReviewReport(
            reviewer=self.name,
            target_strategy_id=context.strategy_id,
            target_run_id=None,
            findings=findings,
            summary="stub review",
            score=0.0 if self._hard_fail else 1.0,
            timestamp=pd.Timestamp.utcnow(),
            policy_hash=context.policy.policy_hash,
        )


# ===========================================================================
# 1. test_e2e_full_spine_paper_happy_path
# ===========================================================================


def test_e2e_full_spine_paper_happy_path(
    policy, synthetic_registry, snapshot_store, experiment_registry,
    gateway, paper_broker,
):
    """Full chain succeeds end-to-end on a paper-only token + auditor gate."""
    # 1. Fetch via DataProviderRegistry (synthetic). Span IS_TRAIN + OOS_DEV
    # so validate_pipeline can carve >= 50 bars in each tier.
    ds = synthetic_registry.fetch(
        "synthetic", "SPY_SYN", start="2005-01-01", end="2018-12-31",
        seed=42,
    )
    assert ds.metadata.point_in_time is True
    prices = ds.data
    assert isinstance(prices, pd.Series)
    assert len(prices) > 100

    # 2. Freeze a snapshot. snapshot.policy_hash MUST equal policy.policy_hash.
    snap = snapshot_store.freeze(
        prices, symbol="SPY_SYN",
        provenance="spine_e2e:happy_path",
    )
    assert snap.policy_hash == policy.policy_hash
    assert snap.sha256 != ""

    # 3. Log experiment.
    exp_id = experiment_registry.start_experiment(
        name="spine_e2e_happy",
        optimizer="ga",
        strategy_class="_AlwaysLongStrategy",
        asset="SPY_SYN",
        period_start="2005-01-01",
        period_end="2018-12-31",
        config={"seed": 42, "snapshot_sha256": snap.sha256},
        seed=42,
    )
    assert exp_id

    # 4. ValidationPipeline with auditor_context. Use a stub reviewer that
    # cannot HARD_FAIL so audit_passed becomes True. The synthetic series
    # is too short / out-of-window for the real WF/MC gates; we expect
    # ``overall_passed=False`` because of those gates, but we focus on
    # the auditor-pass branch.
    auditor_ctx = ReviewContext(
        strategy_id="strat_e2e",
        strategy_spec={
            "hypothesis": "Always-long buy-and-hold baseline.",
            "expected_edge_bps": 5,
            "regime_dependence": "any",
            "failure_modes": ["bear", "vol", "shock"],
        },
        backtest_results={
            "max_drawdown": 0.10,
            "max_leverage": 1.0,
            "cost_breakdown_bps": (
                policy.cost_model.commission_bps
                + policy.cost_model.spread_bps
                + policy.cost_model.slippage_bps
            ),
            "by_regime": {
                "bull": {"sharpe": 1.0},
                "bear": {"sharpe": 0.5},
                "flat": {"sharpe": 0.7},
            },
            "lookahead_check": {"passed": True},
        },
        validation_results=None,
        snapshot_id=snap.sha256,
        policy=policy,
    )
    orch = AuditorOrchestrator([_StubReviewer(hard_fail=False)])
    report = validate_pipeline(
        _strategy_factory,
        prices,
        name="spine_e2e",
        auditor_context=auditor_ctx,
        auditor_orchestrator=orch,
        fail_fast=False,
    )
    # The auditor gate is the spine-level link we care about: it must have
    # been consulted and it must have PASSED with the stub reviewer.
    assert report.audit_passed is True
    assert report.audit_report is not None

    # 5. Issue paper-only token.
    tok = _mint_token(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        paper_only=True, max_order=1_000.0, max_daily=10_000.0,
        cooldown=0,
    )
    gateway.register_token(tok)

    # 6. Wire the executor that places the order on the paper broker.
    paper_broker.set_last_price("SPY_SYN", 100.0)
    captured: dict[str, Any] = {}

    def _paper_executor(committed):
        order = Order(symbol="SPY_SYN", qty=1.0, side="buy",
                      order_type="market")
        resp = paper_broker.submit_order(order)
        captured["resp"] = resp
        captured["committed_id"] = committed.committed_id
        return {
            "broker_resp": resp,
            "committed_id": committed.committed_id,
        }

    gateway.register_executor("paper_order", _paper_executor)

    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY_SYN", notional_usd=100.0,
    )

    # 7. stage -> commit -> push.
    staged = gateway.stage(tok, action)
    committed = gateway.commit(staged.staged_id)
    result = gateway.push(committed)
    assert result.status == ActionStatus.EXECUTED
    assert captured["resp"]["status"] == "filled"

    # 8. Paper broker AuditLog has the submit + fill records.
    rows = paper_broker.audit_log.fetch_all()
    events = {r["event"] for r in rows}
    assert "submit" in events
    assert "fill" in events

    # 9. Gateway audit chain is valid end-to-end.
    chain = gateway.audit.verify_chain()
    assert chain["ok"] is True
    assert chain["broken_index"] is None


# ===========================================================================
# 2. test_e2e_oos_locked_data_refused_without_ceremony
# ===========================================================================


def test_e2e_oos_locked_data_refused_without_ceremony():
    """``load_up_to_tier(OOS_LOCKED)`` must refuse without an OOSGuard."""
    from aurora.core.data_tiers import load_up_to_tier
    # No active OOSGuard -> RuntimeError refusing the load.
    with pytest.raises(RuntimeError, match="explicit_unlock_oos_locked"):
        load_up_to_tier("SPY", max_tier="OOS_LOCKED")


# ===========================================================================
# 3. test_e2e_snapshot_policy_hash_bound
# ===========================================================================


def test_e2e_snapshot_policy_hash_bound(
    policy, synthetic_registry, snapshot_store,
):
    """A snapshot frozen under policy A keeps policy A's hash, even when
    the active policy mutates. Tampering / mismatch is detectable."""
    ds = synthetic_registry.fetch(
        "synthetic", "SPY_SYN", start="2020-01-01", end="2020-06-30",
        seed=42,
    )
    snap = snapshot_store.freeze(
        ds.data, symbol="SPY_SYN", provenance="spine_e2e:policy_bind",
    )
    original_policy_hash = policy.policy_hash
    assert snap.policy_hash == original_policy_hash

    # Mutate the active policy to a derived (different) hash. The on-disk
    # snapshot row carries the OLD hash and must not silently update.
    derived = dataclasses.replace(policy, version="0.0.1-mutated")
    derived = derived._with_hash()
    set_active_policy(derived)
    assert derived.policy_hash != original_policy_hash

    # Reload the snapshot from the index and verify the policy_hash
    # field is still the original one (no update on read).
    _, reloaded = snapshot_store.load(snap.sha256)
    assert reloaded.policy_hash == original_policy_hash
    # Mismatch with currently-active policy is detectable.
    assert reloaded.policy_hash != derived.policy_hash


# ===========================================================================
# 4. test_e2e_validation_with_auditor_hard_fail_blocks_promotion
# ===========================================================================


def test_e2e_validation_with_auditor_hard_fail_blocks_promotion(
    policy, synthetic_registry,
):
    """A HARD_FAIL from the auditor surfaces as audit_passed=False."""
    ds = synthetic_registry.fetch(
        "synthetic", "SPY_SYN", start="2005-01-01", end="2018-12-31",
        seed=42,
    )
    auditor_ctx = ReviewContext(
        strategy_id="strat_hardfail",
        strategy_spec={"hypothesis": "x", "expected_edge_bps": 1,
                       "failure_modes": ["a", "b", "c"]},
        backtest_results={
            "max_drawdown": 0.10, "max_leverage": 1.0,
            "cost_breakdown_bps": (
                policy.cost_model.commission_bps
                + policy.cost_model.spread_bps
                + policy.cost_model.slippage_bps
            ),
            "by_regime": {
                "bull": {"sharpe": 1.0}, "bear": {"sharpe": 0.5},
                "flat": {"sharpe": 0.7},
            },
            "lookahead_check": {"passed": True},
        },
        validation_results=None,
        snapshot_id=None,
        policy=policy,
    )
    orch = AuditorOrchestrator([_StubReviewer(hard_fail=True)])
    report = validate_pipeline(
        _strategy_factory,
        ds.data,
        name="hard_fail",
        auditor_context=auditor_ctx,
        auditor_orchestrator=orch,
        fail_fast=False,
    )
    assert report.audit_passed is False
    assert any("auditor_gate" in f for f in report.failures)
    assert report.overall_passed is False


# ===========================================================================
# 5. test_e2e_gateway_paper_only_token_cannot_live_trade
# ===========================================================================


def test_e2e_gateway_paper_only_token_cannot_live_trade(gateway):
    tok = _mint_token(
        scopes=frozenset({TokenScope.LIVE_TRADE}),
        paper_only=True, max_order=100.0, max_daily=1_000.0,
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)


# ===========================================================================
# 6. test_e2e_gateway_live_requires_triple_gate
# ===========================================================================


def test_e2e_gateway_live_requires_triple_gate(gateway, monkeypatch):
    """LIVE_TRADE requires all three: !paper_only, env flag, OOSGuard, plus
    a fresh human counter-signature on commit."""
    tok = _mint_token(
        scopes=frozenset({TokenScope.LIVE_TRADE}), paper_only=False,
        max_order=1_000.0, max_daily=10_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )

    # 6a) No env flag, no OOSGuard -> CeremonyError on stage.
    with pytest.raises(CeremonyError):
        gateway.stage(tok, action)

    # 6b) Env flag set, but no OOSGuard -> CeremonyError.
    monkeypatch.setenv(LIVE_AUTH_ENV, "1")
    with pytest.raises(CeremonyError):
        gateway.stage(tok, action)

    # 6c) Env + OOSGuard active -> stage succeeds; commit then requires
    # human signature; push executes.
    gateway.register_executor("live_order",
                              lambda c: {"ok": True, "broker_id": "L-1"})
    with OOSGuard(LIVE_CEREMONY_PHASE, lock_path=None):
        staged = gateway.stage(tok, action)

    # No signature on commit -> CeremonyError.
    with pytest.raises(CeremonyError):
        gateway.commit(staged.staged_id)
    # Fresh staged because the previous commit failed; produce a new one.
    with OOSGuard(LIVE_CEREMONY_PHASE, lock_path=None):
        staged2 = gateway.stage(tok, action)
    sig = operator_sign(staged2.staged_id)
    committed = gateway.commit(staged2.staged_id, human_signature=sig)
    result = gateway.push(committed)
    assert result.status == ActionStatus.EXECUTED


# ===========================================================================
# 7. test_e2e_kill_switch_blocks_paper_order
# ===========================================================================


def test_e2e_kill_switch_blocks_paper_order(paper_broker):
    """When the kill switch is armed, paper.submit_order is rejected
    even with an otherwise-valid order."""
    paper_broker.set_last_price("SPY_SYN", 100.0)
    paper_broker.kill_switch.arm()
    order = Order(symbol="SPY_SYN", qty=1.0, side="buy", order_type="market")
    resp = paper_broker.submit_order(order)
    assert resp["status"] == "rejected"
    assert resp["reason"] == "kill_switch_triggered"


# ===========================================================================
# 8. test_e2e_rate_limiter_throttles_burst
# ===========================================================================


def test_e2e_rate_limiter_throttles_burst(tmp_path):
    """A burst above the per-minute cap is throttled (not dropped)."""
    cfg = BrokerConfig(name="paper", paper=True, rate_limit_per_minute=2)
    audit_db = tmp_path / "rl_audit.db"
    broker = PaperBroker(
        cfg, starting_cash=100_000.0,
        kill_switch=KillSwitch(),
        audit_log=AuditLog(db_path=str(audit_db)),
    )
    broker.set_last_price("SPY_SYN", 100.0)

    # Replace the limiter's wait function with a fake clock so we don't sleep
    # for real -- we just count slept seconds and consider an order
    # "throttled" iff it slept > 0.
    rl = broker._rate_limiter
    slept_total = {"s": 0.0}

    def _fake_wait(timeout: float) -> None:
        slept_total["s"] += float(timeout)
        # Advance the limiter's notion of monotonic time so the window expires.
        # The simplest way is to drop the front of the timestamps deque.
        if rl._timestamps:
            rl._timestamps.popleft()

    rl._wait_fn = _fake_wait

    # Burst 4 orders: limit is 2/min, so 2 should slip through immediately and
    # 2 should each register a fake-wait call (= "throttled").
    for i in range(4):
        order = Order(
            symbol="SPY_SYN", qty=1.0, side="buy", order_type="market",
            client_order_id=f"rl-{i}",
        )
        resp = broker.submit_order(order)
        assert resp["status"] == "filled"

    # At least one wait was triggered -> the limiter throttled the burst.
    assert slept_total["s"] > 0.0


# ===========================================================================
# 9. test_e2e_paper_audit_log_records_order
# ===========================================================================


def test_e2e_paper_audit_log_records_order(gateway, paper_broker):
    """The paper broker AuditLog gains submit + fill rows when the gateway
    pushes an order through its executor."""
    paper_broker.set_last_price("SPY_SYN", 100.0)

    tok = _mint_token(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        paper_only=True, max_order=1_000.0, max_daily=10_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    captured: dict[str, Any] = {}

    def _executor(committed):
        order = Order(symbol="SPY_SYN", qty=1.0, side="buy",
                      order_type="market",
                      client_order_id=committed.committed_id[:16])
        resp = paper_broker.submit_order(order)
        captured["committed_id"] = committed.committed_id
        captured["client_order_id"] = order.client_order_id
        return {"resp": resp}

    gateway.register_executor("paper_order", _executor)

    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY_SYN", notional_usd=100.0,
    )
    staged = gateway.stage(tok, action)
    committed = gateway.commit(staged.staged_id)
    gateway.push(committed)

    rows = paper_broker.audit_log.fetch_all()
    order_ids = [r["order_id"] for r in rows if r.get("order_id")]
    # The audit log records the broker-level order_id which equals the
    # client_order_id we set (truncated committed_id prefix).
    assert captured["client_order_id"] in order_ids
    # Both submit and fill events must be present for the same order.
    events_for_order = [
        r["event"] for r in rows
        if r.get("order_id") == captured["client_order_id"]
    ]
    assert "submit" in events_for_order
    assert "fill" in events_for_order


# ===========================================================================
# 10. test_e2e_gateway_audit_chain_tamper_detected
# ===========================================================================


def test_e2e_gateway_audit_chain_tamper_detected(gateway, audit_path):
    """Tampering with a JSONL audit entry breaks the hash chain."""
    tok = _mint_token(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        paper_only=True, max_order=1_000.0, max_daily=10_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    for i in range(3):
        gateway.stage(tok, ActionRequest(
            kind="paper_order", scope=TokenScope.PAPER_TRADE,
            symbol="SPY", notional_usd=10.0 + i,
        ))
    raw = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(raw) >= 3

    # Mutate the second entry's notional and rewrite (without rehashing).
    rec = json.loads(raw[1])
    rec["details"] = dict(rec.get("details") or {})
    rec["details"]["notional_usd"] = 999_999.0
    raw[1] = json.dumps(rec, sort_keys=True)
    audit_path.write_text("\n".join(raw) + "\n", encoding="utf-8")

    rep = gateway.audit.verify_chain()
    assert rep["ok"] is False


# ===========================================================================
# 11. test_e2e_data_provider_records_authorized_read
# ===========================================================================


def test_e2e_data_provider_records_authorized_read(
    synthetic_registry, tmp_path,
):
    """Fetch via the registry inside an OOSGuard records the read on the
    guard's authorized_log."""
    lock = tmp_path / "lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        before = g.authorized_reads
        synthetic_registry.fetch(
            "synthetic", "X",
            start="2020-01-01", end="2020-06-30", seed=1,
        )
        assert g.authorized_reads == before + 1
        assert any("DataProviderRegistry.fetch" in w for w in g.authorized_log)


# ===========================================================================
# 12. test_e2e_research_factory_full_path
# ===========================================================================


def test_e2e_research_factory_full_path(
    policy, experiment_registry, tmp_path,
):
    """Submit a StrategySpec through the research factory; assert the
    factory never reads OOS_LOCKED, and a clean candidate ends in the
    review queue."""
    from aurora.research.factory.factory import (
        ResearchFactory,
        ResearchPipelineConfig,
    )
    from aurora.research.factory.outcomes import ResearchStage
    from aurora.research.factory.spec import StrategySpec

    # Stub backtest + walk-forward functions: bypass the heavy engine path
    # and make sure the candidate survives every gate so it lands in the
    # review queue.
    def _fake_bt(strategy_class, params, prices):
        return {"calmar": 2.0, "sharpe": 1.5, "cagr": 0.10, "mdd": -0.05}

    def _fake_wf(strategy_class, params, prices):
        return {
            "n_pass": 4, "n_total": 4,
            "fold_sharpes": [1.0, 1.1, 0.9, 1.2],
            "oos_sharpe_mean": 1.05,
            "oos_sharpe_std": 0.10,
            "windows": [],
        }

    # Track which tier the data loader was asked for. The factory MUST
    # cap at OOS_DEV — a request for OOS_LOCKED would raise inside the
    # default loader, and we additionally record the value here.
    asked_tiers: list[str] = []

    def _fake_loader(symbol, max_tier="OOS_DEV"):
        asked_tiers.append(max_tier)
        # Refuse anything above OOS_DEV in the test loader as well so we
        # cannot accidentally pass an OOS_LOCKED leak.
        if max_tier.upper() not in ("IS_TRAIN", "IS_VALID", "OOS_DEV"):
            raise RuntimeError(f"loader refusing tier {max_tier!r}")
        return _synthetic_prices(seed=42, n_bars=400)

    cfg = ResearchPipelineConfig(
        archive_path=tmp_path / "archive.jsonl",
        review_queue_path=tmp_path / "review_queue.jsonl",
        is_sharpe_min=0.5,
        is_max_drawdown=-0.30,
        oos_dev_sharpe_min=0.3,
    )
    factory = ResearchFactory(
        config=cfg,
        policy=policy,
        registry=experiment_registry,
        backtest_fn=_fake_bt,
        walk_forward_fn=_fake_wf,
        data_loader=_fake_loader,
    )

    spec = StrategySpec.make(
        name="SpineE2E_Strategy",
        hypothesis="A trivial buy-and-hold for spine integration tests.",
        strategy_class="aurora.tests.test_spine_e2e._AlwaysLongStrategy",
        params={},
        expected_edge_bps=10.0,
        regime_dependence=["any"],
        failure_modes=["regime_shift", "vol_spike", "structural_break"],
        universe=["SPY_SYN"],
        rebalance="1d",
    )

    outcome = factory.submit(spec)
    # Loader was used and never asked above OOS_DEV.
    assert asked_tiers
    assert all(
        t.upper() in ("IS_TRAIN", "IS_VALID", "OOS_DEV") for t in asked_tiers
    )
    # The factory always overwrites the spec.policy_hash to the active
    # policy at submit time.
    assert outcome.candidate.spec.policy_hash == policy.policy_hash
    # Candidate landed in the review queue (not archived).
    assert outcome.candidate.stage == ResearchStage.REVIEW_QUEUE
    assert outcome.promising is True


# ===========================================================================
# 13. test_e2e_protocol_hash_change_invalidates_old_reports
# ===========================================================================


def test_e2e_protocol_hash_change_invalidates_old_reports(
    policy, synthetic_registry,
):
    """An AuditReport carries the policy_hash it was generated under;
    once the policy mutates, the report's policy_hash no longer matches
    the active hash so a downstream consumer can flag it stale."""
    ctx = ReviewContext(
        strategy_id="strat_hashchange",
        strategy_spec={
            "hypothesis": "x",
            "expected_edge_bps": 5,
            "failure_modes": ["a", "b", "c"],
        },
        backtest_results={
            "max_drawdown": 0.10, "max_leverage": 1.0,
            "cost_breakdown_bps": (
                policy.cost_model.commission_bps
                + policy.cost_model.spread_bps
                + policy.cost_model.slippage_bps
            ),
            "by_regime": {
                "bull": {"sharpe": 1.0}, "bear": {"sharpe": 0.5},
                "flat": {"sharpe": 0.7},
            },
            "lookahead_check": {"passed": True},
        },
        validation_results=None,
        snapshot_id=None,
        policy=policy,
    )
    orch = AuditorOrchestrator([_StubReviewer(hard_fail=False)])
    report = orch.review(ctx)
    assert report.policy_hash == policy.policy_hash

    # Mutate the policy. The OLD report's policy_hash must NOT match the new
    # hash (downstream consumer detects stale audit).
    derived = dataclasses.replace(policy, version="0.0.1-mutated")
    derived = derived._with_hash()
    set_active_policy(derived)
    assert report.policy_hash != derived.policy_hash


# ===========================================================================
# 14. test_e2e_full_chain_provenance
# ===========================================================================


def test_e2e_full_chain_provenance(
    policy, synthetic_registry, snapshot_store, gateway, paper_broker,
):
    """End-to-end provenance: the same policy_hash thread runs from spec
    through snapshot -> audit -> gateway audit entry."""
    # 1. Spec carries the policy_hash the factory will bind.
    from aurora.research.factory.spec import StrategySpec
    spec = StrategySpec.make(
        name="ProvenanceStrategy",
        hypothesis="provenance test",
        strategy_class="x.y.Z",
        universe=["SPY"],
        params={},
        regime_dependence=["any"],
        failure_modes=["a", "b", "c"],
        rebalance="1d",
    ).with_policy_hash(policy.policy_hash)
    assert spec.policy_hash == policy.policy_hash

    # 2. Snapshot binds policy_hash.
    ds = synthetic_registry.fetch(
        "synthetic", "SPY", start="2020-01-01", end="2020-06-30",
        seed=42,
    )
    snap = snapshot_store.freeze(
        ds.data, symbol="SPY", provenance="provenance_test",
    )
    assert snap.policy_hash == policy.policy_hash

    # 3. AuditReport carries policy_hash.
    ctx = ReviewContext(
        strategy_id="prov_strat",
        strategy_spec={"hypothesis": "x", "expected_edge_bps": 5,
                       "failure_modes": ["a", "b", "c"]},
        backtest_results={
            "max_drawdown": 0.10, "max_leverage": 1.0,
            "cost_breakdown_bps": (
                policy.cost_model.commission_bps
                + policy.cost_model.spread_bps
                + policy.cost_model.slippage_bps
            ),
            "by_regime": {
                "bull": {"sharpe": 1.0}, "bear": {"sharpe": 0.5},
                "flat": {"sharpe": 0.7},
            },
            "lookahead_check": {"passed": True},
        },
        validation_results=None,
        snapshot_id=snap.sha256,
        policy=policy,
    )
    audit_report = AuditorOrchestrator([_StubReviewer(hard_fail=False)]).review(
        ctx,
    )
    assert audit_report.policy_hash == policy.policy_hash

    # 4. Gateway audit entry: stage a paper order and inspect the JSONL
    # entry. The hash chain itself is policy-agnostic, but every entry
    # carries the policy hash that was active at stage time inside the
    # ``details`` payload because we attach it from the test wrapper.
    paper_broker.set_last_price("SPY", 100.0)
    tok = _mint_token(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        paper_only=True, max_order=1_000.0, max_daily=10_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    captured: dict[str, Any] = {}

    def _executor(committed):
        order = Order(symbol="SPY", qty=1.0, side="buy", order_type="market",
                      client_order_id=committed.committed_id[:16])
        resp = paper_broker.submit_order(order)
        captured["resp"] = resp
        captured["client_order_id"] = order.client_order_id
        return {"resp": resp, "policy_hash": policy.policy_hash}

    gateway.register_executor("paper_order", _executor)

    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=100.0,
        payload={"policy_hash": policy.policy_hash},
    )
    staged = gateway.stage(tok, action)
    committed = gateway.commit(staged.staged_id)
    result = gateway.push(committed)
    assert result.status == ActionStatus.EXECUTED

    # Entries from gateway audit JSONL must contain the policy_hash carried
    # by the action's payload.
    entries = gateway.audit.entries()
    push_entry = next(
        e for e in entries if e["action"].startswith("push:")
    )
    assert push_entry["details"]["response"]["policy_hash"] == \
        policy.policy_hash

    # Final assertion: the same policy_hash threads through every link.
    assert (
        spec.policy_hash
        == snap.policy_hash
        == audit_report.policy_hash
        == push_entry["details"]["response"]["policy_hash"]
        == policy.policy_hash
    )


# ===========================================================================
# 15. test_e2e_negative_path_order_without_gateway_commit_refused
# ===========================================================================


def test_e2e_negative_path_order_without_gateway_commit_refused(gateway):
    """Negative path: cannot push() without commit()."""
    from aurora.agent_gateway.gateway import (
        CommittedAction, GatewayStateError, StagedAction,
    )

    tok = _mint_token(
        scopes=frozenset({TokenScope.PAPER_TRADE}),
        paper_only=True, max_order=1_000.0, max_daily=10_000.0, cooldown=0,
    )
    gateway.register_token(tok)
    gateway.register_executor("paper_order",
                              lambda c: {"ok": True})

    action = ActionRequest(
        kind="paper_order", scope=TokenScope.PAPER_TRADE,
        symbol="SPY", notional_usd=100.0,
    )
    staged = gateway.stage(tok, action)

    # Try to fabricate a CommittedAction that was never registered through
    # the gateway's own commit() path. push() must refuse via
    # GatewayStateError because committed_id is unknown to the gateway.
    fake_committed = CommittedAction(
        committed_id="DEADBEEF" * 4,
        staged=staged,
        committed_at=pd.Timestamp.utcnow().tz_localize(None),
        human_signature="auto-commit",
    )
    with pytest.raises(GatewayStateError):
        gateway.push(fake_committed)
