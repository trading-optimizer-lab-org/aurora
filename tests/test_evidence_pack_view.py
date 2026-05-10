"""R176 -- Tests for the role-restricted evidence pack view."""
from __future__ import annotations

from dataclasses import replace

import pytest

from aurora.agent_gateway.agent_roles import AgentRole, ROLE_REGISTRY
from aurora.agent_gateway.evidence_pack_view import (
    EvidenceAccessDenied,
    EvidenceHashMismatch,
    EvidencePackView,
)
from aurora.reporting.evidence_pack import (
    build_strategy_pack,
    compute_pack_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strategy_pack():
    return build_strategy_pack(
        strategy_id="alpha",
        policy_hash="p1",
        snapshot_hash="s1",
        validation_report={"sharpe": 1.2, "passes_gates": True},
        benchmark_pack={"primary_baseline": "buy_and_hold"},
        manifest={"strategy_version": "v1"},
        research_ledger_excerpt=[{"event": "validation_run"}],
        quality_decisions=[{"symbol": "SPY", "decision": "approved"}],
        provider_provenance=[{"provider": "yahoo"}],
        requested_symbols=["SPY"],
        persisted_symbols=["SPY"],
        warnings=["minor"],
    )


@pytest.fixture
def risk_view(strategy_pack):
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    return EvidencePackView(strategy_pack, cap.allowed_sections)


@pytest.fixture
def data_quality_view(strategy_pack):
    cap = ROLE_REGISTRY.get(AgentRole.DATA_QUALITY_REVIEWER)
    return EvidencePackView(strategy_pack, cap.allowed_sections)


# ---------------------------------------------------------------------------
# Allowed reads
# ---------------------------------------------------------------------------


def test_view_exposes_allowed_section(risk_view):
    """A risk reviewer should be able to read validation_report."""
    report = risk_view.get_section("validation_report")
    assert report["sharpe"] == 1.2


def test_view_carries_evidence_ids(risk_view, strategy_pack):
    """``evidence_ids`` is the citation envelope for downstream output."""
    ids = risk_view.evidence_ids()
    assert ids["pack_id"] == strategy_pack.pack_id
    assert ids["policy_hash"] == "p1"
    assert ids["snapshot_hash"] == "s1"
    assert ids["pack_hash"] == strategy_pack.pack_hash


# ---------------------------------------------------------------------------
# Denied reads
# ---------------------------------------------------------------------------


def test_view_refuses_section_not_in_allowlist(risk_view):
    """Risk reviewer is not permitted to read identity_status."""
    # identity_status is in the data-quality reviewer's allowlist, not
    # the risk reviewer's, so this read must raise.
    with pytest.raises(EvidenceAccessDenied):
        risk_view.get_section("identity_status")


def test_data_quality_view_can_read_identity_status(data_quality_view):
    """Same section is allowed for the data-quality role."""
    status = data_quality_view.get_section("identity_status")
    assert "resolved" in status


# ---------------------------------------------------------------------------
# Hash binding
# ---------------------------------------------------------------------------


def test_view_refuses_when_underlying_pack_hash_changes(strategy_pack):
    """If the pack content drifts, every read must raise."""
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    view = EvidencePackView(strategy_pack, cap.allowed_sections)
    # Mutate the underlying pack-as-dict by swapping its dict-typed
    # validation_report. ``EvidencePack`` is frozen, so we use object
    # __setattr__ to simulate tampering.
    object.__setattr__(view._pack, "validation_report", {"sharpe": 9.99})
    with pytest.raises(EvidenceHashMismatch):
        view.get_section("validation_report")


def test_view_refuses_pack_with_wrong_pack_hash(strategy_pack):
    """A view bound to a pack whose stored pack_hash is wrong fails closed."""
    bad_pack = replace(strategy_pack, pack_hash="0" * 64)
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    with pytest.raises(EvidenceHashMismatch):
        EvidencePackView(bad_pack, cap.allowed_sections)


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------


def test_view_blocks_attribute_writes(risk_view):
    """The view itself is read-only."""
    with pytest.raises(AttributeError):
        risk_view.allowed_sections = frozenset({"everything"})  # type: ignore[misc]


def test_view_get_section_returns_independent_copy(risk_view, strategy_pack):
    """Mutating a returned section must not affect the underlying pack."""
    report = risk_view.get_section("validation_report")
    report["sharpe"] = 99.0
    fresh = risk_view.get_section("validation_report")
    assert fresh["sharpe"] == 1.2
