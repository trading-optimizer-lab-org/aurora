"""Immutable handoff contracts between stock-protocol research layers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


SCHEMA_VERSION = 1
LOCKED_START = pd.Timestamp("2021-01-01")
PHASE_ORDER = (
    "signal",
    "weights",
    "entries",
    "exits",
    "portfolio",
    "costs",
    "walk_forward",
    "robustness",
    "final",
)


def sha256_file(path: Path) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_payload_hash(payload: Mapping[str, Any]) -> str:
    """Return the canonical hash, excluding the self-referential hash field."""

    canonical = {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    raw = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def required_predecessor(phase: str) -> str | None:
    """Return the one layer a phase is allowed to consume."""

    if phase not in PHASE_ORDER:
        raise ValueError(f"unknown phase: {phase}")
    index = PHASE_ORDER.index(phase)
    return None if index == 0 else PHASE_ORDER[index - 1]


def _validate_dates(date_start: str, date_end: str) -> tuple[str, str]:
    start = pd.Timestamp(date_start).normalize()
    end = pd.Timestamp(date_end).normalize()
    if start > end:
        raise ValueError("snapshot date_start must not exceed date_end")
    if end >= LOCKED_START:
        raise ValueError("snapshot crosses locked boundary 2021-01-01")
    return start.date().isoformat(), end.date().isoformat()


def freeze_snapshot(
    *,
    layer: str,
    input_artifact: Path,
    output_path: Path,
    policy_hash: str,
    dataset_hash: str,
    date_start: str,
    date_end: str,
    universe: str,
    decisions: Sequence[Mapping[str, Any]],
) -> Path:
    """Freeze an auditable decision set for exactly one protocol layer."""

    required_predecessor(layer)
    if not input_artifact.is_file():
        raise FileNotFoundError(input_artifact)
    if not policy_hash or not dataset_hash:
        raise ValueError("policy_hash and dataset_hash are required")
    start, end = _validate_dates(date_start, date_end)
    frozen_decisions = [dict(item) for item in decisions]
    if not frozen_decisions:
        raise ValueError(f"layer {layer} cannot freeze an empty decision set")
    for decision in frozen_decisions:
        if not isinstance(decision.get("parameters"), Mapping):
            raise ValueError("each decision must include parameters")
        if not isinstance(decision.get("validation_metrics"), Mapping):
            raise ValueError("each decision must include validation_metrics")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layer": layer,
        "previous_layer": required_predecessor(layer),
        "input_artifact": input_artifact.name,
        "input_artifact_sha256": sha256_file(input_artifact),
        "policy_hash": policy_hash,
        "dataset_hash": dataset_hash,
        "date_start": start,
        "date_end": end,
        "universe": universe,
        "survivorship_limited": universe != "historical_point_in_time_universe",
        "locked_opened": False,
        "decisions": frozen_decisions,
    }
    payload["snapshot_sha256"] = snapshot_payload_hash(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str),
        encoding="utf-8",
    )
    return output_path


def load_snapshot(
    path: Path,
    expected_layer: str,
    expected_policy_hash: str,
    expected_dataset_hash: str,
) -> dict[str, Any]:
    """Load a snapshot only when its complete provenance contract matches."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot root must be an object")
    if payload.get("snapshot_sha256") != snapshot_payload_hash(payload):
        raise ValueError("snapshot hash mismatch")
    if payload.get("layer") != expected_layer:
        raise ValueError(
            f"snapshot layer mismatch: expected {expected_layer}, got {payload.get('layer')}"
        )
    if payload.get("policy_hash") != expected_policy_hash:
        raise ValueError("snapshot policy hash mismatch")
    if payload.get("dataset_hash") != expected_dataset_hash:
        raise ValueError("snapshot dataset hash mismatch")
    if payload.get("locked_opened") is not False:
        raise ValueError("snapshot locked_opened must remain false")
    _validate_dates(str(payload.get("date_start")), str(payload.get("date_end")))
    if payload.get("previous_layer") != required_predecessor(expected_layer):
        raise ValueError("snapshot previous layer contract mismatch")
    if not payload.get("decisions"):
        raise ValueError("snapshot has no frozen decisions")
    return payload
