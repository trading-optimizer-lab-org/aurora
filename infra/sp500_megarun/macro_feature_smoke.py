"""Train-only GitHub smoke for executable SP500 macro lanes F032-F050."""

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
    normalize_credit_spread_panel,
    normalize_cftc_sp500_panel,
    normalize_financial_conditions_panel,
    normalize_finra_margin_panel,
    normalize_fomc_event_panel,
    normalize_french_us_panels,
    normalize_fx_cross_asset_panel,
    normalize_lagged_valuation_panel,
    normalize_macro_release_panel,
    normalize_philadelphia_realtime_growth_panel,
    normalize_revised_z1_equity_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
    normalize_world_bank_cross_asset_panel,
)
from aurora.infra.sp500_megarun.macro_feature_engine import evaluate_macro_lane
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame


class MacroFeatureSmokeError(ValueError):
    """Raised when the smoke target is not the physical train snapshot."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_EXECUTABLE_LANES = tuple(f"F{index:03d}" for index in range(32, 51))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_macro_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Normalize, execute and audit F032-F050 without mounting validation."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise MacroFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    required_datasets = (
        "D_RATES",
        "D_FIN_COND",
        "D_PHILLY_RT",
        "D_MACRO_PIT",
        "D_FOMC_PUBLIC",
        "D_CALENDAR",
        "D_GOYAL",
        "D_SHILLER",
        "D_SPY",
        "D_FX",
        "D_GOLD",
        "D_WTI",
        "D_FRENCH_FACTORS",
        "D_FRENCH_INDUSTRIES",
        "D_Z1",
        "D_FINRA_MARGIN",
        "D_CFTC_LEGACY",
    )
    datasets: dict[str, pd.DataFrame] = {}
    for dataset_id in required_datasets:
        target = snapshot / f"{dataset_id}.parquet"
        if not target.is_file():
            raise MacroFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset_id}")
        datasets[dataset_id] = pd.read_parquet(target)
    sessions = pd.DatetimeIndex(
        pd.to_datetime(datasets["D_CALENDAR"]["date"], errors="raise")
    ).normalize().unique().sort_values()
    sessions = sessions[sessions <= _TRAIN_END]
    rates = datasets["D_RATES"]
    credit = normalize_credit_spread_panel(rates, sessions=sessions)
    curve = normalize_treasury_curve_panel(rates, sessions=sessions)
    financial = normalize_financial_conditions_panel(
        datasets["D_FIN_COND"], sessions=sessions
    )
    realtime = normalize_philadelphia_realtime_growth_panel(
        datasets["D_PHILLY_RT"], sessions=sessions
    )
    macro = normalize_macro_release_panel(
        datasets["D_MACRO_PIT"], sessions=sessions
    )
    fomc = normalize_fomc_event_panel(datasets["D_FOMC_PUBLIC"], sessions=sessions)
    valuation = normalize_lagged_valuation_panel(
        datasets["D_GOYAL"],
        datasets["D_SHILLER"],
        sessions=sessions,
    )
    market = normalize_spy_decision_panel(datasets["D_SPY"], sessions=sessions)
    fx = normalize_fx_cross_asset_panel(datasets["D_FX"], sessions=sessions)
    commodities = normalize_world_bank_cross_asset_panel(
        datasets["D_GOLD"], datasets["D_WTI"], sessions=sessions
    )
    factors, industries = normalize_french_us_panels(
        datasets["D_FRENCH_FACTORS"],
        datasets["D_FRENCH_INDUSTRIES"],
        sessions=sessions,
    )
    balance = normalize_revised_z1_equity_panel(
        datasets["D_Z1"], sessions=sessions
    )
    margin = normalize_finra_margin_panel(
        datasets["D_FINRA_MARGIN"], sessions=sessions
    )
    positioning = normalize_cftc_sp500_panel(
        datasets["D_CFTC_LEGACY"], sessions=sessions
    )
    calendar = normalize_calendar_state_panel(sessions=sessions)
    panels = {
        "credit": credit,
        "rates": curve,
        "financial": financial,
        "realtime": realtime,
        "macro": macro,
        "fomc": fomc,
        "calendar": calendar,
        "valuation": valuation,
        "market": market,
        "fx": fx,
        "commodities": commodities,
        "factors": factors,
        "industries": industries,
        "balance": balance,
        "margin": margin,
        "positioning": positioning,
    }
    parameters: dict[str, dict[str, Any]] = {
        "F032": {"window": 252, "change_lag": 5},
        "F033": {"window": 252, "change_lag": 5},
        "F034": {"window": 252, "change_lag": 5},
        "F035": {"window": 12},
        "F036": {"window": 12},
        "F037": {"window": 12},
        "F038": {"event_window": 20, "normalization_window": 252},
        "F039": {"window": 252},
        "F040": {"window": 24, "earnings_lag": 12},
        "F041": {"slow_window": 8, "margin_window": 9, "positioning_window": 26},
        "F042": {"window": 63, "duration": 7},
        "F043": {"window": 63},
        "F044": {"window": 63},
        "F045": {"window": 63, "shock_threshold": 2},
        "F046": {"window": 63, "threshold": 0},
        "F047": {"window": 63},
        "F048": {"window": 63},
        "F049": {"slow_window": 8, "margin_window": 9, "positioning_window": 26},
        "F050": {"calendar_rule": "turn_of_month", "hold": 3},
    }
    outputs = {
        lane_id: evaluate_macro_lane(lane_id, panels, parameters[lane_id])
        for lane_id in _EXECUTABLE_LANES
    }
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_EXECUTABLE_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )

    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum_feature_date = pd.Timestamp.min
    for lane_id, output in outputs.items():
        target = root / "features" / f"{lane_id}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum_feature_date = max(maximum_feature_date, output["date"].max())
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(output)),
            "non_null_values": int(output["value"].notna().sum()),
        }
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(audit.ready),
        "scope": "technical_macro_feature_smoke_train_only",
        "executable_lanes": list(_EXECUTABLE_LANES),
        "executable_lane_count": len(_EXECUTABLE_LANES),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    (root / "macro_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["MacroFeatureSmokeError", "build_macro_feature_smoke"]
