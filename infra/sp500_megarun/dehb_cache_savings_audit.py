"""Read-only savings and conflict audit for legacy train-only DEHB waves."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


class CacheSavingsAuditError(ValueError):
    """Raised when historical evidence is malformed or crosses closed tiers."""


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def audit_historical_records(
    waves: Sequence[Sequence[Mapping[str, Any]]],
) -> Mapping[str, Any]:
    """Estimate the chosen no-live-coordination cache against ordered waves."""

    prior_keys: set[str] = set()
    scientific_results: dict[str, str] = {}
    conflicts: set[str] = set()
    wave_rows: list[dict[str, Any]] = []
    total_requests = 0
    total_physical = 0
    for wave_index, records in enumerate(waves):
        local_physical: set[tuple[str, str]] = set()
        observed_this_wave: set[str] = set()
        requests = 0
        for record in records:
            if record.get("validation_opened") is not False:
                raise CacheSavingsAuditError("HISTORICAL_AUDIT_OPENED_VALIDATION")
            if record.get("locked_opened") is not False:
                raise CacheSavingsAuditError("HISTORICAL_AUDIT_OPENED_LOCKED")
            key = _hash(
                {
                    "lane_id": str(record["lane_id"]),
                    "configuration": record["configuration"],
                    "fidelity": int(record["fidelity"]),
                }
            )
            result_hash = _hash(record["scientific_result"])
            existing = scientific_results.get(key)
            if existing is not None and existing != result_hash:
                conflicts.add(key)
            scientific_results.setdefault(key, result_hash)
            if key not in prior_keys:
                local_physical.add((str(record["island_id"]), key))
            observed_this_wave.add(key)
            requests += 1
        physical = len(local_physical)
        wave_rows.append(
            {
                "wave": wave_index,
                "full_fidelity_requests": requests,
                "estimated_physical_evaluations": physical,
                "estimated_cache_hits": requests - physical,
                "estimated_savings_fraction": (
                    (requests - physical) / requests if requests else 0.0
                ),
            }
        )
        prior_keys.update(observed_this_wave)
        total_requests += requests
        total_physical += physical
    savings = (total_requests - total_physical) / total_requests if total_requests else 0.0
    return {
        "schema_version": 1,
        "waves": wave_rows,
        "full_fidelity_requests": total_requests,
        "estimated_physical_evaluations": total_physical,
        "estimated_cache_hits": total_requests - total_physical,
        "estimated_savings_fraction": savings,
        "scientific_result_conflicts": len(conflicts),
        "acceptance_65_percent": savings >= 0.65 and not conflicts,
        "legacy_cache_import_allowed": False,
        "validation_opened": False,
        "locked_opened": False,
    }


def load_legacy_wave_records(root: Path) -> tuple[Mapping[str, Any], ...]:
    """Load only train-ledger evidence; never open validation or locked artifacts."""

    rows: list[Mapping[str, Any]] = []
    for manifest_path in sorted(Path(root).rglob("island_manifest.json")):
        manifest = json.loads(manifest_path.read_text("utf-8"))
        if manifest.get("validation_opened") is not False:
            raise CacheSavingsAuditError("HISTORICAL_AUDIT_OPENED_VALIDATION")
        if manifest.get("locked_opened") is not False:
            raise CacheSavingsAuditError("HISTORICAL_AUDIT_OPENED_LOCKED")
        frame = pd.read_parquet(manifest_path.parent / "trial_ledger.parquet")
        for trial in frame.to_dict(orient="records"):
            info = json.loads(str(trial["info_json"]))
            if info.get("full_fidelity") is not True:
                continue
            rows.append(
                {
                    "island_id": str(manifest["island_id"]),
                    "lane_id": str(manifest["lane_id"]),
                    "configuration": json.loads(str(trial["configuration_json"])),
                    "fidelity": int(trial["fidelity"]),
                    "scientific_result": {
                        "fitness": float(trial["fitness"]),
                        "cost": float(trial["cost"]),
                        "strategy_fingerprint": info.get("strategy_fingerprint"),
                        "position_fingerprint": info.get("position_fingerprint"),
                        "annualized_strategy_return": info.get("annualized_strategy_return"),
                        "weekly_spy_beat_rate": info.get("weekly_spy_beat_rate"),
                        "archive_key": info.get("archive_key"),
                        "train_feasible": info.get("train_feasible"),
                    },
                    "validation_opened": info.get("validation_opened"),
                    "locked_opened": info.get("locked_opened"),
                }
            )
    return tuple(rows)


__all__ = [
    "CacheSavingsAuditError",
    "audit_historical_records",
    "load_legacy_wave_records",
]
