"""Train-only GitHub smoke for executable SP500 lanes F231-F240."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_calendar_state_panel,
    normalize_fomc_document_mix_panel,
    normalize_noaa_ny_weather_panel,
    normalize_philadelphia_publication_panel,
    normalize_spy_decision_panel,
    normalize_tic_foreign_flow_panel,
    normalize_treasury_auction_announcement_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.public_context_feature_engine import (
    evaluate_public_context_family_batch,
)


class PublicContextFeatureSmokeError(ValueError):
    """Raised when F231-F240 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(231, 241))
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_PHILLY_RT",
    "D_TREASURY_AUCTIONS",
    "D_FOMC_PUBLIC",
    "D_TIC",
    "D_NOAA_NY",
)
_FOMC_KINDS = ("meeting", "statement", "minutes_release")
_TIC_RESOURCES = ("tic_treasury_sector", "tic_equity_sector")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    required: tuple[str, ...],
) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise PublicContextFeatureSmokeError(
            f"PHYSICAL_SOURCE_COLUMN_MISSING:{dataset_id}:{','.join(missing)}"
        )


def _require_values(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    column: str,
    required: tuple[str, ...],
) -> None:
    _require_columns(frame, dataset_id=dataset_id, required=(column,))
    present = set(frame[column].dropna().astype(str))
    missing = [value for value in required if value not in present]
    if missing:
        raise PublicContextFeatureSmokeError(
            f"PHYSICAL_SOURCE_VALUE_MISSING:{dataset_id}:{column}:{','.join(missing)}"
        )


def _reject_unfrozen_weather_fields(frame: pd.DataFrame) -> None:
    forbidden = sorted(
        str(column)
        for column in frame.columns
        if any(token in str(column).lower() for token in ("sun", "cloud"))
    )
    if forbidden:
        raise PublicContextFeatureSmokeError(
            f"UNFROZEN_NOAA_SUN_CLOUD_FIELD:{','.join(forbidden)}"
        )


def _first_available(panel: pd.DataFrame) -> str | None:
    if panel.empty:
        return None
    return pd.to_datetime(panel["available_at"]).min().date().isoformat()


def build_public_context_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F231-F240 without mounting later partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise PublicContextFeatureSmokeError("TRAIN_PARTITION_REQUIRED")

    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise PublicContextFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        frame = pd.read_parquet(target)
        raw[dataset] = frame
        source_hashes[dataset] = _sha256(target)
        if "date" not in frame or frame.empty:
            raise PublicContextFeatureSmokeError(f"EMPTY_PHYSICAL_DATASET:{dataset}")
        dates = pd.to_datetime(frame["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise PublicContextFeatureSmokeError(f"NON_TRAIN_SOURCE_ROW:{dataset}")

    _require_columns(
        raw["D_PHILLY_RT"],
        dataset_id="D_PHILLY_RT",
        required=("observation_date", "vintage_label", "resource_id"),
    )
    _require_columns(
        raw["D_TREASURY_AUCTIONS"],
        dataset_id="D_TREASURY_AUCTIONS",
        required=(
            "announcemt_date",
            "auction_date",
            "issue_date",
            "maturity_date",
            "security_type",
            "offering_amt",
        ),
    )
    _require_values(
        raw["D_FOMC_PUBLIC"],
        dataset_id="D_FOMC_PUBLIC",
        column="document_kind",
        required=_FOMC_KINDS,
    )
    _require_values(
        raw["D_TIC"],
        dataset_id="D_TIC",
        column="resource_id",
        required=_TIC_RESOURCES,
    )
    _require_columns(
        raw["D_NOAA_NY"],
        dataset_id="D_NOAA_NY",
        required=(
            "TEMP",
            "DEWP",
            "SLP",
            "VISIB",
            "WDSP",
            "MXSPD",
            "GUST",
            "MAX",
            "MIN",
            "PRCP",
            "SNDP",
            "FRSHTT",
        ),
    )
    _reject_unfrozen_weather_fields(raw["D_NOAA_NY"])

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "philly": normalize_philadelphia_publication_panel(
            raw["D_PHILLY_RT"], sessions=sessions
        ),
        "announcements": normalize_treasury_auction_announcement_panel(
            raw["D_TREASURY_AUCTIONS"], sessions=sessions
        ),
        "fomc_documents": normalize_fomc_document_mix_panel(
            raw["D_FOMC_PUBLIC"], sessions=sessions
        ),
        "tic": normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions),
        "weather": normalize_noaa_ny_weather_panel(
            raw["D_NOAA_NY"], sessions=sessions
        ),
        "calendar": normalize_calendar_state_panel(sessions=sessions),
    }
    outputs = dict(evaluate_public_context_family_batch(market, panels))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )

    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum = pd.Timestamp.min
    for lane, output in outputs.items():
        target = root / "features" / f"{lane}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum = max(maximum, pd.to_datetime(output["date"]).max())
        artifacts[lane] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": len(output),
            "non_null_values": int(output["value"].notna().sum()),
        }

    exact_duplicates = [list(group) for group in audit.exact_duplicate_groups]
    near_duplicates = [list(pair) for pair in audit.near_duplicate_pairs]
    ready = bool(
        audit.ready
        and len(outputs) == len(_LANES)
        and not exact_duplicates
        and not near_duplicates
    )
    report = {
        "schema_version": 1,
        "ready": ready,
        "scope": "public_context_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": len(outputs),
        "physical_source_rows": {
            dataset: int(len(frame)) for dataset, frame in raw.items()
        },
        "source_sha256": source_hashes,
        "row_release_causality_valid": True,
        "philadelphia_publication_policy": "official_vintage_date_plus_next_spy_session",
        "treasury_announcement_policy": "announcement_date_plus_next_spy_session",
        "fomc_document_policy": "public_document_date_plus_next_spy_session",
        "fomc_minutes_document_date_used": False,
        "tic_release_policy": "second_following_month_tenth_spy_session",
        "tic_historical_revision_pit_exact": False,
        "noaa_release_policy": "observation_plus_two_calendar_days",
        "sec_source_used": False,
        "sunshine_or_cloud_claimed": False,
        "first_available_at": {
            name: _first_available(panel) for name, panel in panels.items()
        },
        "source_warning": (
            "No SEC source is mounted. NOAA GSOD provides precipitation, visibility, "
            "temperature, wind and event flags but not sunshine or cloud history. "
            "Downloadable TIC history does not recreate historical revisions."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": exact_duplicates,
        "near_duplicate_pairs": near_duplicates,
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "public_context_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "PublicContextFeatureSmokeError",
    "build_public_context_feature_smoke",
]
