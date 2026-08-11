"""Train-only GitHub smoke for executable SP500 lanes F231-F240."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
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
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.public_context_feature_engine import (
    evaluate_public_context_family_batch,
    evaluate_public_context_lane,
)


class PublicContextFeatureSmokeError(ValueError):
    """Raised when F231-F240 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(231, 241))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("1998-01-01")
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


def _repair_public_context_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    window_statistics = {
        "F232": "announcement_density",
        "F233": "publication_density",
        "F234": "divergence_zscore",
        "F235": "precipitation_anomaly",
        "F236": "temperature_anomaly",
        "F240": "rolling_event_density",
    }
    if lane_id in window_statistics and parameter == "window":
        configuration["statistic"] = window_statistics[lane_id]
        configuration["normalization"] = "raw"
    elif parameter == "window":
        configuration["normalization"] = "rolling_zscore"
    lag_statistics = {
        "F231": "breadth_change",
        "F233": "mix_change",
        "F234": "divergence_change",
    }
    if lane_id in lag_statistics and parameter == "change_lag":
        configuration["statistic"] = lag_statistics[lane_id]
        configuration["normalization"] = "raw"
    elif parameter == "change_lag":
        generic_change_statistics = {
            "F232": "announced_offering",
            "F235": "precipitation",
            "F236": "temperature",
            "F237": "daylight_minutes",
            "F238": "sessions_until_expiry",
            "F239": "days_to_general_election",
            "F240": "total_event_count",
        }
        configuration["statistic"] = generic_change_statistics[lane_id]
        configuration["normalization"] = "change"
    if lane_id == "F232" and parameter == "normalization":
        configuration["statistic"] = "announced_offering"
    return configuration


def _parameter_audit_inputs(
    market: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    market_dates = pd.to_datetime(market["date"], errors="raise")
    audit_market = market.loc[
        market_dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
    ].reset_index(drop=True)
    if not (pd.DatetimeIndex(audit_market["date"]).year == 2010).any():
        raise PublicContextFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise PublicContextFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


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
    data_contract = load_and_validate_contract(
        _REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
    )
    feature_contract = load_and_validate_feature_contract(
        _REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json",
        data_contract,
    )
    audit_market, audit_panels = _parameter_audit_inputs(market, panels)
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_public_context_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_public_context_configuration,
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
    required_years = set(range(_SEARCH_START.year, _TRAIN_END.year + 1))
    full_yearly_coverage = all(
        set(item.yearly_non_null_fraction) == required_years
        and all(
            fraction == 1.0
            for fraction in item.yearly_non_null_fraction.values()
        )
        for item in audit.coverage
    )
    ready = bool(
        audit.ready
        and parameter_audit["ready"]
        and len(outputs) == len(_LANES)
        and not exact_duplicates
        and not near_duplicates
        and full_yearly_coverage
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
        "full_yearly_coverage": full_yearly_coverage,
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_1998_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "public_context_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F231_F240.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "PublicContextFeatureSmokeError",
    "build_public_context_feature_smoke",
]
