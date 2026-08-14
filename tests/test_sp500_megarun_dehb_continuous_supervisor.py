from __future__ import annotations

import pytest


def test_database_preflight_requires_tls_and_capacity():
    from aurora.infra.sp500_megarun.dehb_continuous_supervisor import (
        ContinuousSupervisorError,
        verify_database_contract,
    )

    with pytest.raises(ContinuousSupervisorError, match="DATABASE_TLS_REQUIRED"):
        verify_database_contract("postgresql://db.example/aurora", max_connections=500)
    with pytest.raises(ContinuousSupervisorError, match="DATABASE_CAPACITY_TOO_LOW"):
        verify_database_contract(
            "postgresql://db.example/aurora?sslmode=require", max_connections=399
        )


def test_pool_generation_reservation_is_idempotent_and_keeps_360_sessions():
    from aurora.infra.sp500_megarun.dehb_continuous_supervisor import PoolSupervisor

    supervisor = PoolSupervisor()
    first = supervisor.reserve_generation("pool-0007")
    second = supervisor.reserve_generation("pool-0007")

    assert first.dispatch is True
    assert second.dispatch is False
    decision = supervisor.decide(
        campaign_state="searching",
        active_sessions=357,
        active_slots=1_428,
        ready_work=2_880,
        coordinator_healthy=True,
        conflict_count=0,
        boundary_violations=0,
    )
    assert decision.action == "healthy"
    assert decision.target_sessions == 360


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"conflict_count": 1}, "halt_conflict"),
        ({"boundary_violations": 1}, "halt_boundary"),
        ({"coordinator_healthy": False}, "recover_coordinator"),
        ({"active_sessions": 340}, "dispatch_next_generation"),
    ],
)
def test_supervisor_fail_closed_and_replenishment_decisions(changes, expected):
    from aurora.infra.sp500_megarun.dehb_continuous_supervisor import PoolSupervisor

    values = {
        "campaign_state": "searching",
        "active_sessions": 360,
        "active_slots": 1_440,
        "ready_work": 2_880,
        "coordinator_healthy": True,
        "conflict_count": 0,
        "boundary_violations": 0,
    }
    values.update(changes)
    assert PoolSupervisor().decide(**values).action == expected
