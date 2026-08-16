"""Fail-closed one-shot validation support for the frozen SP500 selection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


VALIDATION_ACK = "OPEN_SP500_MEGARUN_VALIDATION_2011_2020_SELECTED_12_ONCE"
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")


class SelectedValidationError(ValueError):
    """Raised when selected-strategy validation cannot remain fail-closed."""


@dataclass(frozen=True)
class ValidationSnapshotReceipt:
    snapshot_dir: Path
    manifest_sha256: str
    spy_sha256: str
    dataset_count: int
    maximum_date: str
    validation_opened: bool = True
    locked_opened: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SelectedValidationError(f"SNAPSHOT_FILE_READ_FAILED:{path.name}") from exc
    return digest.hexdigest()


def _load_manifest(path: Path, *, expected_partition: str) -> Mapping[str, Any]:
    target = path / "snapshot_manifest.json"
    try:
        manifest = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedValidationError(f"SNAPSHOT_MANIFEST_INVALID:{expected_partition}") from exc
    if manifest.get("partition") != expected_partition:
        raise SelectedValidationError(f"SNAPSHOT_PARTITION_INVALID:{expected_partition}")
    if manifest.get("locked_opened") is not False:
        raise SelectedValidationError("SNAPSHOT_LOCKED_ALREADY_OPEN")
    if manifest.get("validation_opened") is not False:
        raise SelectedValidationError("SNAPSHOT_VALIDATION_ALREADY_OPEN")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, Mapping) or not datasets:
        raise SelectedValidationError("SNAPSHOT_DATASETS_INVALID")
    return manifest


def _verified_frame(root: Path, dataset_id: str, row: Mapping[str, Any]) -> pd.DataFrame:
    target = root / f"{dataset_id}.parquet"
    if not target.is_file() or _sha256_file(target) != row.get("sha256"):
        raise SelectedValidationError(f"SNAPSHOT_DATASET_HASH_MISMATCH:{dataset_id}")
    frame = pd.read_parquet(target)
    if "date" not in frame or frame.empty:
        raise SelectedValidationError(f"SNAPSHOT_DATASET_EMPTY:{dataset_id}")
    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise SelectedValidationError(f"SNAPSHOT_DATASET_DATE_INVALID:{dataset_id}")
    result = frame.copy()
    result["date"] = dates
    return result


def build_authorized_validation_snapshot(
    train_dir: Path,
    validation_dir: Path,
    output_dir: Path,
    *,
    authorization: str,
) -> ValidationSnapshotReceipt:
    """Verify and combine train plus validation solely for signal warm-up."""

    if authorization != VALIDATION_ACK:
        raise SelectedValidationError("VALIDATION_AUTHORIZATION_INVALID")
    train_root = Path(train_dir).resolve()
    validation_root = Path(validation_dir).resolve()
    output_root = Path(output_dir).resolve()
    if train_root.name != "train_snapshot_1993_2010":
        raise SelectedValidationError("TRAIN_SNAPSHOT_NAME_INVALID")
    if validation_root.name != "validation_snapshot_2011_2020":
        raise SelectedValidationError("VALIDATION_SNAPSHOT_NAME_INVALID")
    if output_root.name != "authorized_validation_snapshot_1993_2020":
        raise SelectedValidationError("AUTHORIZED_SNAPSHOT_NAME_INVALID")
    if output_root.exists():
        raise SelectedValidationError("AUTHORIZED_SNAPSHOT_ALREADY_EXISTS")

    train_manifest = _load_manifest(train_root, expected_partition="train")
    validation_manifest = _load_manifest(
        validation_root,
        expected_partition="validation",
    )
    if train_manifest.get("contract_sha256") != validation_manifest.get(
        "contract_sha256"
    ):
        raise SelectedValidationError("SNAPSHOT_CONTRACT_MISMATCH")
    train_rows = train_manifest["datasets"]
    validation_rows = validation_manifest["datasets"]
    if set(train_rows) != set(validation_rows):
        raise SelectedValidationError("SNAPSHOT_DATASET_SET_MISMATCH")

    combined_frames: dict[str, pd.DataFrame] = {}
    for dataset_id in sorted(train_rows):
        train = _verified_frame(train_root, dataset_id, train_rows[dataset_id])
        validation = _verified_frame(
            validation_root,
            dataset_id,
            validation_rows[dataset_id],
        )
        train_dates = pd.DatetimeIndex(train["date"])
        validation_dates = pd.DatetimeIndex(validation["date"])
        if train_dates.max() > TRAIN_END:
            raise SelectedValidationError(f"TRAIN_BOUNDARY_VIOLATION:{dataset_id}")
        if validation_dates.min() < VALIDATION_START:
            raise SelectedValidationError(
                f"VALIDATION_START_BOUNDARY_VIOLATION:{dataset_id}"
            )
        if validation_dates.max() >= LOCKED_START:
            raise SelectedValidationError(f"LOCKED_BOUNDARY_VIOLATION:{dataset_id}")
        combined_frames[dataset_id] = pd.concat(
            [train, validation],
            ignore_index=True,
        ).sort_values("date", kind="mergesort", ignore_index=True)

    output_root.mkdir(parents=True)
    output_rows: dict[str, Mapping[str, Any]] = {}
    for dataset_id, frame in combined_frames.items():
        target = output_root / f"{dataset_id}.parquet"
        frame.to_parquet(target, index=False)
        dates = pd.DatetimeIndex(frame["date"])
        output_rows[dataset_id] = {
            **dict(train_rows[dataset_id]),
            "sha256": _sha256_file(target),
            "row_count": len(frame),
            "minimum_date": dates.min().date().isoformat(),
            "maximum_date": dates.max().date().isoformat(),
        }
    manifest = {
        "schema_version": 1,
        "contract_sha256": train_manifest["contract_sha256"],
        "partition": "authorized_validation",
        "mountable_by_first_cycle": False,
        "validation_start": VALIDATION_START.date().isoformat(),
        "validation_end": VALIDATION_END.date().isoformat(),
        "locked_start": LOCKED_START.date().isoformat(),
        "validation_opened": True,
        "locked_opened": False,
        "datasets": output_rows,
    }
    manifest_path = output_root / "snapshot_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ValidationSnapshotReceipt(
        snapshot_dir=output_root,
        manifest_sha256=_sha256_file(manifest_path),
        spy_sha256=str(output_rows["D_SPY"]["sha256"]),
        dataset_count=len(output_rows),
        maximum_date=VALIDATION_END.date().isoformat(),
    )


__all__ = [
    "LOCKED_START",
    "TRAIN_END",
    "VALIDATION_ACK",
    "VALIDATION_END",
    "VALIDATION_START",
    "SelectedValidationError",
    "ValidationSnapshotReceipt",
    "build_authorized_validation_snapshot",
]
