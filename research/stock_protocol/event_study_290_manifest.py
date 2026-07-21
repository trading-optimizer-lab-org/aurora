"""Derive the exact 10 x 29 event-study manifest from the original artifact."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .campaign import canonical_candidate_id
from .layers import snapshot_payload_hash


EXPECTED_COMBINATION_COUNT = 290
EXPECTED_ENTRY_SPEC_COUNT = 10
EXPECTED_EXIT_SPEC_COUNT = 29
EXPECTED_ENTRY_LAYER_SHA256 = "20438e07450f7bbd4a42c8a63158f4c84f682cd3b95e3e29861a154087cb0d21"
EXPECTED_EXIT_LAYER_SHA256 = "2f98ad06a3011d0708f0490cdba1c7bb1205d626acd34c269400c57f1d3d1a17"
EXPECTED_ENTRY_SNAPSHOT_SHA256 = "2b5c2c59c1d80f702e4f7520c78d50cf622563447cfc547e1796d43eeb8137b0"
EXPECTED_EXIT_SNAPSHOT_SHA256 = "50c05eb68517c7bf6ed3d5508052bc0c1e02bed7bef4b2f32cf72123b834205d"

COMBINATION_MANIFEST_NAME = "original_290_combination_manifest.csv"
ENTRY_SPECS_NAME = "original_10_entry_specs.json"
EXIT_SPECS_NAME = "original_29_exit_specs.json"

_REQUIRED_COLUMNS = {
    "candidate_id",
    "dataset_hash",
    "policy_hash",
    "spec_json",
}
_DERIVED_COLUMNS = (
    "combination_id",
    "upstream_candidate_id",
    "entry_upstream_candidate_id",
    "upstream_candidate_ids_json",
    "entry_spec_id",
    "exit_spec_id",
    "entry_spec_json",
    "exit_spec_json",
    "corrected_track_applicability",
    "corrected_track_reason",
    "source_snapshot_sha256",
    "entry_source_sha256",
)
_BREAKOUT_LEVEL_ENTRY_KINDS = {"breakout", "breakout_rvol"}


class EventStudy290ManifestError(ValueError):
    """Raised when the extracted original artifact violates the frozen contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise EventStudy290ManifestError(f"{field} must contain a complete sha256 hash")
    return normalized


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or ())
        missing = _REQUIRED_COLUMNS - set(fieldnames)
        if missing:
            raise EventStudy290ManifestError(
                f"{path.name} is missing required columns: {sorted(missing)}"
            )
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def _parse_spec(row: Mapping[str, str], *, source: str, row_number: int) -> dict[str, Any]:
    raw = row.get("spec_json", "")
    if not raw:
        raise EventStudy290ManifestError(f"{source} row {row_number} has empty spec_json")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EventStudy290ManifestError(
            f"{source} row {row_number} has invalid spec_json"
        ) from exc
    if not isinstance(value, dict):
        raise EventStudy290ManifestError(f"{source} row {row_number} spec_json is not an object")
    return value


def _validate_identity(
    row: Mapping[str, str], spec: Mapping[str, Any], *, source: str, row_number: int
) -> str:
    candidate_id = row.get("candidate_id", "").strip()
    if not candidate_id:
        raise EventStudy290ManifestError(f"{source} row {row_number} has empty candidate_id")
    expected = canonical_candidate_id(spec)
    if candidate_id != expected:
        raise EventStudy290ManifestError(
            f"{source} row {row_number} candidate_id is not canonical: "
            f"expected {expected}, got {candidate_id}"
        )
    return candidate_id


def canonical_exit_spec_id(exit_spec: Mapping[str, Any]) -> str:
    """Return a stable ID for one artifact-derived exit-axis specification."""

    return canonical_candidate_id(exit_spec)


def _one_hash(rows: Sequence[Mapping[str, str]], field: str, source: str) -> str:
    values = {_require_sha256(row.get(field, ""), field) for row in rows}
    if len(values) != 1:
        raise EventStudy290ManifestError(f"{source} contains multiple {field} values")
    return next(iter(values))


def _entry_record(
    candidate_id: str,
    row: Mapping[str, str],
    spec: Mapping[str, Any],
    *,
    source_snapshot_sha256: str,
    entry_source_sha256: str,
    dataset_hash: str,
    policy_hash: str,
) -> dict[str, Any]:
    upstream_candidate_id = str(spec.get("upstream_candidate_id", "")).strip()
    upstream_candidate_ids = spec.get("upstream_candidate_ids")
    if not upstream_candidate_id:
        raise EventStudy290ManifestError(
            f"entry candidate {candidate_id} has no upstream_candidate_id"
        )
    if not isinstance(upstream_candidate_ids, list) or not upstream_candidate_ids or not all(
        isinstance(value, str) and value for value in upstream_candidate_ids
    ):
        raise EventStudy290ManifestError(
            f"entry candidate {candidate_id} has incomplete upstream_candidate_ids"
        )
    entry = spec.get("entry")
    if not isinstance(entry, dict) or not entry.get("kind"):
        raise EventStudy290ManifestError(f"entry candidate {candidate_id} has no entry rule")
    try:
        entry_test_id = int(spec["entry_test_id"])
        entry_variant_index = int(spec["entry_variant_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventStudy290ManifestError(
            f"entry candidate {candidate_id} has incomplete entry IDs"
        ) from exc
    return {
        "entry_spec_id": candidate_id,
        "candidate_id": candidate_id,
        "upstream_candidate_id": upstream_candidate_id,
        "upstream_candidate_ids": list(upstream_candidate_ids),
        "entry_test_id": entry_test_id,
        "entry_variant_index": entry_variant_index,
        "entry": dict(entry),
        "spec_json": row["spec_json"],
        "dataset_hash": dataset_hash,
        "policy_hash": policy_hash,
        "source_snapshot_sha256": source_snapshot_sha256,
        "entry_source_sha256": entry_source_sha256,
    }


def _exit_projection(spec: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    exit_rule = spec.get("exit")
    if not isinstance(exit_rule, dict) or not exit_rule.get("kind"):
        raise EventStudy290ManifestError(f"candidate {candidate_id} has no exit rule")
    try:
        test_id = int(spec["exit_test_id"])
        variant_index = int(spec["exit_variant_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventStudy290ManifestError(
            f"candidate {candidate_id} has incomplete exit IDs"
        ) from exc
    return {
        "exit_test_id": test_id,
        "exit_variant_index": variant_index,
        "exit": dict(exit_rule),
    }


def _assert_exact_child(
    child: Mapping[str, Any],
    parent: Mapping[str, Any],
    parent_id: str,
    exit_spec: Mapping[str, Any],
    candidate_id: str,
) -> None:
    expected = dict(parent)
    expected["upstream_candidate_id"] = parent_id
    expected["exit_test_id"] = exit_spec["exit_test_id"]
    expected["exit_variant_index"] = exit_spec["exit_variant_index"]
    expected["exit"] = dict(exit_spec["exit"])
    try:
        expected["horizon_sessions"] = int(exit_spec["exit"]["holding_sessions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventStudy290ManifestError(
            f"candidate {candidate_id} exit has no valid holding_sessions"
        ) from exc
    if dict(child) != expected:
        raise EventStudy290ManifestError(
            f"candidate {candidate_id} does not preserve the exact original entry-to-exit logic"
        )


def _applicability(entry: Mapping[str, Any], exit_spec: Mapping[str, Any]) -> tuple[str, str]:
    if exit_spec["exit"].get("kind") != "breakout_failure":
        return "applicable", ""
    if entry.get("kind") in _BREAKOUT_LEVEL_ENTRY_KINDS:
        return "applicable", ""
    return "not_applicable", "missing_breakout_level"


def _snapshot_hash(
    path: Path,
    expected: str | None,
    label: str,
    *,
    layer: str,
    dataset_hash: str,
    policy_hash: str,
) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EventStudy290ManifestError(f"{label} snapshot is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EventStudy290ManifestError(f"{label} snapshot root must be an object")

    declared = _require_sha256(
        str(payload.get("snapshot_sha256", "")), f"{label} snapshot_sha256"
    )
    actual = snapshot_payload_hash(payload)
    if declared != actual:
        raise EventStudy290ManifestError(
            f"{label} snapshot hash mismatch: declared {declared}, calculated {actual}"
        )
    if expected is not None and actual != expected:
        raise EventStudy290ManifestError(
            f"{label} snapshot hash mismatch: expected {expected}, got {actual or 'missing'}"
        )

    if payload.get("layer") != layer:
        raise EventStudy290ManifestError(
            f"{label} snapshot layer mismatch: expected {layer}, got {payload.get('layer')}"
        )
    if payload.get("dataset_hash") != dataset_hash:
        raise EventStudy290ManifestError(f"{label} snapshot dataset_hash mismatch")
    if payload.get("policy_hash") != policy_hash:
        raise EventStudy290ManifestError(f"{label} snapshot policy_hash mismatch")
    input_artifact_name = str(payload.get("input_artifact", ""))
    if not input_artifact_name or Path(input_artifact_name).name != input_artifact_name:
        raise EventStudy290ManifestError(
            f"{label} snapshot input_artifact must be a local artifact name"
        )
    input_artifact = path.parent / input_artifact_name
    if not input_artifact.is_file():
        raise EventStudy290ManifestError(
            f"{label} snapshot input_artifact is missing: {input_artifact_name}"
        )
    declared_artifact_hash = _require_sha256(
        str(payload.get("input_artifact_sha256", "")),
        f"{label} input_artifact_sha256",
    )
    if declared_artifact_hash != _sha256_file(input_artifact):
        raise EventStudy290ManifestError(
            f"{label} snapshot input_artifact_sha256 mismatch"
        )
    return actual


def derive_original_290_manifest(
    source_root: Path,
    *,
    entry_snapshot: Path | None = None,
    exit_snapshot: Path | None = None,
    verify_frozen_source: bool = True,
) -> dict[str, Any]:
    """Read and validate the original artifact without regenerating its strategy grid."""

    root = Path(source_root)
    exit_path = root / "exit_layer_results.csv"
    entry_path = root / "entry_layer_results.csv"
    exit_file_sha256 = _sha256_file(exit_path)
    entry_file_sha256 = _sha256_file(entry_path)
    if verify_frozen_source:
        if exit_file_sha256 != EXPECTED_EXIT_LAYER_SHA256:
            raise EventStudy290ManifestError("exit_layer_results.csv frozen sha256 mismatch")
        if entry_file_sha256 != EXPECTED_ENTRY_LAYER_SHA256:
            raise EventStudy290ManifestError("entry_layer_results.csv frozen sha256 mismatch")
        if entry_snapshot is None or exit_snapshot is None:
            raise EventStudy290ManifestError(
                "frozen entry and exit snapshots are required for strict derivation"
            )
    source_fieldnames, exit_rows = _read_csv(exit_path)
    _, entry_rows = _read_csv(entry_path)
    if len(exit_rows) != EXPECTED_COMBINATION_COUNT:
        raise EventStudy290ManifestError(
            f"exit_layer_results.csv must contain exactly {EXPECTED_COMBINATION_COUNT} rows; "
            f"found {len(exit_rows)}"
        )

    dataset_hash = _one_hash(exit_rows, "dataset_hash", exit_path.name)
    policy_hash = _one_hash(exit_rows, "policy_hash", exit_path.name)
    if _one_hash(entry_rows, "dataset_hash", entry_path.name) != dataset_hash:
        raise EventStudy290ManifestError("entry and exit dataset_hash values differ")
    if _one_hash(entry_rows, "policy_hash", entry_path.name) != policy_hash:
        raise EventStudy290ManifestError("entry and exit policy_hash values differ")

    entry_snapshot_sha256 = (
        _snapshot_hash(
            Path(entry_snapshot),
            EXPECTED_ENTRY_SNAPSHOT_SHA256 if verify_frozen_source else None,
            "entry",
            layer="entries",
            dataset_hash=dataset_hash,
            policy_hash=policy_hash,
        )
        if entry_snapshot is not None
        else ""
    )
    exit_snapshot_sha256 = (
        _snapshot_hash(
            Path(exit_snapshot),
            EXPECTED_EXIT_SNAPSHOT_SHA256 if verify_frozen_source else None,
            "exit",
            layer="exits",
            dataset_hash=dataset_hash,
            policy_hash=policy_hash,
        )
        if exit_snapshot is not None
        else ""
    )
    source_snapshot_sha256 = exit_snapshot_sha256 or exit_file_sha256
    entry_source_sha256 = entry_snapshot_sha256 or entry_file_sha256

    entry_index: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
    for row_number, row in enumerate(entry_rows, start=2):
        spec = _parse_spec(row, source=entry_path.name, row_number=row_number)
        candidate_id = _validate_identity(
            row, spec, source=entry_path.name, row_number=row_number
        )
        if candidate_id in entry_index:
            raise EventStudy290ManifestError(
                f"entry_layer_results.csv repeats candidate_id {candidate_id}"
            )
        entry_index[candidate_id] = (row, spec)

    candidates: set[str] = set()
    source_rows: set[tuple[str, ...]] = set()
    referenced_entries: list[str] = []
    exit_specs: dict[str, dict[str, Any]] = {}
    pairs: set[tuple[str, str]] = set()
    manifest_rows: list[dict[str, str]] = []

    for row_number, row in enumerate(exit_rows, start=2):
        if any(not row.get(field, "") for field in _REQUIRED_COLUMNS):
            raise EventStudy290ManifestError(
                f"{exit_path.name} row {row_number} has an incomplete required field"
            )
        source_key = tuple(row.get(field, "") for field in source_fieldnames)
        if source_key in source_rows:
            raise EventStudy290ManifestError(f"{exit_path.name} contains a duplicate row")
        source_rows.add(source_key)

        spec = _parse_spec(row, source=exit_path.name, row_number=row_number)
        candidate_id = _validate_identity(
            row, spec, source=exit_path.name, row_number=row_number
        )
        if candidate_id in candidates:
            raise EventStudy290ManifestError(f"duplicate candidate_id {candidate_id}")
        candidates.add(candidate_id)

        upstream_id = str(spec.get("upstream_candidate_id", "")).strip()
        if not upstream_id:
            raise EventStudy290ManifestError(
                f"candidate {candidate_id} has no upstream_candidate_id"
            )
        if upstream_id not in entry_index:
            raise EventStudy290ManifestError(
                f"candidate {candidate_id} references missing entry candidate {upstream_id}"
            )
        if upstream_id not in referenced_entries:
            referenced_entries.append(upstream_id)
        entry_row, entry_spec = entry_index[upstream_id]
        exit_projection = _exit_projection(spec, candidate_id)
        exit_spec_id = canonical_exit_spec_id(exit_projection)
        existing = exit_specs.get(exit_spec_id)
        if existing is not None and existing != exit_projection:
            raise EventStudy290ManifestError(f"exit ID collision for {exit_spec_id}")
        exit_specs.setdefault(exit_spec_id, exit_projection)
        _assert_exact_child(spec, entry_spec, upstream_id, exit_projection, candidate_id)

        pair = (upstream_id, exit_spec_id)
        if pair in pairs:
            raise EventStudy290ManifestError(
                f"duplicate entry/exit combination {upstream_id}/{exit_spec_id}"
            )
        pairs.add(pair)
        applicability, reason = _applicability(entry_spec["entry"], exit_projection)
        derived = dict(row)
        derived.update(
            {
                "combination_id": candidate_id,
                "upstream_candidate_id": upstream_id,
                "entry_upstream_candidate_id": str(
                    entry_spec.get("upstream_candidate_id", "")
                ),
                "upstream_candidate_ids_json": _canonical_json(
                    entry_spec.get("upstream_candidate_ids", [])
                ),
                "entry_spec_id": upstream_id,
                "exit_spec_id": exit_spec_id,
                "entry_spec_json": entry_row["spec_json"],
                "exit_spec_json": _canonical_json(exit_projection),
                "corrected_track_applicability": applicability,
                "corrected_track_reason": reason,
                "source_snapshot_sha256": source_snapshot_sha256,
                "entry_source_sha256": entry_source_sha256,
            }
        )
        manifest_rows.append(derived)

    if len(referenced_entries) != EXPECTED_ENTRY_SPEC_COUNT:
        raise EventStudy290ManifestError(
            f"expected {EXPECTED_ENTRY_SPEC_COUNT} entry specs; found {len(referenced_entries)}"
        )
    if len(exit_specs) != EXPECTED_EXIT_SPEC_COUNT:
        raise EventStudy290ManifestError(
            f"expected {EXPECTED_EXIT_SPEC_COUNT} exit specs; found {len(exit_specs)}"
        )
    expected_pairs = {
        (entry_id, exit_spec_id)
        for entry_id in referenced_entries
        for exit_spec_id in exit_specs
    }
    if pairs != expected_pairs:
        missing = expected_pairs - pairs
        extra = pairs - expected_pairs
        raise EventStudy290ManifestError(
            "entry/exit combinations are not the complete Cartesian product: "
            f"missing={len(missing)}, extra={len(extra)}"
        )

    entry_records = [
        _entry_record(
            entry_id,
            *entry_index[entry_id],
            source_snapshot_sha256=source_snapshot_sha256,
            entry_source_sha256=entry_source_sha256,
            dataset_hash=dataset_hash,
            policy_hash=policy_hash,
        )
        for entry_id in referenced_entries
    ]
    exit_records = []
    for exit_spec_id, projection in exit_specs.items():
        matching = [
            row for row in manifest_rows if row["exit_spec_id"] == exit_spec_id
        ]
        exit_records.append(
            {
                "exit_spec_id": exit_spec_id,
                "candidate_id": exit_spec_id,
                **projection,
                "spec_json": _canonical_json(projection),
                "candidate_ids": [row["candidate_id"] for row in matching],
                "upstream_candidate_ids": [
                    row["upstream_candidate_id"] for row in matching
                ],
                "dataset_hash": dataset_hash,
                "policy_hash": policy_hash,
                "source_snapshot_sha256": source_snapshot_sha256,
            }
        )

    return {
        "source_fieldnames": source_fieldnames,
        "manifest_rows": manifest_rows,
        "entry_specs": entry_records,
        "exit_specs": exit_records,
        "dataset_hash": dataset_hash,
        "policy_hash": policy_hash,
        "source_snapshot_sha256": source_snapshot_sha256,
        "entry_source_sha256": entry_source_sha256,
        "exit_layer_file_sha256": exit_file_sha256,
        "entry_layer_file_sha256": entry_file_sha256,
        "entry_snapshot_sha256": entry_snapshot_sha256,
        "exit_snapshot_sha256": exit_snapshot_sha256,
    }


def prepare_original_290_manifest(
    source_root: Path,
    output_root: Path,
    *,
    entry_snapshot: Path | None = None,
    exit_snapshot: Path | None = None,
    verify_frozen_source: bool = True,
) -> dict[str, Any]:
    """Validate the original artifact and write its three deterministic derivatives."""

    derived = derive_original_290_manifest(
        source_root,
        entry_snapshot=entry_snapshot,
        exit_snapshot=exit_snapshot,
        verify_frozen_source=verify_frozen_source,
    )
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / COMBINATION_MANIFEST_NAME
    entry_path = destination / ENTRY_SPECS_NAME
    exit_path = destination / EXIT_SPECS_NAME

    fieldnames = [*derived["source_fieldnames"], *_DERIVED_COLUMNS]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(derived["manifest_rows"])
    entry_path.write_text(
        json.dumps(derived["entry_specs"], indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    exit_path.write_text(
        json.dumps(derived["exit_specs"], indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "combination_manifest": str(manifest_path),
        "entry_specs": str(entry_path),
        "exit_specs": str(exit_path),
        "combination_count": EXPECTED_COMBINATION_COUNT,
        "entry_spec_count": EXPECTED_ENTRY_SPEC_COUNT,
        "exit_spec_count": EXPECTED_EXIT_SPEC_COUNT,
        "dataset_hash": derived["dataset_hash"],
        "policy_hash": derived["policy_hash"],
        "source_snapshot_sha256": derived["source_snapshot_sha256"],
        "entry_snapshot_sha256": derived["entry_snapshot_sha256"],
        "exit_snapshot_sha256": derived["exit_snapshot_sha256"],
        "entry_layer_file_sha256": derived["entry_layer_file_sha256"],
        "exit_layer_file_sha256": derived["exit_layer_file_sha256"],
    }


build_original_290_manifest = prepare_original_290_manifest


__all__ = [
    "COMBINATION_MANIFEST_NAME",
    "ENTRY_SPECS_NAME",
    "EXIT_SPECS_NAME",
    "EXPECTED_COMBINATION_COUNT",
    "EXPECTED_ENTRY_SPEC_COUNT",
    "EXPECTED_EXIT_SPEC_COUNT",
    "EventStudy290ManifestError",
    "build_original_290_manifest",
    "canonical_exit_spec_id",
    "derive_original_290_manifest",
    "prepare_original_290_manifest",
]
