"""Train-only GitHub smoke for executable SP500 lanes F091-F100."""

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
    normalize_cboe_vol_panel,
    normalize_cftc_sp500_panel,
    normalize_credit_money_panel,
    normalize_fomc_decision_panel,
    normalize_macro_release_panel,
    normalize_monetary_liquidity_panel,
    normalize_policy_rate_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.tail_macro_feature_engine import (
    evaluate_tail_macro_family_batch,
    evaluate_tail_macro_lane,
)


class TailMacroFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to the physical train partition."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_EXECUTABLE_LANES = tuple(f"F{index:03d}" for index in range(91, 101))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_DATASETS = (
    "D_SPY",
    "D_VIX",
    "D_VXO",
    "D_CFTC",
    "D_RATES",
    "D_MACRO_PIT",
    "D_FOMC_PUBLIC",
    "D_CALENDAR",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_tail_macro_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F091" and parameter == "tail_quantile":
        configuration["statistic"] = "realized_tail"
    if lane_id == "F093" and parameter == "positioning_window":
        configuration["statistic"] = "positioning_pressure"
    if lane_id == "F095" and parameter == "change_lag":
        configuration["statistic"] = "shock"
    if lane_id == "F097" and parameter == "window":
        configuration["statistic"] = "credit_impulse"
    if lane_id == "F098" and parameter == "scale_window":
        configuration["statistic"] = "growth_surprise"
    if lane_id == "F099":
        if parameter == "forecast_window":
            configuration["statistic"] = "inflation_trend"
        if parameter == "scale_window":
            configuration["statistic"] = "inflation_surprise"
    if lane_id == "F100" and parameter == "normalization_window":
        configuration["statistic"] = "event_interaction"
    return configuration


def build_tail_macro_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Normalize, execute and audit F091-F100 without mounting validation."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise TailMacroFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    datasets: dict[str, pd.DataFrame] = {}
    for dataset_id in _REQUIRED_DATASETS:
        target = snapshot / f"{dataset_id}.parquet"
        if not target.is_file():
            raise TailMacroFeatureSmokeError(
                f"TRAIN_DATASET_MISSING:{dataset_id}"
            )
        datasets[dataset_id] = pd.read_parquet(target)
    sessions = pd.DatetimeIndex(
        pd.to_datetime(datasets["D_CALENDAR"]["date"], errors="raise")
    ).normalize().unique().sort_values()
    sessions = sessions[sessions <= _TRAIN_END]
    panels = {
        "spy": normalize_spy_decision_panel(
            datasets["D_SPY"], sessions=sessions
        ),
        "vol": normalize_cboe_vol_panel(
            datasets["D_VIX"], datasets["D_VXO"], sessions=sessions
        ),
        "cftc": normalize_cftc_sp500_panel(
            datasets["D_CFTC"], sessions=sessions
        ),
        "rates": normalize_treasury_curve_panel(
            datasets["D_RATES"], sessions=sessions
        ),
        "policy": normalize_policy_rate_panel(
            datasets["D_RATES"], sessions=sessions
        ),
        "calendar": normalize_calendar_state_panel(sessions=sessions),
        "liquidity": normalize_monetary_liquidity_panel(
            datasets["D_MACRO_PIT"], sessions=sessions
        ),
        "credit_money": normalize_credit_money_panel(
            datasets["D_MACRO_PIT"], sessions=sessions
        ),
        "macro": normalize_macro_release_panel(
            datasets["D_MACRO_PIT"], sessions=sessions
        ),
        "fomc": normalize_fomc_decision_panel(
            datasets["D_FOMC_PUBLIC"], sessions=sessions
        ),
    }
    outputs = dict(evaluate_tail_macro_family_batch(panels))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_EXECUTABLE_LANES,
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
    expected_years = sorted(
        set(
            pd.to_datetime(panels["spy"]["date"], errors="raise")
            .loc[lambda values: values.ge(_SEARCH_START)]
            .dt.year
        )
    )
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_EXECUTABLE_LANES,
        evaluator=lambda lane_id, configuration: evaluate_tail_macro_lane(
            lane_id,
            panels,
            configuration,
        ),
        expected_years=expected_years,
        repair=_repair_tail_macro_configuration,
    )

    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum_feature_date = pd.Timestamp.min
    for lane_id, output in outputs.items():
        target = root / "features" / f"{lane_id}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum_feature_date = max(
            maximum_feature_date,
            pd.to_datetime(output["date"], errors="raise").max(),
        )
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(output)),
            "non_null_values": int(output["value"].notna().sum()),
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(
            audit.ready
            and parameter_audit["ready"]
            and len(outputs) == len(_EXECUTABLE_LANES)
        ),
        "scope": "technical_tail_macro_feature_smoke_train_only",
        "executable_lanes": list(_EXECUTABLE_LANES),
        "executable_lane_count": len(_EXECUTABLE_LANES),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "availability_policy": "max_native_input_available_at",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "tail_macro_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F091_F100.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "TailMacroFeatureSmokeError",
    "build_tail_macro_feature_smoke",
]
