"""Build the bounded SP500 mega-run snapshot and the F001-F120 readiness matrix."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import (
    FreeDataContract,
    LaneContract,
    validate_snapshot_manifest,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.source_adapters import normalize_resource_payload


class CompleteSnapshotError(RuntimeError):
    """Raised when one of the 120 lanes is not runnable from the snapshot."""


def _causal_zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").ffill()
    mean = values.expanding(min_periods=1).mean()
    deviation = values.expanding(min_periods=2).std().replace(0.0, pd.NA)
    return ((values - mean) / deviation).fillna(0.0).astype(float)


def _daily_numeric_level(frame: pd.DataFrame, *, preferred: str) -> pd.DataFrame:
    copy = frame.copy()
    copy["date"] = pd.to_datetime(copy["date"], errors="coerce")
    numeric_columns = [
        column
        for column in copy.columns
        if column != "date" and pd.api.types.is_numeric_dtype(copy[column])
    ]
    preferred_columns = [
        column for column in numeric_columns if preferred in str(column).casefold()
    ]
    selected = preferred_columns or numeric_columns
    if not selected:
        converted = copy.drop(columns=["date"]).apply(pd.to_numeric, errors="coerce")
        selected = list(converted.columns)
        copy[selected] = converted
    if not selected:
        raise CompleteSnapshotError("NO_NUMERIC_LEVEL_COLUMNS")
    copy["level"] = copy[selected].median(axis=1, skipna=True)
    return (
        copy.loc[copy["date"].notna() & copy["level"].notna(), ["date", "level"]]
        .groupby("date", as_index=False)["level"]
        .median()
        .sort_values("date")
    )


def build_financial_composites(
    spy: pd.DataFrame, rates: pd.DataFrame, vix: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create causal, expanding-only financial-condition and uncertainty scores."""

    sessions = pd.DataFrame(
        {"date": pd.to_datetime(spy["date"], errors="coerce")}
    ).dropna().drop_duplicates().sort_values("date")
    rate_level = _daily_numeric_level(rates, preferred="value").rename(
        columns={"level": "rate_level"}
    )
    vol_level = _daily_numeric_level(vix, preferred="close").rename(
        columns={"level": "volatility_level"}
    )
    joined = pd.merge_asof(sessions, rate_level, on="date", direction="backward")
    joined = pd.merge_asof(joined, vol_level, on="date", direction="backward")
    joined[["rate_level", "volatility_level"]] = joined[
        ["rate_level", "volatility_level"]
    ].ffill()
    joined = joined.dropna(subset=["rate_level", "volatility_level"]).reset_index(
        drop=True
    )
    rate_z = _causal_zscore(joined["rate_level"])
    vol_z = _causal_zscore(joined["volatility_level"])
    rate_shock_z = _causal_zscore(joined["rate_level"].diff().abs().fillna(0.0))
    conditions = pd.DataFrame(
        {
            "date": joined["date"],
            "financial_conditions_score": (rate_z + vol_z) / 2.0,
            "rate_level": joined["rate_level"],
            "volatility_level": joined["volatility_level"],
        }
    )
    uncertainty = pd.DataFrame(
        {
            "date": joined["date"],
            "uncertainty_score": (vol_z + rate_shock_z) / 2.0,
            "volatility_level": joined["volatility_level"],
            "absolute_rate_change": joined["rate_level"].diff().abs().fillna(0.0),
        }
    )
    return conditions, uncertainty


def build_lane_readiness(
    lanes: Sequence[LaneContract], available_datasets: set[str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for lane in lanes:
        missing = sorted(set(lane.required_datasets) - available_datasets)
        rows.append(
            {
                "lane_id": lane.lane_id,
                "status": "ready" if not missing else "blocked",
                "required_datasets": list(lane.required_datasets),
                "missing_datasets": missing,
                "fidelity": lane.fidelity,
                "replacement_note": lane.replacement_note,
            }
        )
    return rows


def _write_parquet(frame: pd.DataFrame, target: Path, *, maximum_date: pd.Timestamp) -> None:
    copy = frame.copy()
    copy["date"] = pd.to_datetime(copy["date"], errors="coerce")
    copy = copy.loc[copy["date"].notna() & (copy["date"] <= maximum_date)].copy()
    if copy.empty:
        raise CompleteSnapshotError(f"EMPTY_BOUNDED_DATASET:{target.stem}")
    parquet_safe_frame(copy).to_parquet(target, index=False)


def build_complete_snapshot(
    contract: FreeDataContract,
    *,
    normalized_dir: Path,
    spy_csv: Path,
    output_dir: Path,
) -> Mapping[str, object]:
    """Add SPY/derived inputs and prove every lane resolves to bounded data."""

    normalized_dir.mkdir(parents=True, exist_ok=True)
    ceiling = pd.Timestamp(contract.boundaries.evaluation_end)
    spy = normalize_resource_payload(
        "existing_spy_snapshot",
        spy_csv.read_bytes(),
        format_name="csv",
        resource_id="stooq_spy",
        maximum_observation_date=contract.boundaries.evaluation_end.isoformat(),
    )
    _write_parquet(spy, normalized_dir / "D_SPY.parquet", maximum_date=ceiling)
    calendar = pd.DataFrame({"date": pd.to_datetime(spy["date"])}).drop_duplicates()
    _write_parquet(calendar, normalized_dir / "D_CALENDAR.parquet", maximum_date=ceiling)
    rates = pd.read_parquet(normalized_dir / "D_RATES.parquet")
    vix = pd.read_parquet(normalized_dir / "D_VIX.parquet")
    conditions, uncertainty = build_financial_composites(spy, rates, vix)
    _write_parquet(conditions, normalized_dir / "D_FIN_COND.parquet", maximum_date=ceiling)
    _write_parquet(uncertainty, normalized_dir / "D_EPU.parquet", maximum_date=ceiling)

    manifest: dict[str, object] = {
        "contract_sha256": contract.sha256,
        "validation_opened": False,
        "locked_opened": False,
        "datasets": {},
    }
    manifest_datasets: dict[str, object] = manifest["datasets"]  # type: ignore[assignment]
    for dataset_id in sorted(contract.datasets):
        target = normalized_dir / f"{dataset_id}.parquet"
        if not target.exists():
            raise CompleteSnapshotError(f"DATASET_ARTIFACT_MISSING:{dataset_id}")
        frame = pd.read_parquet(target)
        dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        if frame.empty or dates.empty:
            raise CompleteSnapshotError(f"DATASET_ARTIFACT_EMPTY:{dataset_id}")
        maximum = dates.max()
        manifest_datasets[dataset_id] = {
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "row_count": len(frame),
            "minimum_date": dates.min().date().isoformat(),
            "maximum_date": maximum.date().isoformat(),
            "schema_valid": "date" in frame.columns,
            "causal_valid": maximum <= ceiling,
        }

    contract_payload = json.loads(contract.path.read_text(encoding="utf-8"))
    validate_snapshot_manifest(
        contract_payload,
        manifest,
        expected_contract_path=contract.path,
    )
    lane_rows = build_lane_readiness(contract.lanes, set(manifest_datasets))
    if len(lane_rows) != 120 or any(row["status"] != "ready" for row in lane_rows):
        raise CompleteSnapshotError("NOT_ALL_120_LANES_READY")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "lane_readiness_F001_F120.json").write_text(
        json.dumps(lane_rows, indent=2, sort_keys=True), encoding="utf-8"
    )
    report = {
        "ready": True,
        "dataset_count": len(manifest_datasets),
        "lane_count": len(lane_rows),
        "exact_lane_count": sum(row["fidelity"] == "exact" for row in lane_rows),
        "proxy_lane_count": sum(row["fidelity"] == "proxy" for row in lane_rows),
        "redesigned_lane_count": sum(row["fidelity"] == "redesigned" for row in lane_rows),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output_dir / "complete_snapshot_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report
