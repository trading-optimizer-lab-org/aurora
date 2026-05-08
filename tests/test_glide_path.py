"""Tests for RetirementGlidePath.

Run: pytest quantforge/tests/test_glide_path.py -v
"""
from __future__ import annotations
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.glide_path import (
    GlidePathConfig,
    GlidePathResult,
    RetirementGlidePath,
)


def test_default_config_valid():
    cfg = GlidePathConfig()
    assert cfg.shape in ("linear", "target_date")


def test_invalid_shape_rejected():
    with pytest.raises(ValueError):
        GlidePathConfig(shape="exotic")


def test_invalid_start_equity_rejected():
    with pytest.raises(ValueError):
        GlidePathConfig(start_equity=1.5)


def test_invalid_risk_tolerance_rejected():
    with pytest.raises(ValueError):
        GlidePathConfig(risk_tolerance=2.0)


def test_returns_result():
    gp = RetirementGlidePath()
    res = gp.allocate(as_of=datetime(2030, 1, 1))
    assert isinstance(res, GlidePathResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_weights_sum_to_one():
    gp = RetirementGlidePath()
    res = gp.allocate(as_of=datetime(2030, 1, 1))
    assert pytest.approx(res.weights.iloc[0].sum(), abs=1e-9) == 1.0


def test_far_from_retirement_high_equity():
    """Linear shape: many years left -> equity ~ start_equity."""
    cfg = GlidePathConfig(
        shape="linear", start_equity=0.90, end_equity=0.30,
        target_retirement_year=2060, current_age=30, retirement_age=65,
    )
    gp = RetirementGlidePath(cfg)
    res = gp.allocate(as_of=datetime(2024, 1, 1))
    assert res.equity_pct > 0.5


def test_at_retirement_low_equity():
    cfg = GlidePathConfig(
        shape="target_date", start_equity=0.90, end_equity=0.30,
        target_retirement_year=2024, current_age=30, retirement_age=65,
    )
    gp = RetirementGlidePath(cfg)
    res = gp.allocate(as_of=datetime(2024, 6, 1))
    assert res.equity_pct < 0.5


def test_target_date_holds_until_taper_window():
    cfg = GlidePathConfig(
        shape="target_date", start_equity=0.90, end_equity=0.30,
        target_retirement_year=2050,
    )
    gp = RetirementGlidePath(cfg)
    res = gp.allocate(as_of=datetime(2024, 1, 1))
    # 26 years to retirement, well outside the 10y taper window.
    assert res.equity_pct == pytest.approx(0.90, abs=1e-6)


def test_risk_tolerance_scales_equity():
    aggressive = RetirementGlidePath(GlidePathConfig(risk_tolerance=1.5))
    conservative = RetirementGlidePath(GlidePathConfig(risk_tolerance=0.5))
    a = aggressive.allocate(as_of=datetime(2030, 1, 1))
    c = conservative.allocate(as_of=datetime(2030, 1, 1))
    assert a.equity_pct >= c.equity_pct


def test_with_prices_dataframe():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = pd.DataFrame({"EQUITY": [100.0] * 10, "BOND": [50.0] * 10}, index=idx)
    gp = RetirementGlidePath()
    res = gp.allocate(prices=prices, as_of=datetime(2030, 1, 1))
    assert list(res.weights.columns) == ["EQUITY", "BOND"]
    assert pytest.approx(res.weights.iloc[0].sum(), abs=1e-6) == 1.0


def test_equity_plus_bond_pct_one():
    gp = RetirementGlidePath()
    res = gp.allocate(as_of=datetime(2030, 1, 1))
    assert pytest.approx(res.equity_pct + res.bond_pct, abs=1e-9) == 1.0
