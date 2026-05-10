"""Tests for R175 solo-operator risk record + approval gates."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from aurora.governance.approvals import (
    LifecycleStage,
    PromotionBlocked,
    StrategyOverride,
    StrategyRiskRecord,
    StrategyRiskRegistry,
    add_override,
    assert_can_run,
    can_promote,
    promote,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    stage: LifecycleStage = LifecycleStage.DRAFTED,
    expires_at: date | None = None,
    policy_hash: str = "p1",
    snapshot_hash: str = "s1",
    strategy_hash: str = "x1",
) -> StrategyRiskRecord:
    return StrategyRiskRecord(
        strategy_id="alpha",
        intended_use="single-asset momentum",
        limitations="us equities only",
        assumptions="252 trading days",
        operator="op@local",
        risk_limits={"max_drawdown": 0.1, "max_leverage": 1.0},
        validation_id="v1",
        policy_hash=policy_hash,
        snapshot_hash=snapshot_hash,
        strategy_hash=strategy_hash,
        expires_at=expires_at,
        stage=stage,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_record_requires_strategy_id():
    with pytest.raises(ValueError):
        StrategyRiskRecord(
            strategy_id="",
            intended_use="x",
            limitations="x",
            assumptions="x",
            operator="op",
            risk_limits={},
            validation_id="v",
            policy_hash="p",
            snapshot_hash="s",
            strategy_hash="x",
        )


def test_record_requires_operator():
    with pytest.raises(ValueError):
        StrategyRiskRecord(
            strategy_id="a",
            intended_use="x",
            limitations="x",
            assumptions="x",
            operator="",
            risk_limits={},
            validation_id="v",
            policy_hash="p",
            snapshot_hash="s",
            strategy_hash="x",
        )


def test_is_expired_today():
    rec = _record(expires_at=date(2026, 1, 1))
    assert rec.is_expired(today=date(2026, 5, 10)) is True
    assert rec.is_expired(today=date(2025, 12, 31)) is False


def test_hashes_match_returns_true_for_matching_inputs():
    rec = _record()
    assert rec.hashes_match(
        policy_hash="p1", snapshot_hash="s1", strategy_hash="x1",
    ) is True
    assert rec.hashes_match(
        policy_hash="p1", snapshot_hash="other", strategy_hash="x1",
    ) is False


def test_content_hash_changes_when_intent_changes():
    a = _record()
    b = StrategyRiskRecord(
        strategy_id=a.strategy_id,
        intended_use="different intent",
        limitations=a.limitations,
        assumptions=a.assumptions,
        operator=a.operator,
        risk_limits=dict(a.risk_limits),
        validation_id=a.validation_id,
        policy_hash=a.policy_hash,
        snapshot_hash=a.snapshot_hash,
        strategy_hash=a.strategy_hash,
        stage=a.stage,
    )
    assert a.content_hash() != b.content_hash()


def test_to_dict_includes_content_hash():
    rec = _record()
    payload = rec.to_dict()
    assert "content_hash" in payload
    assert payload["stage"] == "drafted"


# ---------------------------------------------------------------------------
# Promotion logic
# ---------------------------------------------------------------------------


def test_can_promote_one_stage_forward():
    rec = _record(stage=LifecycleStage.DRAFTED)
    ok, reason = can_promote(rec, LifecycleStage.REVIEWED)
    assert ok is True
    assert reason


def test_cannot_skip_stages():
    rec = _record(stage=LifecycleStage.DRAFTED)
    ok, reason = can_promote(rec, LifecycleStage.PAPER)
    assert ok is False
    assert "skip" in reason


def test_promote_returns_new_record_with_target_stage():
    rec = _record(stage=LifecycleStage.DRAFTED)
    new = promote(rec, LifecycleStage.REVIEWED)
    assert new.stage is LifecycleStage.REVIEWED
    assert rec.stage is LifecycleStage.DRAFTED


def test_promote_blocked_when_skipping_stages():
    rec = _record(stage=LifecycleStage.DRAFTED)
    with pytest.raises(PromotionBlocked):
        promote(rec, LifecycleStage.LIVE)


def test_promote_blocked_when_record_expired():
    rec = _record(stage=LifecycleStage.SHADOW, expires_at=date(2026, 1, 1))
    with pytest.raises(PromotionBlocked):
        promote(rec, LifecycleStage.PAPER, today=date(2026, 5, 10))


def test_promote_allows_de_escalation():
    rec = _record(stage=LifecycleStage.PAPER)
    new = promote(rec, LifecycleStage.SHADOW)
    assert new.stage is LifecycleStage.SHADOW


def test_promote_blocks_de_escalation_when_disabled():
    rec = _record(stage=LifecycleStage.PAPER)
    with pytest.raises(PromotionBlocked):
        promote(rec, LifecycleStage.SHADOW, allow_backwards=False)


def test_promote_to_retired_always_allowed():
    rec = _record(stage=LifecycleStage.LIVE)
    new = promote(rec, LifecycleStage.RETIRED)
    assert new.stage is LifecycleStage.RETIRED


def test_retired_record_cannot_be_promoted():
    rec = _record(stage=LifecycleStage.RETIRED)
    with pytest.raises(PromotionBlocked):
        promote(rec, LifecycleStage.SHADOW)


# ---------------------------------------------------------------------------
# assert_can_run
# ---------------------------------------------------------------------------


def test_assert_can_run_succeeds_for_matching_stage_and_hashes():
    rec = _record(stage=LifecycleStage.PAPER)
    # Should not raise.
    assert_can_run(
        rec,
        expected_policy_hash="p1",
        expected_snapshot_hash="s1",
        expected_strategy_hash="x1",
        minimum_stage=LifecycleStage.SHADOW,
    )


def test_assert_can_run_blocks_when_stage_too_low():
    rec = _record(stage=LifecycleStage.SHADOW)
    with pytest.raises(PromotionBlocked):
        assert_can_run(
            rec,
            expected_policy_hash="p1",
            expected_snapshot_hash="s1",
            expected_strategy_hash="x1",
            minimum_stage=LifecycleStage.LIVE,
        )


def test_assert_can_run_blocks_on_hash_mismatch():
    rec = _record(stage=LifecycleStage.PAPER)
    with pytest.raises(PromotionBlocked) as exc:
        assert_can_run(
            rec,
            expected_policy_hash="OTHER",
            expected_snapshot_hash="s1",
            expected_strategy_hash="x1",
            minimum_stage=LifecycleStage.PAPER,
        )
    assert "hash mismatch" in str(exc.value)


def test_assert_can_run_blocks_when_expired():
    rec = _record(
        stage=LifecycleStage.PAPER, expires_at=date(2026, 1, 1),
    )
    with pytest.raises(PromotionBlocked) as exc:
        assert_can_run(
            rec,
            expected_policy_hash="p1",
            expected_snapshot_hash="s1",
            expected_strategy_hash="x1",
            minimum_stage=LifecycleStage.PAPER,
            today=date(2026, 5, 10),
        )
    assert "expired" in str(exc.value)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_add_override_appends_audit_entry():
    rec = _record(stage=LifecycleStage.SHADOW)
    new = add_override(
        rec,
        actor="op@local",
        reason="data-quality warning bypassed for shadow only",
        affected_field="risk_limits.max_drawdown",
        previous_value=0.1,
        new_value=0.2,
    )
    assert len(new.overrides) == 1
    assert new.overrides[0].actor == "op@local"
    assert new.overrides[0].new_value == 0.2


def test_add_override_requires_actor_and_reason():
    rec = _record()
    with pytest.raises(ValueError):
        add_override(
            rec, actor="", reason="r",
            affected_field="x", previous_value=0, new_value=1,
        )
    with pytest.raises(ValueError):
        add_override(
            rec, actor="op", reason="",
            affected_field="x", previous_value=0, new_value=1,
        )


# ---------------------------------------------------------------------------
# Persistent registry
# ---------------------------------------------------------------------------


def test_registry_round_trip(tmp_path: Path):
    reg = StrategyRiskRegistry(tmp_path / "risk.jsonl")
    rec = _record()
    reg.append(rec)
    fetched = reg.latest("alpha")
    assert fetched is not None
    assert fetched.strategy_id == "alpha"
    assert fetched.stage is LifecycleStage.DRAFTED


def test_registry_latest_picks_last_entry(tmp_path: Path):
    reg = StrategyRiskRegistry(tmp_path / "risk.jsonl")
    reg.append(_record())
    reg.append(_record(stage=LifecycleStage.SHADOW))
    latest = reg.latest("alpha")
    assert latest is not None
    assert latest.stage is LifecycleStage.SHADOW


def test_registry_all_strategies_unique_sorted(tmp_path: Path):
    reg = StrategyRiskRegistry(tmp_path / "risk.jsonl")
    reg.append(_record())
    reg.append(StrategyRiskRecord(
        strategy_id="zeta",
        intended_use="x", limitations="x", assumptions="x",
        operator="op", risk_limits={},
        validation_id="v", policy_hash="p", snapshot_hash="s",
        strategy_hash="x",
    ))
    assert reg.all_strategies() == ["alpha", "zeta"]


def test_registry_returns_none_when_strategy_absent(tmp_path: Path):
    reg = StrategyRiskRegistry(tmp_path / "risk.jsonl")
    assert reg.latest("missing") is None


def test_registry_round_trips_overrides(tmp_path: Path):
    reg = StrategyRiskRegistry(tmp_path / "risk.jsonl")
    rec = add_override(
        _record(),
        actor="op@local",
        reason="bypass for shadow",
        affected_field="risk_limits.max_leverage",
        previous_value=1.0,
        new_value=1.5,
    )
    reg.append(rec)
    fetched = reg.latest("alpha")
    assert fetched is not None
    assert len(fetched.overrides) == 1
    assert fetched.overrides[0].reason == "bypass for shadow"
