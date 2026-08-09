"""Causal execution kernels for SP500 macro families beginning at F032."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class MacroFeatureEngineError(ValueError):
    """Raised when a macro input is incomplete, non-causal or non-train."""


_TRAIN_END = pd.Timestamp("2010-12-31")


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MacroFeatureEngineError(f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}")
    panel = frame.copy()
    for column in required:
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize()
    if panel[list(required)].isna().any().any():
        raise MacroFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(_TRAIN_END).any():
        raise MacroFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise MacroFeatureEngineError(f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise MacroFeatureEngineError(f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise MacroFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (values - mean) / deviation


def evaluate_macro_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen macro formula on data available by each decision date."""

    if lane_id != "F032":
        raise MacroFeatureEngineError(f"MACRO_LANE_NOT_IMPLEMENTED:{lane_id}")
    if "credit" not in input_panels:
        raise MacroFeatureEngineError("MACRO_PANELS_MISSING:credit")
    credit = _validated_panel("credit", input_panels["credit"])
    if "baa_aaa_spread" not in credit:
        raise MacroFeatureEngineError("CREDIT_SPREAD_MISSING")
    window = int(parameters.get("window", 252))
    change_lag = int(parameters.get("change_lag", 5))
    spread = pd.to_numeric(credit["baa_aaa_spread"], errors="coerce")
    change = spread.diff(change_lag)
    acceleration = change.diff(change_lag)
    value = _rolling_z(change + acceleration, window)
    return pd.DataFrame(
        {
            "date": credit["date"],
            "observed_at": credit["observed_at"],
            "available_at": credit["available_at"],
            "value": value.replace([np.inf, -np.inf], np.nan),
        }
    )


__all__ = ["MacroFeatureEngineError", "evaluate_macro_lane"]
