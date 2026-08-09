from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.macro_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"macro feature engine is missing: {exc}")


def _credit_panel(periods: int = 500) -> pd.DataFrame:
    dates = pd.bdate_range("2009-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    spread = 1.5 + 0.2 * np.sin(phase / 17.0) + 0.0002 * phase
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "aaa_yield": 4.0 + 0.1 * np.sin(phase / 40.0),
            "baa_yield": 4.0 + 0.1 * np.sin(phase / 40.0) + spread,
            "baa_aaa_spread": spread,
        }
    )


def test_f032_is_trailing_credit_spread_change_acceleration() -> None:
    api = _engine_api()
    panel = _credit_panel(80)

    result = api.evaluate_macro_lane(
        "F032",
        {"credit": panel},
        {"window": 20, "change_lag": 5},
    )

    spread = panel["baa_aaa_spread"]
    change = spread.diff(5)
    acceleration = change.diff(5)
    raw = change + acceleration
    expected = (raw.iloc[-1] - raw.iloc[-20:].mean()) / raw.iloc[-20:].std(ddof=0)
    assert result.loc[79, "value"] == pytest.approx(expected)


def test_f032_is_causal_under_future_append() -> None:
    api = _engine_api()
    panel = _credit_panel(100)

    before = api.evaluate_macro_lane(
        "F032", {"credit": panel.iloc[:80]}, {"window": 20, "change_lag": 5}
    )
    after = api.evaluate_macro_lane(
        "F032", {"credit": panel}, {"window": 20, "change_lag": 5}
    ).iloc[:80]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_macro_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panel = _credit_panel(20)
    panel.loc[len(panel)] = {
        "date": pd.Timestamp("2011-01-03"),
        "observed_at": pd.Timestamp("2010-12-31"),
        "available_at": pd.Timestamp("2011-01-03"),
        "aaa_yield": 4.0,
        "baa_yield": 5.5,
        "baa_aaa_spread": 1.5,
    }

    with pytest.raises(api.MacroFeatureEngineError, match="NON_TRAIN_PANEL_ROW:credit"):
        api.evaluate_macro_lane("F032", {"credit": panel}, {"window": 20})
