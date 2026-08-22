from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aurora.infra.sp500_megarun.catalog_capacity import (
    CACHE_STORAGE_LIMIT_BYTES,
    CatalogCapacityProfileV1,
    CatalogCapacityWorkloadV1,
    CatalogLiveCapacitySnapshotV1,
    StorageObjectV1,
    StorageWriteReceiptV1,
    pack_catalog_work_units,
    select_safe_catalog_capacity,
    split_catalog_worker_matrix,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
GIB = 1024**3


def qualified_profile(**updates: object) -> CatalogCapacityProfileV1:
    values: dict[str, object] = {
        "organization": "trading-optimizer-lab-org",
        "repository": "aurora",
        "repository_visibility": "public",
        "plan": "enterprise",
        "maximum_concurrent_jobs": 360,
        "proven_uncontended_floor": 120,
        "qualified_at": NOW - timedelta(days=1),
        "topology_qualified": True,
        "topology_sample_count": 3,
        "included_shared_artifact_package_storage_bytes": 50 * GIB,
        "organization_sha256": "1" * 64,
        "repository_plan_sha256": "2" * 64,
        "runner_class_sha256": "3" * 64,
        "capacity_contract_sha256": "4" * 64,
        "qualification_receipt_sha256": "5" * 64,
        "qualification_run_ids": ("100", "101", "102"),
    }
    values.update(updates)
    return CatalogCapacityProfileV1.create(**values)


def live_capacity(**updates: object) -> CatalogLiveCapacitySnapshotV1:
    values: dict[str, object] = {
        "observed_at": NOW - timedelta(minutes=1),
        "calibration_observed_at": NOW - timedelta(days=1),
        "available_standard_jobs": 360,
        "fresh_runner_health": True,
        "runner_image": "ubuntu-24.04",
        "standard_runner_only": True,
        "larger_runners_enabled": False,
        "self_hosted_runners_enabled": False,
        "zero_actions_spend_budget_verified": True,
        "zero_actions_storage_budget_verified": True,
        "zero_cache_storage_budget_verified": True,
        "zero_spend_budgets_receipt_sha256": "6" * 64,
        "cache_storage_limit_bytes": CACHE_STORAGE_LIMIT_BYTES,
        "cache_retention_days": 90,
        "artifact_package_inventory_complete": True,
        "artifact_package_recent_writes_complete": True,
        "reported_shared_artifact_package_storage_bytes": 2 * GIB,
        "artifact_package_objects": (),
        "artifact_package_recent_writes": (),
        "cache_inventory_complete": True,
        "cache_recent_writes_complete": True,
        "reported_cache_storage_bytes": GIB,
        "cache_objects": (),
        "cache_recent_writes": (),
        "authority_ledger_observable": True,
        "authority_ledger_complete": True,
        "authority_ledger_stable": True,
        "authority_ledger_conflicting": False,
        "active_heavy_campaign_ids": (),
        "requested_campaign_id": "7" * 64,
        "organization_sha256": "1" * 64,
        "repository_plan_sha256": "2" * 64,
        "runner_class_sha256": "3" * 64,
        "capacity_contract_sha256": "4" * 64,
        "calibration_receipt_sha256": "8" * 64,
    }
    values.update(updates)
    return CatalogLiveCapacitySnapshotV1.create(**values)


def workload_fit(**updates: object) -> CatalogCapacityWorkloadV1:
    values: dict[str, object] = {
        "registered_maximum_workers": 360,
        "logical_work_units": 7200,
        "processes_per_worker": 4,
        "component_workers": 120,
        "component_processes_per_worker": 4,
        "topology_sample_count": 3,
        "memory_fraction_p50": 0.40,
        "memory_fraction_p95": 0.55,
        "memory_fraction_p99": 0.60,
        "disk_fraction_p50": 0.35,
        "disk_fraction_p95": 0.45,
        "disk_fraction_p99": 0.50,
        "runner_start_seconds_p50": 8.0,
        "runner_start_seconds_p95": 15.0,
        "runner_start_seconds_p99": 20.0,
        "unit_seconds_p50": 1.0,
        "unit_seconds_p95": 1.5,
        "unit_seconds_p99": 2.0,
        "projected_artifact_storage_bytes": 3 * GIB,
        "projected_cache_storage_bytes": 2 * GIB,
        "planned_new_cache_entry_count": 120,
        "selected_component_bundle_count": 64,
        "planned_cache_upload_requests_per_minute_peak": 100,
        "planned_cache_download_requests_per_minute_peak": 800,
        "artifact_transport_retention_days": 1,
        "estimated_paid_runner_minutes": 0,
        "estimated_paid_actions_cost": 0,
    }
    values.update(updates)
    return CatalogCapacityWorkloadV1(**values)


def inputs(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "profile": qualified_profile(),
        "live": live_capacity(),
        "workload": workload_fit(),
        "now": NOW,
    }
    values.update(updates)
    return values


def test_selects_highest_proven_free_capacity() -> None:
    decision = select_safe_catalog_capacity(**inputs())

    assert decision.workers == 360
    assert decision.standard_runner_only is True
    assert decision.estimated_paid_runner_minutes == 0
    assert decision.estimated_paid_actions_cost == 0
    assert decision.projected_artifact_storage_bytes <= (
        decision.verified_free_artifact_headroom_bytes
    )
    assert decision.projected_cache_storage_bytes <= (
        decision.verified_free_cache_headroom_bytes
    )


def test_uses_lower_live_available_capacity_without_changing_science() -> None:
    decision = select_safe_catalog_capacity(
        **inputs(live=live_capacity(available_standard_jobs=173))
    )

    assert decision.workers == 173
    assert decision.campaign_identity_changed is False


def test_unobservable_account_wide_usage_uses_proven_safe_floor() -> None:
    decision = select_safe_catalog_capacity(
        **inputs(live=live_capacity(available_standard_jobs=None))
    )

    assert decision.workers == 120
    assert decision.decision_reason == "ACCOUNT_USAGE_UNKNOWN_USING_SAFE_FLOOR"


@pytest.mark.parametrize("workers", (1, 256, 257, 359, 360))
def test_matrix_splitting_is_exact_and_unique(workers: int) -> None:
    matrices = split_catalog_worker_matrix(workers)
    flattened = tuple(worker for matrix in matrices for worker in matrix)

    assert flattened == tuple(range(workers))
    assert len(flattened) == len(set(flattened))
    assert all(1 <= len(matrix) <= 256 for matrix in matrices)


def test_logical_units_are_packed_once_without_changing_identity() -> None:
    assignments = pack_catalog_work_units(tuple(range(7200)), workers=173)
    flattened = tuple(unit for assignment in assignments for unit in assignment)

    assert sorted(flattened) == list(range(7200))
    assert len(flattened) == len(set(flattened))
    assert max(map(len, assignments)) - min(map(len, assignments)) <= 1


@pytest.mark.parametrize(
    ("profile_update", "live_update", "workload_update", "reason"),
    (
        ({"qualified_at": NOW - timedelta(days=8)}, {}, {}, "CAPACITY_PROFILE_STALE"),
        ({"topology_qualified": False}, {}, {}, "CAPACITY_TOPOLOGY_UNQUALIFIED"),
        ({}, {}, {"estimated_paid_runner_minutes": 1}, "PAID_RUNNER_FORBIDDEN"),
        ({}, {"larger_runners_enabled": True}, {}, "LARGER_RUNNER_FORBIDDEN"),
        ({}, {"self_hosted_runners_enabled": True}, {}, "SELF_HOSTED_RUNNER_FORBIDDEN"),
        ({}, {"zero_actions_spend_budget_verified": False}, {}, "ZERO_ACTIONS_SPEND_BUDGET_REQUIRED"),
        ({}, {"zero_actions_storage_budget_verified": False}, {}, "ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED"),
        ({}, {"zero_cache_storage_budget_verified": False}, {}, "ZERO_CACHE_STORAGE_BUDGET_REQUIRED"),
        ({}, {"cache_storage_limit_bytes": CACHE_STORAGE_LIMIT_BYTES + 1}, {}, "FREE_CACHE_STORAGE_LIMIT_REQUIRED"),
        ({}, {"artifact_package_inventory_complete": False}, {}, "FREE_ARTIFACT_STORAGE_UNPROVEN"),
        ({}, {"artifact_package_recent_writes_complete": False}, {}, "FREE_ARTIFACT_STORAGE_UNPROVEN"),
        ({}, {"cache_inventory_complete": False}, {}, "FREE_CACHE_STORAGE_UNPROVEN"),
        ({}, {"cache_recent_writes_complete": False}, {}, "FREE_CACHE_STORAGE_UNPROVEN"),
        ({}, {}, {"memory_fraction_p99": 0.71}, "CAPACITY_MEMORY_MARGIN_INSUFFICIENT"),
        ({}, {}, {"disk_fraction_p99": 0.71}, "CAPACITY_DISK_MARGIN_INSUFFICIENT"),
        ({}, {"fresh_runner_health": False}, {}, "LIVE_CAPACITY_HEALTH_MISSING"),
    ),
)
def test_unproven_or_nonfree_capacity_blocks(
    profile_update: dict[str, object],
    live_update: dict[str, object],
    workload_update: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        select_safe_catalog_capacity(
            profile=qualified_profile(**profile_update),
            live=live_capacity(**live_update),
            workload=workload_fit(**workload_update),
            now=NOW,
        )


def _artifact_boundary_live(projected: int, delta: int) -> CatalogLiveCapacitySnapshotV1:
    allowance = 50 * GIB
    reserve = allowance // 5
    used = allowance - reserve - projected + delta
    return live_capacity(
        reported_shared_artifact_package_storage_bytes=used,
        artifact_package_objects=(),
        artifact_package_recent_writes=(),
    )


@pytest.mark.parametrize(("delta", "allowed"), ((-1, True), (0, True), (1, False)))
def test_artifact_storage_boundary_is_exact(delta: int, allowed: bool) -> None:
    call = lambda: select_safe_catalog_capacity(
        **inputs(live=_artifact_boundary_live(3 * GIB, delta))
    )
    if allowed:
        assert call().projected_artifact_storage_bytes == 3 * GIB
    else:
        with pytest.raises(ValueError, match="FREE_ARTIFACT_STORAGE_INSUFFICIENT"):
            call()


@pytest.mark.parametrize(("delta", "allowed"), ((-1, True), (0, True), (1, False)))
def test_cache_storage_boundary_is_exact(delta: int, allowed: bool) -> None:
    reserve = CACHE_STORAGE_LIMIT_BYTES // 10
    used = CACHE_STORAGE_LIMIT_BYTES - reserve - 2 * GIB + delta
    call = lambda: select_safe_catalog_capacity(
        **inputs(live=live_capacity(reported_cache_storage_bytes=used))
    )
    if allowed:
        assert call().projected_cache_storage_bytes == 2 * GIB
    else:
        with pytest.raises(ValueError, match="FREE_CACHE_STORAGE_INSUFFICIENT"):
            call()


def test_recent_write_already_in_inventory_is_not_counted_twice() -> None:
    receipt = StorageWriteReceiptV1(
        object_id="artifact-a",
        size_bytes=GIB,
        written_at=NOW - timedelta(minutes=2),
        receipt_sha256="9" * 64,
    )
    decision = select_safe_catalog_capacity(
        **inputs(
            live=live_capacity(
                reported_shared_artifact_package_storage_bytes=0,
                artifact_package_objects=(
                    StorageObjectV1(object_id="artifact-a", size_bytes=GIB),
                ),
                artifact_package_recent_writes=(receipt,),
            )
        )
    )

    assert decision.reconciled_live_artifact_package_storage_bytes == GIB
    assert decision.unreflected_artifact_package_upload_bytes_12h == 0


def test_unreflected_recent_write_consumes_headroom() -> None:
    receipt = StorageWriteReceiptV1(
        object_id="not-yet-reported",
        size_bytes=38 * GIB,
        written_at=NOW - timedelta(minutes=2),
        receipt_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="FREE_ARTIFACT_STORAGE_INSUFFICIENT"):
        select_safe_catalog_capacity(
            **inputs(
                live=live_capacity(
                    reported_shared_artifact_package_storage_bytes=0,
                    artifact_package_recent_writes=(receipt,),
                )
            )
        )


def test_future_dated_storage_write_blocks_instead_of_disappearing() -> None:
    receipt = StorageWriteReceiptV1(
        object_id="future-artifact",
        size_bytes=GIB,
        written_at=NOW + timedelta(minutes=2),
        receipt_sha256="b" * 64,
    )

    with pytest.raises(ValueError, match="FREE_ARTIFACT_STORAGE_UNPROVEN"):
        select_safe_catalog_capacity(
            **inputs(
                live=live_capacity(
                    artifact_package_recent_writes=(receipt,),
                )
            )
        )


def test_distinct_active_heavy_campaign_is_deferred_without_workers() -> None:
    decision = select_safe_catalog_capacity(
        **inputs(
            live=live_capacity(active_heavy_campaign_ids=("b" * 64,))
        )
    )

    assert decision.admission_status == "DEFERRED"
    assert decision.workers == 0
    assert decision.matrix_sizes == ()
    assert decision.retry_not_before == NOW + timedelta(minutes=5)


def test_unproven_heavy_campaign_lease_blocks() -> None:
    with pytest.raises(ValueError, match="HEAVY_CAMPAIGN_LEASE_UNPROVEN"):
        select_safe_catalog_capacity(
            **inputs(live=live_capacity(authority_ledger_stable=False))
        )
