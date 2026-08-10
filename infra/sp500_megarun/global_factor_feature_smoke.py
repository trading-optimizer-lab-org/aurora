"""Train-only GitHub smoke for executable SP500 lanes F161-F170."""

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
    normalize_french_factor_panel,
    normalize_french_global_factor_panels,
    normalize_french_industry_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.global_factor_feature_engine import (
    evaluate_global_factor_family_batch,
    evaluate_global_factor_lane,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class GlobalFactorFeatureSmokeError(ValueError):
    """Raised when the F161-F170 smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(161, 171))
_DATASETS = ("D_SPY", "D_CALENDAR", "D_FRENCH_US", "D_FRENCH_GLOBAL")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2004-01-01")
_US_RESOURCES = ("ff3_daily", "industry_48_daily")
_GLOBAL_RESOURCES = (
    "developed_five_factors",
    "developed_momentum",
    "developed_ex_us",
    "europe",
    "japan",
    "asia_pacific_ex_japan",
    "developed_ex_us_momentum",
    "europe_momentum",
    "japan_momentum",
    "asia_pacific_ex_japan_momentum",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resource_counts(
    frame: pd.DataFrame,
    *,
    dataset: str,
) -> dict[str, int]:
    if "resource_id" not in frame:
        raise GlobalFactorFeatureSmokeError(
            f"FRENCH_RESOURCE_ID_MISSING:{dataset}"
        )
    return {
        str(resource_id): int(count)
        for resource_id, count in frame["resource_id"]
        .astype(str)
        .value_counts()
        .items()
    }


def _repair_global_factor_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id in {"F161", "F170"} and parameter == "change_lag":
        configuration["mode"] = "change"
    if lane_id == "F165" and parameter == "short_window":
        configuration["statistic"] = "regime_change"
        configuration["window"] = 126
    if lane_id == "F169" and parameter == "selection_fraction":
        configuration["universe"] = (
            "developed_ex_us_plus_regions"
            if float(configuration["selection_fraction"]) == 0.33
            else "all_available"
        )
    if lane_id == "F169" and parameter == "aggregation":
        configuration["selection_fraction"] = 0.5
        configuration["universe"] = "all_available"
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
        raise GlobalFactorFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise GlobalFactorFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_global_factor_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F161-F170 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise GlobalFactorFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise GlobalFactorFeatureSmokeError(
                f"TRAIN_DATASET_MISSING:{dataset}"
            )
        raw[dataset] = pd.read_parquet(target)
    if "date" not in raw["D_CALENDAR"] or raw["D_CALENDAR"].empty:
        raise GlobalFactorFeatureSmokeError("EMPTY_PHYSICAL_CALENDAR")

    us_counts = _resource_counts(raw["D_FRENCH_US"], dataset="D_FRENCH_US")
    global_counts = _resource_counts(
        raw["D_FRENCH_GLOBAL"], dataset="D_FRENCH_GLOBAL"
    )
    for resource in _US_RESOURCES:
        if us_counts.get(resource, 0) < 1:
            raise GlobalFactorFeatureSmokeError(
                f"FRENCH_US_RESOURCE_MISSING:{resource}"
            )
    for resource in _GLOBAL_RESOURCES:
        if global_counts.get(resource, 0) < 1:
            raise GlobalFactorFeatureSmokeError(
                f"FRENCH_GLOBAL_RESOURCE_MISSING:{resource}"
            )

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels: dict[str, pd.DataFrame] = {
        "industries": normalize_french_industry_panel(
            raw["D_FRENCH_US"], sessions=sessions
        ),
        "us_factors": normalize_french_factor_panel(
            raw["D_FRENCH_US"], sessions=sessions
        ),
    }
    global_panels = normalize_french_global_factor_panels(
        raw["D_FRENCH_GLOBAL"], sessions=sessions
    )
    missing_normalized = [
        resource for resource in _GLOBAL_RESOURCES if resource not in global_panels
    ]
    if missing_normalized:
        raise GlobalFactorFeatureSmokeError(
            "NORMALIZED_FRENCH_GLOBAL_PANEL_MISSING:"
            f"{','.join(missing_normalized)}"
        )
    panels.update(global_panels)

    outputs = dict(evaluate_global_factor_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_global_factor_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_global_factor_configuration,
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
        "scope": "industry_global_factor_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "approved_free_resources": [*_US_RESOURCES, *_GLOBAL_RESOURCES],
        "physical_resource_rows": {
            "D_FRENCH_US": {
                resource: us_counts[resource] for resource in _US_RESOURCES
            },
            "D_FRENCH_GLOBAL": {
                resource: global_counts[resource]
                for resource in _GLOBAL_RESOURCES
            },
        },
        "daily_release_policy": "next_spy_session",
        "row_release_causality_valid": True,
        "historical_revision_pit_exact": False,
        "source_vintage_status": "current_download_not_historical_vintage",
        "source_vintage_warning": (
            "Kenneth French may revise full history; require candidate "
            "robustness both with and without F161-F170."
        ),
        "f166_fidelity": "proxy_not_exact",
        "f166_warning": (
            "US FF3 and developed-ex-US five-factor series use different "
            "construction universes; compare only their shared market, size "
            "and value columns."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [
            list(group) for group in audit.exact_duplicate_groups
        ],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_2004_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "global_factor_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F161_F170.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "GlobalFactorFeatureSmokeError",
    "build_global_factor_feature_smoke",
]
