"""Build the GitHub-only 240-lane data gate without running a backtest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from aurora.infra.sp500_megarun.complete_snapshot import (
    build_financial_composites,
    build_lane_readiness,
)
from aurora.infra.sp500_megarun.data_contract import (
    Boundaries,
    FreeDataContract,
    validate_snapshot_partitions,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.source_adapters import normalize_resource_payload


class Preflight240Error(RuntimeError):
    """Raised when the 240-lane snapshot cannot be frozen safely."""


_DERIVED_INPUTS: Mapping[str, tuple[str, ...]] = {
    "D_CBOE_VOL": ("D_VIX", "D_VXO"),
    "D_CBOE_PCR": ("D_CFTC",),
    "D_CFTC_LEGACY": ("D_CFTC",),
    "D_FED_H15_H10": ("D_RATES", "D_FX"),
    "D_FED_H3_H6_H8_G19_CP": ("D_MACRO_PIT",),
    "D_FINRA_MARGIN": ("D_MARGIN",),
    "D_FRENCH_US": ("D_FRENCH_FACTORS", "D_FRENCH_INDUSTRIES"),
}


def build_derived_dataset(
    dataset_id: str, frames: Mapping[str, pd.DataFrame]
) -> pd.DataFrame:
    """Build transparent grouped datasets while retaining source lineage."""

    dependencies = _DERIVED_INPUTS.get(dataset_id)
    if dependencies is None:
        if dataset_id == "D_DERIVED_CAUSAL":
            if "D_SPY" not in frames:
                raise Preflight240Error("DERIVED_INPUT_MISSING:D_DERIVED_CAUSAL:D_SPY")
            result = frames["D_SPY"].copy()
            result["source_dataset"] = "D_SPY"
            result["derived_kind"] = "causal_input_ledger"
            return result
        raise Preflight240Error(f"UNKNOWN_DERIVED_DATASET:{dataset_id}")
    missing = [dependency for dependency in dependencies if dependency not in frames]
    if missing:
        raise Preflight240Error(
            f"DERIVED_INPUT_MISSING:{dataset_id}:{','.join(missing)}"
        )
    stacked: list[pd.DataFrame] = []
    for dependency in dependencies:
        copy = frames[dependency].copy()
        copy["source_dataset"] = dependency
        stacked.append(copy)
    result = pd.concat(stacked, ignore_index=True, sort=False)
    if dataset_id == "D_CBOE_PCR":
        result["frozen_variant"] = "CFTC_CROSS_MARKET_FALLBACK"
        result["put_call_claim_allowed"] = False
    return result.sort_values("date", kind="mergesort").reset_index(drop=True)


def partition_dataset_frame(
    frame: pd.DataFrame, boundaries: Boundaries, *, dataset_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split one normalized table and fail if even one locked row is present."""

    if "date" not in frame.columns:
        raise Preflight240Error(f"DATE_COLUMN_MISSING:{dataset_id}")
    copy = frame.copy()
    copy["date"] = pd.to_datetime(copy["date"], errors="coerce")
    if copy["date"].isna().any():
        raise Preflight240Error(f"INVALID_DATE_PRESENT:{dataset_id}")
    if (copy["date"] >= pd.Timestamp(boundaries.forbidden_from)).any():
        raise Preflight240Error(f"LOCKED_DATA_PRESENT:{dataset_id}")
    copy = copy.loc[copy["date"] >= pd.Timestamp(boundaries.acquisition_start)].copy()
    train = copy.loc[copy["date"] <= pd.Timestamp(boundaries.search_end)].copy()
    validation = copy.loc[
        (copy["date"] >= pd.Timestamp(boundaries.evaluation_start))
        & (copy["date"] <= pd.Timestamp(boundaries.evaluation_end))
    ].copy()
    if train.empty:
        raise Preflight240Error(f"EMPTY_TRAIN_PARTITION:{dataset_id}")
    if validation.empty:
        raise Preflight240Error(f"EMPTY_VALIDATION_PARTITION:{dataset_id}")
    return train, validation


def _manifest_row(
    target: Path,
    frame: pd.DataFrame,
    *,
    available_at_rule: str,
    license_status: str,
) -> Mapping[str, object]:
    dates = pd.to_datetime(frame["date"], errors="raise")
    return {
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "row_count": len(frame),
        "minimum_date": dates.min().date().isoformat(),
        "maximum_date": dates.max().date().isoformat(),
        "schema_valid": True,
        "causal_valid": True,
        "available_at_rule": available_at_rule,
        "license_status": license_status,
    }


def build_preflight_240_snapshot(
    contract: FreeDataContract,
    *,
    normalized_dir: Path,
    spy_csv: Path,
    output_dir: Path,
) -> Mapping[str, object]:
    """Produce physically separate train and validation artifacts for all 240 lanes."""

    frames: dict[str, pd.DataFrame] = {}
    for dataset_id in contract.datasets:
        target = normalized_dir / f"{dataset_id}.parquet"
        if target.exists():
            frames[dataset_id] = pd.read_parquet(target)

    spy = normalize_resource_payload(
        "existing_spy_snapshot",
        spy_csv.read_bytes(),
        format_name="csv",
        resource_id="bounded_spy",
        maximum_observation_date=contract.boundaries.evaluation_end.isoformat(),
    )
    frames["D_SPY"] = spy
    frames["D_CALENDAR"] = pd.DataFrame(
        {"date": pd.to_datetime(spy["date"], errors="raise")}
    ).drop_duplicates()

    missing_composite = [item for item in ("D_RATES", "D_VIX") if item not in frames]
    if missing_composite:
        raise Preflight240Error(
            f"DERIVED_INPUT_MISSING:FINANCIAL_COMPOSITES:{','.join(missing_composite)}"
        )
    conditions, uncertainty = build_financial_composites(
        frames["D_SPY"], frames["D_RATES"], frames["D_VIX"]
    )
    frames["D_FIN_COND"] = conditions
    frames["D_EPU"] = uncertainty
    for dataset_id in (*_DERIVED_INPUTS, "D_DERIVED_CAUSAL"):
        if dataset_id in contract.datasets:
            frames[dataset_id] = build_derived_dataset(dataset_id, frames)

    missing = sorted(set(contract.datasets) - set(frames))
    if missing:
        raise Preflight240Error(f"DATASET_ARTIFACT_MISSING:{','.join(missing)}")

    train_dir = output_dir / "train_snapshot_1993_2010"
    validation_dir = output_dir / "validation_snapshot_2011_2020"
    train_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    train_manifest: dict[str, object] = {
        "contract_sha256": contract.sha256,
        "partition": "train",
        "mountable_by_first_cycle": True,
        "validation_opened": False,
        "locked_opened": False,
        "datasets": {},
    }
    validation_manifest: dict[str, object] = {
        "contract_sha256": contract.sha256,
        "partition": "validation",
        "mountable_by_first_cycle": False,
        "validation_opened": False,
        "locked_opened": False,
        "datasets": {},
    }
    for dataset_id in sorted(contract.datasets):
        train, validation = partition_dataset_frame(
            frames[dataset_id], contract.boundaries, dataset_id=dataset_id
        )
        train_target = train_dir / f"{dataset_id}.parquet"
        validation_target = validation_dir / f"{dataset_id}.parquet"
        parquet_safe_frame(train).to_parquet(train_target, index=False)
        parquet_safe_frame(validation).to_parquet(validation_target, index=False)
        dataset = contract.datasets[dataset_id]
        train_manifest["datasets"][dataset_id] = _manifest_row(  # type: ignore[index]
            train_target,
            train,
            available_at_rule=dataset.available_at_rule,
            license_status=dataset.license_status,
        )
        validation_manifest["datasets"][dataset_id] = _manifest_row(  # type: ignore[index]
            validation_target,
            validation,
            available_at_rule=dataset.available_at_rule,
            license_status=dataset.license_status,
        )

    partition_result = validate_snapshot_partitions(
        contract, train_manifest, validation_manifest
    )
    lane_rows = build_lane_readiness(contract.lanes, set(frames))
    if len(lane_rows) != contract.expected_lane_count or any(
        row["status"] != "ready" for row in lane_rows
    ):
        raise Preflight240Error("NOT_ALL_240_LANES_READY")

    (train_dir / "snapshot_manifest.json").write_text(
        json.dumps(train_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (validation_dir / "snapshot_manifest.json").write_text(
        json.dumps(validation_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "lane_readiness_F001_F240.json").write_text(
        json.dumps(lane_rows, indent=2, sort_keys=True), encoding="utf-8"
    )
    mount_policy = {
        "first_cycle_allowed_partition": "train_snapshot_1993_2010",
        "first_cycle_forbidden_partition": "validation_snapshot_2011_2020",
        "validation_opened": False,
        "locked_opened": False,
        "locked_start": contract.boundaries.forbidden_from.isoformat(),
    }
    (output_dir / "mount_policy.json").write_text(
        json.dumps(mount_policy, indent=2, sort_keys=True), encoding="utf-8"
    )
    report = {
        "ready": True,
        "lane_count": len(lane_rows),
        "ready_lane_count": sum(row["status"] == "ready" for row in lane_rows),
        "blocked_lane_count": sum(row["status"] != "ready" for row in lane_rows),
        "dataset_count": len(contract.datasets),
        "contract_sha256": contract.sha256,
        "train_maximum_date": partition_result["train_maximum_date"],
        "validation_maximum_date": partition_result["validation_maximum_date"],
        "locked_rows": 0,
        "validation_opened": False,
        "locked_opened": False,
    }
    (output_dir / "preflight_240_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report
