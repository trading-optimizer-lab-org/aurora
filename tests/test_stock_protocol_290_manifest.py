"""Contract tests for the artifact-derived original 10 x 29 manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aurora.research.stock_protocol.campaign import canonical_candidate_id
from aurora.research.stock_protocol.event_study_290_manifest import (
    COMBINATION_MANIFEST_NAME,
    ENTRY_SPECS_NAME,
    EXIT_SPECS_NAME,
    EventStudy290ManifestError,
    canonical_exit_spec_id,
    prepare_original_290_manifest,
)
from aurora.research.stock_protocol.layers import freeze_snapshot, snapshot_payload_hash


DATASET_HASH = "1" * 64
POLICY_HASH = "2" * 64


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _source_artifact(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    root.mkdir()
    entry_rows: list[dict[str, str]] = []
    entries: list[tuple[str, dict[str, object]]] = []
    for index in range(10):
        entry_rule: dict[str, object]
        if index < 2:
            entry_rule = {
                "kind": "breakout_rvol",
                "window": 20,
                "threshold": 1.5 + index,
                "max_wait_sessions": 21,
            }
        else:
            entry_rule = {
                "kind": "consolidation",
                "window": 20 + index,
                "max_width": 0.15,
            }
        spec: dict[str, object] = {
            "signal_test_id": 2,
            "signal_variant_index": 0,
            "signal_variant": {"lookback": 126, "skip": 21},
            "selection": {"kind": "top_percent", "value": 20.0},
            "entry": entry_rule,
            "entry_test_id": 18 if index < 2 else 17,
            "entry_variant_index": index,
            "exit": {"kind": "none", "holding_sessions": 63},
            "horizon_sessions": 63,
            "portfolio": {"sizing": "equal"},
            "cost_bps": 0,
            "upstream_candidate_id": f"stock_weight_{index:02d}",
            "upstream_candidate_ids": [f"stock_signal_{index:02d}"],
        }
        candidate_id = canonical_candidate_id(spec)
        entries.append((candidate_id, spec))
        entry_rows.append(
            {
                "candidate_id": candidate_id,
                "dataset_hash": DATASET_HASH,
                "policy_hash": POLICY_HASH,
                "spec_json": json.dumps(spec, sort_keys=True, separators=(",", ":")),
                "status": "evaluated",
            }
        )

    exit_axis: list[dict[str, object]] = []
    for index in range(29):
        if index < 4:
            rule = {
                "kind": "breakout_failure",
                "failure_window": index + 1,
                "holding_sessions": 252,
            }
        else:
            rule = {"kind": "take_profit", "target_pct": index, "holding_sessions": 252}
        exit_axis.append(
            {
                "exit_test_id": 22 if index < 4 else 26,
                "exit_variant_index": index,
                "exit": rule,
            }
        )

    exit_rows: list[dict[str, str]] = []
    task_index = 0
    for entry_id, parent in entries:
        for exit_spec in exit_axis:
            child = dict(parent)
            child["upstream_candidate_id"] = entry_id
            child.update(exit_spec)
            child["horizon_sessions"] = int(exit_spec["exit"]["holding_sessions"])
            exit_rows.append(
                {
                    "candidate_id": canonical_candidate_id(child),
                    "dataset_hash": DATASET_HASH,
                    "policy_hash": POLICY_HASH,
                    "spec_json": json.dumps(child, sort_keys=True, separators=(",", ":")),
                    "status": "evaluated",
                    "task_index": str(task_index),
                }
            )
            task_index += 1
    _write_csv(root / "entry_layer_results.csv", entry_rows)
    _write_csv(root / "exit_layer_results.csv", exit_rows)
    return entry_rows, exit_rows


def _write_snapshot(path: Path, *, layer: str, input_artifact: Path) -> Path:
    return freeze_snapshot(
        layer=layer,
        input_artifact=input_artifact,
        output_path=path,
        policy_hash=POLICY_HASH,
        dataset_hash=DATASET_HASH,
        date_start="1995-01-01",
        date_end="2020-12-31",
        universe="current_universe_backfill",
        decisions=[
            {
                "candidate_id": f"{layer}_selection",
                "parameters": {"source": input_artifact.name},
                "validation_metrics": {"score": 1.0},
                "decision": "advance",
            }
        ],
    )


def test_prepares_exact_cartesian_manifest_and_preserves_source_rows(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    _, source_exit_rows = _source_artifact(source)

    summary = prepare_original_290_manifest(source, output, verify_frozen_source=False)

    with (output / COMBINATION_MANIFEST_NAME).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        manifest = list(csv.DictReader(handle))
    entry_specs = json.loads((output / ENTRY_SPECS_NAME).read_text(encoding="utf-8"))
    exit_specs = json.loads((output / EXIT_SPECS_NAME).read_text(encoding="utf-8"))
    assert summary["combination_count"] == 290
    assert len(manifest) == 290
    assert len(entry_specs) == 10
    assert len(exit_specs) == 29
    assert len({row["candidate_id"] for row in manifest}) == 290
    assert all(row["combination_id"] == row["candidate_id"] for row in manifest)
    assert len({row["entry_spec_id"] for row in manifest}) == 10
    assert len({row["exit_spec_id"] for row in manifest}) == 29
    assert len({(row["entry_spec_id"], row["exit_spec_id"]) for row in manifest}) == 290
    for source_row, manifest_row in zip(source_exit_rows, manifest, strict=True):
        assert all(manifest_row[key] == value for key, value in source_row.items())
    assert all(record["candidate_id"] == record["entry_spec_id"] for record in entry_specs)
    assert all(record["candidate_id"] == record["exit_spec_id"] for record in exit_specs)
    assert all(record["spec_json"] for record in entry_specs + exit_specs)
    assert all(record["dataset_hash"] == DATASET_HASH for record in entry_specs + exit_specs)
    assert all(record["policy_hash"] == POLICY_HASH for record in entry_specs + exit_specs)


def test_exit_ids_are_canonical_and_independent_of_mapping_order() -> None:
    left = {
        "exit_test_id": 22,
        "exit_variant_index": 1,
        "exit": {"kind": "breakout_failure", "holding_sessions": 252},
    }
    right = {
        "exit": {"holding_sessions": 252, "kind": "breakout_failure"},
        "exit_variant_index": 1,
        "exit_test_id": 22,
    }

    assert canonical_exit_spec_id(left) == canonical_exit_spec_id(right)


def test_breakout_failure_without_breakout_level_is_kept_but_not_applicable(
    tmp_path: Path,
):
    source = tmp_path / "source"
    output = tmp_path / "output"
    _source_artifact(source)

    prepare_original_290_manifest(source, output, verify_frozen_source=False)

    with (output / COMBINATION_MANIFEST_NAME).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    breakout_failure = [
        row
        for row in rows
        if json.loads(row["exit_spec_json"])["exit"]["kind"] == "breakout_failure"
    ]
    assert len(breakout_failure) == 40
    assert sum(row["corrected_track_applicability"] == "applicable" for row in breakout_failure) == 8
    assert sum(
        row["corrected_track_applicability"] == "not_applicable"
        for row in breakout_failure
    ) == 32
    assert all(
        row["corrected_track_reason"] == "missing_breakout_level"
        for row in breakout_failure
        if row["corrected_track_applicability"] == "not_applicable"
    )


def test_rejects_non_290_source_before_writing_outputs(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    _source_artifact(source)
    path = source / "exit_layer_results.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    _write_csv(path, rows[:-1])

    with pytest.raises(EventStudy290ManifestError, match="exactly 290"):
        prepare_original_290_manifest(source, output, verify_frozen_source=False)

    assert not output.exists()


def test_rejects_noncanonical_candidate_and_missing_hash(tmp_path: Path):
    source = tmp_path / "source"
    _source_artifact(source)
    path = source / "exit_layer_results.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["candidate_id"] = "stock_not_canonical"
    rows[1]["policy_hash"] = ""
    _write_csv(path, rows)

    with pytest.raises(EventStudy290ManifestError):
        prepare_original_290_manifest(
            source, tmp_path / "output", verify_frozen_source=False
        )


def test_source_snapshot_hash_is_the_exact_original_csv_hash(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    _source_artifact(source)
    expected = hashlib.sha256((source / "exit_layer_results.csv").read_bytes()).hexdigest()

    summary = prepare_original_290_manifest(source, output, verify_frozen_source=False)

    assert summary["source_snapshot_sha256"] == expected


def test_accepts_valid_snapshots_bound_to_their_source_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _source_artifact(source)
    entry_package = tmp_path / "entry-package"
    exit_package = tmp_path / "exit-package"
    entry_package.mkdir()
    exit_package.mkdir()
    entry_artifact = entry_package / "entries_results.csv"
    exit_artifact = exit_package / "exits_results.csv"
    entry_artifact.write_bytes((source / "entry_layer_results.csv").read_bytes())
    exit_artifact.write_bytes((source / "exit_layer_results.csv").read_bytes())
    entry_snapshot = _write_snapshot(
        entry_package / "entries_snapshot.json",
        layer="entries",
        input_artifact=entry_artifact,
    )
    exit_snapshot = _write_snapshot(
        exit_package / "exits_snapshot.json",
        layer="exits",
        input_artifact=exit_artifact,
    )

    summary = prepare_original_290_manifest(
        source,
        output,
        entry_snapshot=entry_snapshot,
        exit_snapshot=exit_snapshot,
        verify_frozen_source=False,
    )

    entry_payload = json.loads(entry_snapshot.read_text(encoding="utf-8"))
    exit_payload = json.loads(exit_snapshot.read_text(encoding="utf-8"))
    assert summary["entry_snapshot_sha256"] == entry_payload["snapshot_sha256"]
    assert summary["exit_snapshot_sha256"] == exit_payload["snapshot_sha256"]
    assert summary["source_snapshot_sha256"] == exit_payload["snapshot_sha256"]


def test_rejects_snapshot_payload_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_artifact(source)
    snapshot = _write_snapshot(
        source / "entries_snapshot.json",
        layer="entries",
        input_artifact=source / "entry_layer_results.csv",
    )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["decisions"][0]["parameters"]["source"] = "tampered.csv"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EventStudy290ManifestError, match="snapshot hash mismatch"):
        prepare_original_290_manifest(
            source,
            tmp_path / "output",
            entry_snapshot=snapshot,
            verify_frozen_source=False,
        )


def test_rejects_tampering_with_snapshot_linked_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_artifact(source)
    package = tmp_path / "entry-package"
    package.mkdir()
    artifact = package / "entries_results.csv"
    artifact.write_bytes((source / "entry_layer_results.csv").read_bytes())
    snapshot = _write_snapshot(
        package / "entries_snapshot.json",
        layer="entries",
        input_artifact=artifact,
    )
    artifact.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(
        EventStudy290ManifestError, match="snapshot input_artifact_sha256 mismatch"
    ):
        prepare_original_290_manifest(
            source,
            tmp_path / "output",
            entry_snapshot=snapshot,
            verify_frozen_source=False,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("layer", "exits", "snapshot layer mismatch"),
        ("dataset_hash", "3" * 64, "snapshot dataset_hash mismatch"),
        ("policy_hash", "4" * 64, "snapshot policy_hash mismatch"),
        ("input_artifact", "other.csv", "snapshot input_artifact is missing"),
        (
            "input_artifact_sha256",
            "5" * 64,
            "snapshot input_artifact_sha256 mismatch",
        ),
    ],
)
def test_rejects_resigned_snapshot_with_invalid_provenance(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    source = tmp_path / "source"
    _source_artifact(source)
    snapshot = _write_snapshot(
        source / "entries_snapshot.json",
        layer="entries",
        input_artifact=source / "entry_layer_results.csv",
    )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload[field] = value
    payload["snapshot_sha256"] = snapshot_payload_hash(payload)
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EventStudy290ManifestError, match=message):
        prepare_original_290_manifest(
            source,
            tmp_path / "output",
            entry_snapshot=snapshot,
            verify_frozen_source=False,
        )


def test_strict_mode_rejects_well_formed_but_noncanonical_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_artifact(source)
    with pytest.raises(EventStudy290ManifestError, match="frozen sha256 mismatch"):
        prepare_original_290_manifest(source, tmp_path / "strict-output")
