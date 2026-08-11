"""Train-only GitHub smoke for executable SP500 lanes F191-F200."""

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
    normalize_macro_release_panel,
    normalize_philadelphia_realtime_cycle_panel,
    normalize_realtime_macro_vintage_panel,
    normalize_sloos_credit_panel,
    normalize_spf_central_panel,
    normalize_spf_disagreement_panel,
    normalize_spf_output_error_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.realtime_survey_feature_engine import (
    evaluate_realtime_survey_family_batch,
    evaluate_realtime_survey_lane,
)


class RealtimeSurveyFeatureSmokeError(ValueError):
    """Raised when F191-F200 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(191, 201))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2003-01-01")
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_PHILLY_RT",
    "D_MACRO_PIT",
    "D_SPF",
    "D_SLOOS",
)
_REQUIRED_REALTIME_RESOURCES = (
    "real_output_quarterly_vintages",
    "real_gdi_quarterly_vintages",
    "nominal_consumption_quarterly_vintages",
    "nominal_disposable_income_quarterly_vintages",
    "saving_rate_quarterly_vintages",
    "real_output_monthly_vintages",
    "unemployment_quarterly_vintages",
)
_REQUIRED_MACRO_RESOURCES = (
    "philly_cpi_first_releases",
    "philly_core_cpi_first_releases",
    "philly_core_pce_first_releases",
    "philly_payroll_first_releases",
    "philly_industrial_production_first_releases",
    "philly_manufacturing_production_first_releases",
    "philly_capacity_utilization_first_releases",
    "philly_manufacturing_capacity_first_releases",
    "philly_housing_starts_first_releases",
    "philly_real_output_first_releases",
    "philly_real_consumption_first_releases",
    "philly_nonresidential_investment_first_releases",
    "philly_residential_investment_first_releases",
)
_REQUIRED_SPF_RESOURCES = ("spf_median_level", "spf_dispersion")
_REQUIRED_SLOOS_SERIES = (
    "SUBLPDCILS_N.Q",
    "SUBLPDCILD_N.Q",
    "SUBLPDCISS_N.Q",
    "SUBLPDCISD_N.Q",
    "SUBLPDCILTC_N.Q",
    "SUBLPDCILTL_N.Q",
    "SUBLPDCILTM_N.Q",
    "SUBLPDCILTQ_N.Q",
    "SUBLPDCILTS_N.Q",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_values(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    column: str,
    required: tuple[str, ...],
) -> None:
    if column not in frame:
        raise RealtimeSurveyFeatureSmokeError(
            f"PHYSICAL_SOURCE_COLUMN_MISSING:{dataset_id}:{column}"
        )
    present = set(frame[column].dropna().astype(str))
    for value in required:
        if value not in present:
            raise RealtimeSurveyFeatureSmokeError(
                f"PHYSICAL_SOURCE_VALUE_MISSING:{dataset_id}:{column}:{value}"
            )


def _first_available(panel: pd.DataFrame, column: str) -> str | None:
    values = pd.to_numeric(panel[column], errors="coerce")
    valid = values.notna()
    if not valid.any():
        return None
    return pd.to_datetime(panel.loc[valid, "available_at"]).min().date().isoformat()


def _repair_realtime_survey_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if parameter == "change_lag":
        configuration["normalization"] = "change"
    if lane_id == "F197" and parameter in {"normalization", "change_lag"}:
        configuration["statistic"] = "cpi_nowcast"
    if lane_id in {"F191", "F192", "F194", "F200"} and parameter == "window":
        configuration["normalization"] = "rolling_zscore"
    window_statistics = {
        "F193": "housing_investment_composite",
        "F195": "labor_composite",
        "F196": "production_capacity_composite",
        "F197": "macro_outlook_composite",
        "F198": "macro_disagreement",
        "F199": "rolling_absolute_error",
    }
    if lane_id in window_statistics and parameter == "window":
        configuration["statistic"] = window_statistics[lane_id]
    if lane_id == "F193" and parameter == "lag":
        configuration["statistic"] = "housing_starts_change"
    if lane_id == "F196" and parameter == "lag":
        configuration["statistic"] = "production_capacity_composite"
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
        raise RealtimeSurveyFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise RealtimeSurveyFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_realtime_survey_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F191-F200 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise RealtimeSurveyFeatureSmokeError("TRAIN_PARTITION_REQUIRED")

    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise RealtimeSurveyFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise RealtimeSurveyFeatureSmokeError(f"EMPTY_PHYSICAL_DATASET:{dataset}")
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise RealtimeSurveyFeatureSmokeError(f"NON_TRAIN_SOURCE_ROW:{dataset}")

    _require_values(
        raw["D_PHILLY_RT"],
        dataset_id="D_PHILLY_RT",
        column="resource_id",
        required=_REQUIRED_REALTIME_RESOURCES,
    )
    _require_values(
        raw["D_MACRO_PIT"],
        dataset_id="D_MACRO_PIT",
        column="resource_id",
        required=_REQUIRED_MACRO_RESOURCES,
    )
    _require_values(
        raw["D_SPF"],
        dataset_id="D_SPF",
        column="resource_id",
        required=_REQUIRED_SPF_RESOURCES,
    )
    _require_values(
        raw["D_SLOOS"],
        dataset_id="D_SLOOS",
        column="series_id",
        required=_REQUIRED_SLOOS_SERIES,
    )

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "realtime": normalize_realtime_macro_vintage_panel(
            raw["D_PHILLY_RT"], sessions=sessions
        ),
        "macro_release": normalize_macro_release_panel(
            raw["D_MACRO_PIT"], sessions=sessions
        ),
        "cycle": normalize_philadelphia_realtime_cycle_panel(
            raw["D_PHILLY_RT"], sessions=sessions
        ),
        "spf_central": normalize_spf_central_panel(raw["D_SPF"], sessions=sessions),
        "spf_disagreement": normalize_spf_disagreement_panel(
            raw["D_SPF"], sessions=sessions
        ),
        "spf_error": normalize_spf_output_error_panel(
            raw["D_SPF"], raw["D_MACRO_PIT"], sessions=sessions
        ),
        "sloos": normalize_sloos_credit_panel(raw["D_SLOOS"], sessions=sessions),
    }

    outputs = dict(evaluate_realtime_survey_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_realtime_survey_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_realtime_survey_configuration,
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

    report = {
        "schema_version": 1,
        "ready": bool(
            audit.ready and parameter_audit["ready"] and len(outputs) == 10
        ),
        "scope": "realtime_macro_survey_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": len(outputs),
        "physical_source_rows": {dataset: int(len(frame)) for dataset, frame in raw.items()},
        "source_sha256": source_hashes,
        "row_release_causality_valid": True,
        "philly_realtime_release_policy": "official_vintage_date_plus_next_spy_session",
        "macro_first_release_policy": "conservative_observation_lag_plus_next_spy_session",
        "spf_release_policy": "quarter_end_plus_next_spy_session",
        "sloos_release_policy": "quarter_end_plus_60_days_next_spy_session",
        "sloos_historical_revision_pit_exact": False,
        "f191_default": "output_growth_full_train_history",
        "f191_component_first_available_at": {
            column: _first_available(panels["realtime"], column)
            for column in ("output_growth", "gdi_growth")
        },
        "source_vintage_warning": (
            "The downloadable SLOOS history includes retrospective revisions; "
            "its sixty-day release guard prevents future rows but does not recreate old vintages."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_2003_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "realtime_survey_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F191_F200.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "RealtimeSurveyFeatureSmokeError",
    "build_realtime_survey_feature_smoke",
]
