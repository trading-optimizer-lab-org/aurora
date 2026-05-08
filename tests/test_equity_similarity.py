"""Tests for analytics.equity_similarity (R83)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantforge.analytics.equity_similarity import (
    pairwise_matrix,
    pairwise_similarity,
)


def _curve(seed: int, n: int = 250, drift: float = 0.0005) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.01, n)
    nav = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(nav, index=pd.date_range("2025-01-01", periods=n, freq="B"))


def test_identical_curves_score_one():
    a = _curve(seed=1)
    b = a.copy()
    score = pairwise_similarity(a, b, strategy_id_a="alpha", strategy_id_b="copy")
    assert score.pearson_similarity == 1.0
    assert score.return_correlation == 1.0
    assert score.is_duplicate is True


def test_independent_curves_score_close_to_zero():
    a = _curve(seed=1)
    b = _curve(seed=999, drift=0.0)
    score = pairwise_similarity(a, b, strategy_id_a="alpha", strategy_id_b="beta")
    assert abs(score.return_correlation) < 0.5
    assert score.is_duplicate is False


def test_nearly_identical_curves_above_threshold():
    a = _curve(seed=1)
    # Same returns plus tiny noise.
    b = a.copy()
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.0001, len(a))
    b = a * (1 + pd.Series(noise, index=a.index))
    score = pairwise_similarity(a, b, strategy_id_a="alpha", strategy_id_b="near")
    assert score.pearson_similarity > 0.95


def test_no_overlap_returns_nan():
    a = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.date_range("2025-01-01", periods=3, freq="B"),
    )
    b = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.date_range("2026-01-01", periods=3, freq="B"),
    )
    score = pairwise_similarity(a, b)
    assert score.n_overlap_bars == 0
    assert pd.isna(score.pearson_similarity)


def test_pairwise_matrix_flags_duplicates():
    a = _curve(seed=1)
    b = _curve(seed=1)  # identical
    c = _curve(seed=999, drift=-0.0005)
    scores, dupes = pairwise_matrix(
        {"a": a, "b": b, "c": c}, duplicate_threshold=0.95
    )
    assert len(scores) == 3  # 3-choose-2
    dupe_pairs = [tuple(sorted(p)) for p in dupes]
    assert ("a", "b") in dupe_pairs
    assert ("a", "c") not in dupe_pairs
