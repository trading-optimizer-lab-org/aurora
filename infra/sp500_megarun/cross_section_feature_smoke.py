"""Train-only GitHub smoke for executable SP500 lanes F111-F120."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.cross_section_feature_engine import (
    evaluate_cross_section_family_batch,
    evaluate_cross_section_lane,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_cboe_vol_bundle_panel,
    normalize_credit_spread_panel,
    normalize_financial_conditions_panel,
    normalize_french_factor_panel,
    normalize_french_industry_panel,
    normalize_fx_cross_asset_panel,
    normalize_lagged_valuation_panel,
    normalize_macro_release_panel,
    normalize_policy_rate_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class CrossSectionFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{i:03d}" for i in range(111, 121))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASETS = (
    "D_SPY", "D_FRENCH_INDUSTRIES", "D_FRENCH_FACTORS", "D_RATES",
    "D_FX", "D_GOYAL", "D_SHILLER", "D_FIN_COND", "D_MACRO_PIT", "D_CBOE_VOL",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_cross_section_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F113" and parameter == "momentum_lag":
        configuration["statistic"] = "curve_momentum"
    if lane_id == "F116" and parameter == "window":
        configuration["statistic"] = "common_share"
    if lane_id == "F117" and parameter == "change_lag":
        configuration["statistic"] = "acceleration"
    if lane_id == "F120" and parameter == "horizon":
        configuration["embargo"] = max(
            int(configuration["embargo"]),
            int(configuration["horizon"]),
        )
    return configuration


def _merge_rates(curve: pd.DataFrame, credit: pd.DataFrame, policy: pd.DataFrame) -> pd.DataFrame:
    result = curve.copy()
    observed_columns = ["curve_observed_at"]
    result = result.rename(columns={"observed_at": "curve_observed_at"}).drop(columns="available_at")
    for label, panel in (("credit", credit), ("policy", policy)):
        current = panel.rename(columns={"observed_at": f"{label}_observed_at"}).drop(columns="available_at")
        result = pd.merge_asof(result.sort_values("date"), current.sort_values("date"), on="date", direction="backward")
        observed_columns.append(f"{label}_observed_at")
    result["observed_at"] = result[observed_columns].max(axis=1)
    result["available_at"] = result["date"]
    return result.drop(columns=observed_columns)


def build_cross_section_feature_smoke(train_snapshot: str | Path, *, output_dir: str | Path) -> dict[str, Any]:
    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise CrossSectionFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    data: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        path = snapshot / f"{dataset}.parquet"
        if not path.is_file():
            raise CrossSectionFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        data[dataset] = pd.read_parquet(path)
    sessions = pd.DatetimeIndex(pd.to_datetime(data["D_SPY"]["date"], errors="raise")).normalize().unique().sort_values()
    sessions = sessions[sessions <= _TRAIN_END]
    curve = normalize_treasury_curve_panel(data["D_RATES"], sessions=sessions)
    panels = {
        "spy": normalize_spy_decision_panel(data["D_SPY"], sessions=sessions),
        "industries": normalize_french_industry_panel(data["D_FRENCH_INDUSTRIES"], sessions=sessions),
        "factors": normalize_french_factor_panel(data["D_FRENCH_FACTORS"], sessions=sessions),
        "rates": _merge_rates(
            curve,
            normalize_credit_spread_panel(data["D_RATES"], sessions=sessions),
            normalize_policy_rate_panel(data["D_RATES"], sessions=sessions),
        ),
        "fx": normalize_fx_cross_asset_panel(data["D_FX"], sessions=sessions),
        "valuation": normalize_lagged_valuation_panel(data["D_GOYAL"], data["D_SHILLER"], sessions=sessions),
        "financial": normalize_financial_conditions_panel(data["D_FIN_COND"], sessions=sessions),
        "macro": normalize_macro_release_panel(data["D_MACRO_PIT"], sessions=sessions),
        "vol": normalize_cboe_vol_bundle_panel(data["D_CBOE_VOL"], sessions=sessions),
    }
    outputs = dict(evaluate_cross_section_family_batch(panels))
    audit = audit_feature_outputs(outputs, expected_lane_ids=_LANES, search_start=_SEARCH_START, search_end=_TRAIN_END)
    data_contract = load_and_validate_contract(
        _REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
    )
    feature_contract = load_and_validate_feature_contract(
        _REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json",
        data_contract,
    )
    expected_years = sorted(
        set(pd.DatetimeIndex(sessions[sessions >= _SEARCH_START]).year)
    )
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_cross_section_lane(
            lane_id,
            panels,
            configuration,
        ),
        expected_years=expected_years,
        repair=_repair_cross_section_configuration,
    )
    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum = pd.Timestamp.min
    for lane, output in outputs.items():
        target = root / "features" / f"{lane}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum = max(maximum, pd.to_datetime(output["date"]).max())
        artifacts[lane] = {"path": target.relative_to(root).as_posix(), "sha256": _sha256(target), "rows": len(output), "non_null_values": int(output["value"].notna().sum())}
    report = {
        "schema_version": 1,
        "ready": bool(audit.ready and parameter_audit["ready"] and len(outputs) == 10),
        "scope": "technical_cross_section_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "search_start": "1998-01-01",
        "train_end": "2010-12-31",
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "cross_section_feature_smoke_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "parameter_choice_audit_F111_F120.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["CrossSectionFeatureSmokeError", "build_cross_section_feature_smoke"]
