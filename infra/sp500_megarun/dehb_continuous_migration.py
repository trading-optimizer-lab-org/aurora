"""Fail-closed evidence for cloning the continuous DEHB coordinator database."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


class ContinuousMigrationError(RuntimeError):
    """Raised when a coordinator database clone is not exact and closed."""


def canonical_rows_sha256(rows: Iterable[str]) -> str:
    """Hash an already canonically ordered stream of PostgreSQL JSON rows."""

    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _report_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_clone_inventories(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove that source and target contain the same closed campaign rows."""

    source_campaign = str(source.get("campaign_id", ""))
    target_campaign = str(target.get("campaign_id", ""))
    if not source_campaign or source_campaign != target_campaign:
        raise ContinuousMigrationError("CLONE_CAMPAIGN_ID_MISMATCH")

    for inventory in (source, target):
        if (
            bool(inventory.get("validation_opened"))
            or bool(inventory.get("locked_opened"))
            or int(inventory.get("boundary_violations", 0)) != 0
        ):
            raise ContinuousMigrationError("CLONE_BOUNDARY_OPENED")
        if int(inventory.get("conflict_count", 0)) != 0:
            raise ContinuousMigrationError("CLONE_CONFLICT_PRESENT")

    identity_fields = ("campaign_state", "code_commit_sha")
    if any(source.get(field) != target.get(field) for field in identity_fields):
        raise ContinuousMigrationError("CLONE_CAMPAIGN_IDENTITY_MISMATCH")

    source_tables = dict(source.get("tables", {}))
    target_tables = dict(target.get("tables", {}))
    if set(source_tables) != set(target_tables):
        raise ContinuousMigrationError("CLONE_TABLE_SET_MISMATCH")
    if source_tables != target_tables:
        raise ContinuousMigrationError("CLONE_TABLE_DIGEST_MISMATCH")

    report: dict[str, Any] = {
        "schema_version": 1,
        "verified": True,
        "campaign_id": source_campaign,
        "campaign_state": source.get("campaign_state"),
        "code_commit_sha": source.get("code_commit_sha"),
        "validation_opened": False,
        "locked_opened": False,
        "conflict_count": 0,
        "source_database_size_bytes": int(source.get("database_size_bytes", 0)),
        "target_database_size_bytes": int(target.get("database_size_bytes", 0)),
        "tables": source_tables,
    }
    report["verification_sha256"] = _report_sha256(report)
    return report


__all__ = [
    "ContinuousMigrationError",
    "canonical_rows_sha256",
    "compare_clone_inventories",
]
