"""Tests for quantforge.research.paper_replicator."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.research.paper_replicator import (
    PaperReplicator,
    PaperSpec,
    ReplicationReport,
)


def _all_long_signal(prices: pd.Series) -> np.ndarray:
    return np.ones(len(prices), dtype=float)


def _all_flat_signal(prices: pd.Series) -> np.ndarray:
    return np.zeros(len(prices), dtype=float)


def test_replicator_match_when_within_tolerance(synthetic_prices_daily):
    spec = PaperSpec(
        title="All-long",
        signal_def=_all_long_signal,
        reported_metrics={"sharpe": 0.0, "cagr": 0.0},
        tolerance={"sharpe": 5.0, "cagr": 100.0},
    )
    rep = PaperReplicator().replicate(spec, synthetic_prices_daily)
    assert isinstance(rep, ReplicationReport)
    assert rep.title == "All-long"
    assert rep.matched is True
    assert "sharpe" in rep.per_metric


def test_replicator_no_match_when_far(synthetic_prices_daily):
    spec = PaperSpec(
        title="Bogus",
        signal_def=_all_long_signal,
        reported_metrics={"sharpe": 100.0},
        tolerance={"sharpe": 0.01},
    )
    rep = PaperReplicator().replicate(spec, synthetic_prices_daily)
    assert rep.matched is False
    assert rep.per_metric["sharpe"]["within"] is False


def test_replicator_observed_metrics_populated(synthetic_prices_daily):
    spec = PaperSpec(title="Flat", signal_def=_all_flat_signal,
                     reported_metrics={"sharpe": 0.0}, tolerance={"sharpe": 0.5})
    rep = PaperReplicator().replicate(spec, synthetic_prices_daily)
    assert "calmar" in rep.observed_metrics
    assert "cagr" in rep.observed_metrics


def test_replicator_requires_pd_series():
    spec = PaperSpec(title="x", signal_def=_all_long_signal,
                     reported_metrics={"sharpe": 0.0})
    with pytest.raises(TypeError):
        PaperReplicator().replicate(spec, np.zeros(10))


def test_replicator_empty_reported_metrics_not_match(synthetic_prices_daily):
    spec = PaperSpec(title="empty", signal_def=_all_long_signal,
                     reported_metrics={})
    rep = PaperReplicator().replicate(spec, synthetic_prices_daily)
    assert rep.matched is False
