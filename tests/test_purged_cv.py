"""Tests for Purged K-Fold CV with embargo (Task G.1)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.validation.purged_cv import (
    PurgedKFold, PurgedKFoldResult, cv_score,
)
from quantforge.core.seed import set_global_seed, child_rng


@pytest.fixture
def fake_prices_500():
    idx = pd.date_range("2015-01-01", periods=500, freq="B")
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


@pytest.fixture
def fake_prices_1000():
    idx = pd.date_range("2010-01-01", periods=1000, freq="B")
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0003, 0.010, 1000)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _stateless_macross_factory():
    """No-arg factory: stateless strategy."""
    from quantforge.strategies.library.ma_cross import MACross
    return MACross(fast=10, slow=50)


def test_basic_5_splits(fake_prices_500):
    """5 folds → result with 5 fold_metrics, each ok."""
    res = cv_score(_stateless_macross_factory, fake_prices_500,
                   n_splits=5, embargo_pct=0.01)
    assert isinstance(res, PurgedKFoldResult)
    assert res.n_splits == 5
    assert len(res.fold_metrics) == 5
    for fm in res.fold_metrics:
        assert "fold" in fm
        assert "train_idx" in fm
        assert "test_idx" in fm
        assert fm["ok"] is True
        assert fm["metrics"] is not None
        assert "calmar" in fm["metrics"]
        assert "sharpe" in fm["metrics"]
        assert "mdd" in fm["metrics"]


def test_embargo_excludes_zone(fake_prices_1000):
    """embargo_pct=0.10 → train should not contain the 100 bars right after test_end."""
    pkf = PurgedKFold(n_splits=5, embargo_pct=0.10)
    X = pd.DataFrame({"x": fake_prices_1000.values}, index=fake_prices_1000.index)
    n = len(X)
    embargo_n = int(round(n * 0.10))

    splits = list(pkf.split(X))
    assert len(splits) == 5

    for fold_i, (train_idx, test_idx) in enumerate(splits):
        # Test indices contiguous
        assert np.all(np.diff(test_idx) == 1)
        test_end = int(test_idx[-1])
        # Embargo zone = (test_end, test_end + embargo_n] in positional terms
        emb_lo = test_end + 1
        emb_hi = min(test_end + embargo_n, n - 1)
        if emb_lo <= emb_hi:
            forbidden = set(range(emb_lo, emb_hi + 1))
            assert forbidden.isdisjoint(set(train_idx)), (
                f"fold {fold_i}: train contains embargo bars {forbidden & set(train_idx)}"
            )


def test_purge_overlap(fake_prices_500):
    """t1 with deliberate overlap → train indices that overlap the test span are purged."""
    # Build a t1 series where each label spans 10 bars forward (large overlap)
    idx = fake_prices_500.index
    n = len(idx)
    horizon = 10
    t1_vals = []
    for i in range(n):
        t1_vals.append(idx[min(i + horizon, n - 1)])
    t1 = pd.Series(pd.DatetimeIndex(t1_vals), index=idx)

    pkf = PurgedKFold(n_splits=5, embargo_pct=0.0, t1=t1)
    X = pd.DataFrame({"x": fake_prices_500.values}, index=idx)
    splits = list(pkf.split(X))
    assert len(splits) == 5

    # Compare against no-purge baseline (default t1 == no overlap)
    pkf_no_purge = PurgedKFold(n_splits=5, embargo_pct=0.0, t1=None)
    splits_no_purge = list(pkf_no_purge.split(X))

    for (train_p, test_p), (train_np, test_np) in zip(splits, splits_no_purge):
        # Test indices identical
        np.testing.assert_array_equal(test_p, test_np)
        # Purged train must be a subset of the no-purge train
        assert set(train_p).issubset(set(train_np))
        # And strictly smaller for at least the boundary folds (overlap exists)
    # Total purged size should be smaller than no-purge size somewhere
    total_p = sum(len(t) for t, _ in splits)
    total_np = sum(len(t) for t, _ in splits_no_purge)
    assert total_p < total_np, "purging removed zero samples — bug"


def test_no_t1_default(fake_prices_500):
    """No t1 passed → defaults to no-overlap t1 (purging is a no-op)."""
    pkf = PurgedKFold(n_splits=4, embargo_pct=0.0, t1=None)
    X = pd.DataFrame({"x": fake_prices_500.values}, index=fake_prices_500.index)
    n = len(X)
    splits = list(pkf.split(X))
    # With no embargo and default t1, train+test should reconstruct the full set
    for train_idx, test_idx in splits:
        assert len(set(train_idx).intersection(set(test_idx))) == 0
        assert len(train_idx) + len(test_idx) == n


def test_reproducibility(fake_prices_500):
    """Same seed → same fold splits across two runs."""
    set_global_seed(123)
    _ = child_rng("purged_cv")  # smoke-call, no randomness used in deterministic split
    pkf_a = PurgedKFold(n_splits=5, embargo_pct=0.02)
    X = pd.DataFrame({"x": fake_prices_500.values}, index=fake_prices_500.index)
    splits_a = [(t.copy(), s.copy()) for t, s in pkf_a.split(X)]

    set_global_seed(123)
    _ = child_rng("purged_cv")
    pkf_b = PurgedKFold(n_splits=5, embargo_pct=0.02)
    splits_b = [(t.copy(), s.copy()) for t, s in pkf_b.split(X)]

    assert len(splits_a) == len(splits_b)
    for (ta, sa), (tb, sb) in zip(splits_a, splits_b):
        np.testing.assert_array_equal(ta, tb)
        np.testing.assert_array_equal(sa, sb)


def test_metrics_aggregation(fake_prices_1000):
    """mean / median / std computed correctly across folds."""
    res = cv_score(_stateless_macross_factory, fake_prices_1000,
                   n_splits=5, embargo_pct=0.01)
    calmars = [fm["metrics"]["calmar"] for fm in res.fold_metrics if fm["ok"]]
    sharpes = [fm["metrics"]["sharpe"] for fm in res.fold_metrics if fm["ok"]]
    mdds = [fm["metrics"]["mdd"] for fm in res.fold_metrics if fm["ok"]]

    assert res.mean_calmar == pytest.approx(float(np.mean(calmars)), rel=1e-6, abs=1e-6)
    assert res.median_calmar == pytest.approx(float(np.median(calmars)), rel=1e-6, abs=1e-6)
    assert res.std_calmar == pytest.approx(float(np.std(calmars, ddof=0)), rel=1e-6, abs=1e-6)
    assert res.mean_sharpe == pytest.approx(float(np.mean(sharpes)), rel=1e-6, abs=1e-6)
    assert res.median_sharpe == pytest.approx(float(np.median(sharpes)), rel=1e-6, abs=1e-6)
    assert res.std_sharpe == pytest.approx(float(np.std(sharpes, ddof=0)), rel=1e-6, abs=1e-6)
    assert res.mean_mdd == pytest.approx(float(np.mean(mdds)), rel=1e-6, abs=1e-6)


def test_invalid_n_splits():
    with pytest.raises(ValueError):
        PurgedKFold(n_splits=1)


def test_invalid_embargo_pct():
    with pytest.raises(ValueError):
        PurgedKFold(n_splits=5, embargo_pct=1.0)
    with pytest.raises(ValueError):
        PurgedKFold(n_splits=5, embargo_pct=-0.01)


def test_split_disjoint_test_sets(fake_prices_500):
    """Across folds, the union of test sets is the full positional range."""
    pkf = PurgedKFold(n_splits=5, embargo_pct=0.0)
    X = pd.DataFrame({"x": fake_prices_500.values}, index=fake_prices_500.index)
    test_concat = []
    for _, test_idx in pkf.split(X):
        test_concat.extend(test_idx.tolist())
    # full coverage and no duplicates
    assert sorted(test_concat) == list(range(len(X)))


def test_purged_cv_test_side_no_overlap(fake_prices_1000):
    """Train indices must not fall within `embargo` of ANY fold's test span.

    This is the symmetric-purge invariant: not just the current fold's
    embargo zone, but every other fold's pre/post-test buffer should also be
    purged out of the train set.
    """
    n_splits = 5
    embargo_pct = 0.05  # 5% embargo
    pkf = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct)
    X = pd.DataFrame({"x": fake_prices_1000.values}, index=fake_prices_1000.index)
    n = len(X)
    embargo_n = int(round(n * embargo_pct))

    splits = list(pkf.split(X))
    # Collect every fold's test range
    test_ranges = [(int(test_idx[0]), int(test_idx[-1])) for _, test_idx in splits]

    for fold_i, (train_idx, test_idx) in enumerate(splits):
        train_set = set(train_idx.tolist())
        for j, (lo, hi) in enumerate(test_ranges):
            # Pre-test buffer
            pre_lo = max(0, lo - embargo_n)
            pre_hi = lo - 1
            # Post-test buffer
            post_lo = hi + 1
            post_hi = min(n - 1, hi + embargo_n)
            if j == fold_i:
                # current fold: only post-buffer is checked by the original
                # one-sided embargo logic; pre-buffer used to be allowed.
                # With symmetric purge, BOTH sides should now be excluded
                # for OTHER folds (j != fold_i). For the current fold the
                # test span itself is already excluded from train.
                continue
            if pre_lo <= pre_hi:
                forbidden = set(range(pre_lo, pre_hi + 1))
                bad = train_set & forbidden
                assert not bad, (
                    f"fold {fold_i}: train contains pre-buffer of fold {j}: {bad}"
                )
            if post_lo <= post_hi:
                forbidden = set(range(post_lo, post_hi + 1))
                bad = train_set & forbidden
                assert not bad, (
                    f"fold {fold_i}: train contains post-buffer of fold {j}: {bad}"
                )


def test_factory_with_train_prices(fake_prices_500):
    """Factory accepting train_prices receives the train slice."""
    captured = {"calls": 0, "train_lens": []}

    def factory(train_prices: pd.Series):
        captured["calls"] += 1
        captured["train_lens"].append(len(train_prices))
        from quantforge.strategies.library.ma_cross import MACross
        return MACross(fast=10, slow=50)

    res = cv_score(factory, fake_prices_500, n_splits=5, embargo_pct=0.01)
    assert captured["calls"] == 5
    # All train slices non-trivial
    for tl in captured["train_lens"]:
        assert tl > 50
