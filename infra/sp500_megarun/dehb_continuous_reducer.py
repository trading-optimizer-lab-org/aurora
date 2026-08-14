"""Immutable train-only snapshots and winner freeze for continuous DEHB."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from aurora.infra.sp500_megarun.dehb_global_merge import (
    select_seed_consensus_finalists,
)


class ContinuousReducerError(RuntimeError):
    """Raised when a snapshot contains unsafe or contradictory evidence."""


@dataclass(frozen=True)
class ContinuousReducerSnapshotV1:
    cutoff_sequence: int
    snapshot_sha256: str
    physical_result_count: int
    champion_count: int
    finalists: tuple[Mapping[str, Any], ...]
    validation_opened: bool = False
    locked_opened: bool = False
    schema_version: int = 1


@dataclass(frozen=True)
class TrainFreezeDecisionV1:
    action: str
    snapshot_sha256: str
    winner: Mapping[str, Any] | None
    validation_opened: bool = False
    locked_opened: bool = False
    schema_version: int = 1


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


class ContinuousReducer:
    """Reduce an exact database sequence without pausing the search pool."""

    def __init__(self, store: object) -> None:
        self.store = store

    def build_snapshot(self, cutoff_sequence: int) -> ContinuousReducerSnapshotV1:
        cutoff = int(cutoff_sequence)
        if cutoff < 0:
            raise ContinuousReducerError("CONTINUOUS_REDUCER_CUTOFF_INVALID")
        rows = [dict(row) for row in self.store.result_rows(cutoff)]
        for row in rows:
            if row.get("validation_opened") is not False:
                raise ContinuousReducerError("CONTINUOUS_REDUCER_OPENED_VALIDATION")
            if row.get("locked_opened") is not False:
                raise ContinuousReducerError("CONTINUOUS_REDUCER_OPENED_LOCKED")

        by_island: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("full_fidelity") is not True:
                continue
            island_id = str(row.get("island_id", ""))
            if not island_id:
                raise ContinuousReducerError("CONTINUOUS_REDUCER_ISLAND_ID_MISSING")
            current = by_island.get(island_id)
            archive_key = tuple(float(value) for value in row.get("archive_key", ()))
            if not archive_key:
                raise ContinuousReducerError("CONTINUOUS_REDUCER_ARCHIVE_KEY_MISSING")
            if current is None or archive_key < tuple(
                float(value) for value in current["archive_key"]
            ):
                by_island[island_id] = row

        champions = [by_island[key] for key in sorted(by_island)]
        finalists = select_seed_consensus_finalists(champions)
        evidence = {
            "schema_version": 1,
            "cutoff_sequence": cutoff,
            "physical_result_count": len(rows),
            "result_receipts": [
                hashlib.sha256(_canonical(row)).hexdigest()
                for row in sorted(
                    rows,
                    key=lambda item: (
                        int(item.get("created_sequence", 0)),
                        str(item.get("island_id", "")),
                        str(item.get("strategy_fingerprint", "")),
                    ),
                )
            ],
            "champions": champions,
            "finalists": finalists,
            "validation_opened": False,
            "locked_opened": False,
        }
        digest = hashlib.sha256(b"SP500-DEHB-CONTINUOUS-SNAPSHOT-V1\0" + _canonical(evidence))
        snapshot = ContinuousReducerSnapshotV1(
            cutoff_sequence=cutoff,
            snapshot_sha256=digest.hexdigest(),
            physical_result_count=len(rows),
            champion_count=len(champions),
            finalists=tuple(finalists),
        )
        self.store.persist_reducer_snapshot(snapshot)
        return snapshot

    def attempt_train_freeze(
        self, snapshot: ContinuousReducerSnapshotV1
    ) -> TrainFreezeDecisionV1:
        eligible = [
            dict(row)
            for row in snapshot.finalists
            if row.get("global_robustness_passed") is True
            and (
                row.get("train_freeze_eligible") is True
                or row.get("all_60_train_gates_passed") is True
            )
            and row.get("train_feasible") is True
            and row.get("validation_opened") is False
            and row.get("locked_opened") is False
        ]
        if not eligible:
            return TrainFreezeDecisionV1(
                action="searching",
                snapshot_sha256=snapshot.snapshot_sha256,
                winner=None,
            )
        winner = min(
            eligible,
            key=lambda row: (
                tuple(float(value) for value in row["archive_key"]),
                str(row["strategy_fingerprint"]),
            ),
        )
        self.store.freeze_campaign(snapshot.snapshot_sha256, winner)
        return TrainFreezeDecisionV1(
            action="frozen",
            snapshot_sha256=snapshot.snapshot_sha256,
            winner=winner,
        )


__all__ = [
    "ContinuousReducer",
    "ContinuousReducerError",
    "ContinuousReducerSnapshotV1",
    "TrainFreezeDecisionV1",
]
