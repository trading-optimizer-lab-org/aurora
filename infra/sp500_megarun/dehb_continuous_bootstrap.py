"""Deterministic bootstrap records for continuous SP500 DEHB."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from aurora.infra.sp500_megarun.dehb_campaign_contract import build_island_schedule


@dataclass(frozen=True)
class IslandBootstrapRecordV1:
    island_id: str
    lane_id: str
    replica: int
    restart_seed: int
    n_workers: int
    validation_opened: bool = False
    locked_opened: bool = False
    schema_version: int = 1


@dataclass(frozen=True)
class BootstrapReceiptV1:
    campaign_id: str
    island_count: int
    receipt_sha256: str
    validation_opened: bool = False
    locked_opened: bool = False
    schema_version: int = 1


def build_island_bootstrap_records(contract: Any) -> tuple[IslandBootstrapRecordV1, ...]:
    """Flatten the frozen official campaign topology into 720 island rows."""

    records = tuple(
        IslandBootstrapRecordV1(
            island_id=island.island_id,
            lane_id=island.lane_id,
            replica=int(island.replicate),
            restart_seed=int(island.seed),
            n_workers=int(island.n_workers),
        )
        for job in build_island_schedule(contract)
        for island in job.islands
    )
    if (
        len(records) != 720
        or len({record.island_id for record in records}) != 720
        or any(record.n_workers != 4 for record in records)
    ):
        raise ValueError("CONTINUOUS_BOOTSTRAP_ISLAND_TOPOLOGY_INVALID")
    return records


def build_worker_pool_matrices(pool_generation: str) -> Mapping[str, Mapping[str, Any]]:
    """Build three 240-lifetime matrices with 120 concurrent runners per shard."""

    generation = str(pool_generation)
    if not generation:
        raise ValueError("CONTINUOUS_POOL_GENERATION_INVALID")
    matrices: dict[str, dict[str, Any]] = {}
    for shard_index, shard in enumerate("ABC"):
        entries = []
        for ordinal in range(240):
            global_ordinal = shard_index * 240 + ordinal
            entries.append(
                {
                    "worker_lifetime_id": f"{generation}-{global_ordinal:04d}",
                    "pool_generation": generation,
                    "shard_id": shard,
                    "shard_ordinal": ordinal,
                    "executor_slots": 4,
                    "lifetime_minutes": 300,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            )
        # Execution controls such as ``max-parallel`` belong to the workflow's
        # strategy block.  A scalar control inside ``matrix`` makes GitHub omit
        # every expanded worker job even though the planning job succeeds.
        matrices[shard] = {"include": entries}
    return matrices


def bootstrap_campaign(
    connection: Any,
    *,
    campaign_id: str,
    campaign: Any,
    launch_contract_sha256: str,
    code_commit_sha: str,
    numeric_profile_sha256: str,
    schema_applier: Any,
) -> BootstrapReceiptV1:
    """Create one immutable closed-boundary campaign and all official islands."""

    records = build_island_bootstrap_records(campaign)
    schema_applier(connection)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO campaigns (
                    campaign_id, schema_version, state, scientific_contract_sha256,
                    launch_contract_sha256, code_commit_sha, train_manifest_sha256,
                    train_spy_sha256, numeric_profile_sha256,
                    validation_opened, locked_opened
                ) VALUES (%s, 1, 'searching', %s, %s, %s, %s, %s, %s, false, false)
                ON CONFLICT (campaign_id) DO NOTHING
                """,
                (
                    str(campaign_id),
                    str(campaign.sha256),
                    str(launch_contract_sha256),
                    str(code_commit_sha),
                    str(campaign.train_snapshot_manifest_sha256),
                    str(campaign.train_spy_sha256),
                    str(numeric_profile_sha256),
                ),
            )
            cursor.executemany(
                """
                INSERT INTO islands (
                    campaign_id, island_id, schema_version, lane_id, replica,
                    restart_seed, status, runtime_state,
                    created_sequence, updated_sequence
                ) VALUES (%s, %s, 1, %s, %s, %s, 'runnable', '{}'::jsonb, 0, 0)
                ON CONFLICT (campaign_id, island_id) DO NOTHING
                """,
                [
                    (
                        str(campaign_id),
                        record.island_id,
                        record.lane_id,
                        record.replica,
                        record.restart_seed,
                    )
                    for record in records
                ],
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    payload = {
        "schema_version": 1,
        "campaign_id": str(campaign_id),
        "campaign_contract_sha256": str(campaign.sha256),
        "launch_contract_sha256": str(launch_contract_sha256),
        "code_commit_sha": str(code_commit_sha),
        "numeric_profile_sha256": str(numeric_profile_sha256),
        "island_count": len(records),
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return BootstrapReceiptV1(
        campaign_id=str(campaign_id),
        island_count=len(records),
        receipt_sha256=receipt_sha256,
    )


__all__ = [
    "IslandBootstrapRecordV1",
    "BootstrapReceiptV1",
    "bootstrap_campaign",
    "build_island_bootstrap_records",
    "build_worker_pool_matrices",
]
