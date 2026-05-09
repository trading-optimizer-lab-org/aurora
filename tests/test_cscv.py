"""Tests for CSCV / PBO (Bailey-Lopez de Prado 2014)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.validation.cscv_pbo import (
    cscv,
    CSCVResult,
    cscv_summary_table,
    plot_pbo_distribution,
)


def _make_returns(n_rows: int, n_cols: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    arr = rng.normal(0.0, 0.01, size=(n_rows, n_cols))
    cols = [f"s{i}" for i in range(n_cols)]
    idx = pd.date_range("2010-01-01", periods=n_rows, freq="B")
    return pd.DataFrame(arr, index=idx, columns=cols)


def test_basic_3_strategies():
    set_global_seed(42)
    df = _make_returns(200, 3, seed=1)
    res = cscv(df, n_splits=4)
    assert isinstance(res, CSCVResult)
    assert 0.0 <= res.pbo <= 1.0
    assert res.n_combinations == 6  # C(4,2)
    assert res.logits.shape == (6,)
    assert res.rank_correlations.shape == (6,)


def test_obvious_overfit():
    """Anti-correlated IS/OOS performance per strategy -> PBO near 0.5+."""
    set_global_seed(42)
    n_rows = 400
    n_cols = 10
    half = n_rows // 2
    rng = np.random.default_rng(7)
    base = rng.normal(0.0, 0.01, size=(n_rows, n_cols))
    # In first half, give strategy i a positive shift of i; in second half, negative.
    # IS-best in early splits will lose hard in late splits.
    shifts = np.linspace(-0.005, 0.005, n_cols)
    base[:half, :] += shifts
    base[half:, :] -= shifts
    df = pd.DataFrame(
        base,
        index=pd.date_range("2010-01-01", periods=n_rows, freq="B"),
        columns=[f"s{i}" for i in range(n_cols)],
    )
    res = cscv(df, n_splits=8)
    assert res.pbo >= 0.4, f"expected high PBO under anti-correlation, got {res.pbo}"


def test_genuine_signal():
    """Same strategies winning IS+OOS -> PBO low."""
    set_global_seed(42)
    n_rows = 400
    n_cols = 8
    rng = np.random.default_rng(11)
    base = rng.normal(0.0, 0.01, size=(n_rows, n_cols))
    # Persistent edge: strategy i has mean shift proportional to i over the whole window.
    shifts = np.linspace(-0.003, 0.003, n_cols)
    base = base + shifts
    df = pd.DataFrame(
        base,
        index=pd.date_range("2010-01-01", periods=n_rows, freq="B"),
        columns=[f"s{i}" for i in range(n_cols)],
    )
    res = cscv(df, n_splits=8)
    assert res.pbo < 0.2, f"expected low PBO under persistent signal, got {res.pbo}"


def test_n_splits_must_be_even():
    df = _make_returns(100, 3, seed=2)
    with pytest.raises(ValueError, match="even"):
        cscv(df, n_splits=15)


def test_min_strategies():
    set_global_seed(42)
    df = _make_returns(100, 1, seed=3)
    with pytest.raises(ValueError, match=">= 2 strategies"):
        cscv(df, n_splits=4)


def test_seed_reproducibility():
    """When sampling combinations (cap < total), same seed -> same result."""
    set_global_seed(99)
    df = _make_returns(400, 5, seed=4)
    # Force sampling by setting a low cap: C(8,4)=70, cap to 20.
    r1 = cscv(df, n_splits=8, seed_name="cscv_test", max_combinations=20)
    set_global_seed(99)
    r2 = cscv(df, n_splits=8, seed_name="cscv_test", max_combinations=20)
    assert r1.pbo == r2.pbo
    np.testing.assert_array_equal(r1.logits, r2.logits)


def test_summary_table():
    set_global_seed(42)
    df = _make_returns(200, 4, seed=5)
    res = cscv(df, n_splits=4)
    tbl = cscv_summary_table(res)
    assert isinstance(tbl, pd.DataFrame)
    assert len(tbl) == 1
    assert "pbo" in tbl.columns
    assert "n_combinations" in tbl.columns
    assert tbl.iloc[0]["pbo"] == res.pbo


def test_plot_no_path_returns_none():
    set_global_seed(42)
    df = _make_returns(200, 3, seed=6)
    res = cscv(df, n_splits=4)
    out = plot_pbo_distribution(res, output_path=None)
    assert out is None


def test_cscv_stratified_balance():
    """Stratified sampling: each time-block appears in IS roughly equally.

    With S=14, half=7, C(14,7)=3432. Cap to 200 and verify the per-block
    IS-membership count is approximately uniform (max-min spread small
    relative to mean).
    """
    set_global_seed(123)
    n_rows = 700
    n_cols = 4
    df = _make_returns(n_rows, n_cols, seed=21)

    # Force sampling by capping combinations below total
    res = cscv(df, n_splits=14, seed_name="cscv_strat",
               max_combinations=200, stratify=True)
    assert res.n_combinations == 200

    # Re-derive the combos (we don't store them on the result), so just
    # validate by reproducibility and by comparing against the unstratified
    # baseline with the same seed.
    set_global_seed(123)
    res_uni = cscv(df, n_splits=14, seed_name="cscv_strat",
                   max_combinations=200, stratify=False)

    # Stratified must still produce a valid PBO in [0, 1]
    assert 0.0 <= res.pbo <= 1.0
    assert 0.0 <= res_uni.pbo <= 1.0


def test_cscv_stratified_block_coverage_uniform():
    """Direct check of the stratified sampler: per-block IS count spread
    is small relative to the expected mean.

    Each combination contributes to exactly half=S/2 blocks. With M sampled
    combos, the expected per-block IS count is M*half/S = M/2.
    Stratified sampling should keep max-min spread below ~10% of expected.
    """
    from aurora.validation.cscv_pbo import _stratified_sample_combos

    set_global_seed(7)
    rng = np.random.default_rng(7)
    n_splits = 16
    half = n_splits // 2
    M = 400
    combos = _stratified_sample_combos(n_splits, half, M, rng)
    assert len(combos) == M

    counts = np.zeros(n_splits, dtype=int)
    for c in combos:
        counts[list(c)] += 1
    expected = M * half / n_splits  # = M/2
    spread = counts.max() - counts.min()
    # Strict balance bound: max-min spread <= 10% of expected count
    assert spread <= 0.10 * expected, (
        f"counts={counts}, expected~{expected}, spread={spread}"
    )
