"""Tests for ESGFilter.

Run: pytest quantforge/tests/test_esg_filter.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.esg_filter import (
    ESGConfig,
    ESGFilter,
    ESGFilterResult,
)


@pytest.fixture
def synthetic_prices():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "GREEN": np.linspace(100, 120, 10),
        "OK": np.linspace(50, 55, 10),
        "DIRTY": np.linspace(75, 70, 10),
        "MIXED": np.linspace(30, 33, 10),
    }, index=idx)


@pytest.fixture
def mock_scores():
    return {
        "GREEN": {"E": 9.0, "S": 8.5, "G": 9.5},
        "OK":    {"E": 6.0, "S": 7.0, "G": 6.5},
        "DIRTY": {"E": 2.0, "S": 3.0, "G": 4.0},
        "MIXED": {"E": 8.0, "S": 2.0, "G": 7.0},   # fails S threshold
    }


def test_default_config():
    cfg = ESGConfig()
    assert cfg.score_source in ("mock", "msci")


def test_invalid_source_rejected():
    with pytest.raises(ValueError):
        ESGConfig(score_source="bloomberg")


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        ESGConfig(e_threshold=11.0)


def test_returns_dataframe(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert isinstance(res, ESGFilterResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_weights_sum_to_one(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert pytest.approx(res.weights.iloc[0].sum(), abs=1e-9) == 1.0


def test_dirty_excluded(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores, e_threshold=5.0)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert "DIRTY" in res.excluded


def test_mixed_excluded_in_require_all(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores, s_threshold=5.0, require_all=True)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert "MIXED" in res.excluded


def test_mixed_passes_in_require_or(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores, s_threshold=5.0, require_all=False)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    # MIXED has E=8, G=7, both above 5, so OR mode keeps it.
    assert "MIXED" not in res.excluded


def test_msci_source_runs(synthetic_prices):
    """MSCI stub deterministically scores, exercising that code path."""
    cfg = ESGConfig(score_source="msci", e_threshold=0.0,
                    s_threshold=0.0, g_threshold=0.0)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert res.scores.shape == (4, 3)


def test_inner_weights_consumed(synthetic_prices, mock_scores):
    cfg = ESGConfig(
        mock_scores=mock_scores,
        inner_weights=pd.Series({"GREEN": 0.7, "OK": 0.3}),
    )
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    row = res.weights.iloc[0]
    if "GREEN" in row.index and "OK" in row.index:
        assert row["GREEN"] >= row["OK"]


def test_requires_dataframe():
    flt = ESGFilter()
    with pytest.raises(TypeError):
        flt.allocate([1, 2])


def test_pass_mask_is_bool_series(synthetic_prices, mock_scores):
    cfg = ESGConfig(mock_scores=mock_scores)
    flt = ESGFilter(cfg)
    res = flt.allocate(synthetic_prices)
    assert res.pass_mask.dtype == bool
