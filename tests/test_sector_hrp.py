"""Tests for SectorHRP.

Run: pytest aurora/tests/test_sector_hrp.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.sector_hrp import (
    SectorHRP,
    SectorHRPConfig,
    SectorHRPResult,
)


@pytest.fixture
def sector_prices():
    """Six assets across three sectors with structured intra-sector correlation."""
    rng = np.random.default_rng(42)
    n = 400
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    base_tech = rng.normal(0.0006, 0.012, n)
    base_fin = rng.normal(0.0004, 0.010, n)
    base_eng = rng.normal(0.0003, 0.013, n)
    rets = pd.DataFrame({
        "AAPL": base_tech + rng.normal(0, 0.002, n),
        "MSFT": base_tech + rng.normal(0, 0.002, n),
        "JPM": base_fin + rng.normal(0, 0.002, n),
        "GS": base_fin + rng.normal(0, 0.002, n),
        "XOM": base_eng + rng.normal(0, 0.002, n),
        "CVX": base_eng + rng.normal(0, 0.002, n),
    }, index=idx)
    prices = (1.0 + rets).cumprod() * 100.0
    return prices


@pytest.fixture
def lookup():
    return {
        "AAPL": "TECH", "MSFT": "TECH",
        "JPM": "FIN", "GS": "FIN",
        "XOM": "ENG", "CVX": "ENG",
    }


def test_returns_dataframe(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert isinstance(res, SectorHRPResult)
    assert isinstance(res.weights, pd.DataFrame)
    assert list(res.weights.columns) == list(sector_prices.columns)


def test_weights_sum_to_one(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert pytest.approx(res.weights.iloc[0].sum(), abs=1e-6) == 1.0


def test_weights_non_negative(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert (res.weights.iloc[0] >= -1e-12).all()


def test_sector_weights_sum_to_one(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    s = res.sector_weights.sum()
    assert pytest.approx(s, abs=1e-6) == 1.0


def test_three_sectors_all_present(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert set(res.intra_sector_weights.keys()) == {"TECH", "FIN", "ENG"}


def test_intra_weights_sum_to_one(sector_prices, lookup):
    cfg = SectorHRPConfig(sector_lookup=lookup)
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    for sec, w in res.intra_sector_weights.items():
        assert pytest.approx(w.sum(), abs=1e-6) == 1.0


def test_unknown_asset_falls_into_default(sector_prices):
    # No lookup -> all assets fall into OTHER as a single sector.
    cfg = SectorHRPConfig(sector_lookup={}, fallback_sector="OTHER")
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert "OTHER" in res.intra_sector_weights


def test_singleton_sector(sector_prices):
    cfg = SectorHRPConfig(sector_lookup={"AAPL": "SOLO"})
    sh = SectorHRP(cfg)
    res = sh.allocate(sector_prices)
    assert "SOLO" in res.intra_sector_weights
    assert pytest.approx(res.intra_sector_weights["SOLO"].iloc[0], abs=1e-12) == 1.0


def test_requires_dataframe():
    sh = SectorHRP()
    with pytest.raises(TypeError):
        sh.allocate([1, 2])
