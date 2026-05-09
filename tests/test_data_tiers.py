"""Tests for `core.data_tiers`: 5-tier protocol split boundaries."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.data_tiers import (
    FORWARD_START,
    IS_TRAIN_END,
    IS_VALID_END,
    IS_VALID_START,
    OOS_DEV_END,
    OOS_DEV_START,
    OOS_LOCKED_END,
    OOS_LOCKED_START,
    TierSplit,
    get_tier,
    split_by_tier,
)


def _full_prices() -> pd.Series:
    """Daily series spanning every tier with explicit boundary dates."""
    idx = pd.date_range("1995-01-01", "2025-06-30", freq="B")
    rng = np.random.default_rng(42)
    return pd.Series(100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, len(idx))),
                     index=idx, name="SYNTH")


def test_split_by_tier_returns_tier_split():
    s = _full_prices()
    out = split_by_tier(s)
    assert isinstance(out, TierSplit)


def test_split_by_tier_boundaries_is_train():
    s = _full_prices()
    out = split_by_tier(s)
    # IS_TRAIN ends at 2010-12-31 inclusive
    assert out.is_train.index.max() <= IS_TRAIN_END
    assert out.is_train.index.min() >= pd.Timestamp("1995-01-01")
    # next slice does not overlap
    assert out.is_valid.index.min() >= IS_VALID_START


def test_split_by_tier_boundaries_is_valid():
    s = _full_prices()
    out = split_by_tier(s)
    assert out.is_valid.index.min() >= IS_VALID_START
    assert out.is_valid.index.max() <= IS_VALID_END
    # IS_VALID is 2011-01-01..2012-12-31
    assert out.is_valid.index.max() <= pd.Timestamp("2012-12-31")
    # disjoint with is_train
    assert out.is_valid.index.min() > out.is_train.index.max()


def test_split_by_tier_boundaries_oos_dev():
    s = _full_prices()
    out = split_by_tier(s)
    assert out.oos_dev.index.min() >= OOS_DEV_START
    assert out.oos_dev.index.max() <= OOS_DEV_END
    # disjoint with oos_locked
    assert out.oos_dev.index.max() < out.oos_locked.index.min()


def test_split_by_tier_boundaries_oos_locked():
    s = _full_prices()
    out = split_by_tier(s)
    assert out.oos_locked.index.min() >= OOS_LOCKED_START
    assert out.oos_locked.index.max() <= OOS_LOCKED_END


def test_split_by_tier_boundaries_forward():
    s = _full_prices()
    out = split_by_tier(s)
    assert out.forward.index.min() >= FORWARD_START
    # forward upper bound only constrained by data; here ends 2025-06-30
    assert out.forward.index.max() <= pd.Timestamp("2025-06-30")


def test_split_by_tier_disjoint_and_complete():
    s = _full_prices()
    out = split_by_tier(s)
    total = (
        len(out.is_train)
        + len(out.is_valid)
        + len(out.oos_dev)
        + len(out.oos_locked)
        + len(out.forward)
    )
    assert total == len(s), "tiers must partition the input series"


def test_is_all_property_concats_train_and_valid():
    s = _full_prices()
    out = split_by_tier(s)
    expected_len = len(out.is_train) + len(out.is_valid)
    assert len(out.is_all) == expected_len
    assert out.is_all.index.max() <= IS_VALID_END


@pytest.mark.parametrize("tier,lo,hi", [
    ("IS_TRAIN", pd.Timestamp("1995-01-01"), IS_TRAIN_END),
    ("IS_VALID", IS_VALID_START, IS_VALID_END),
    ("OOS_DEV", OOS_DEV_START, OOS_DEV_END),
    ("OOS_LOCKED", OOS_LOCKED_START, OOS_LOCKED_END),
    ("FORWARD", FORWARD_START, pd.Timestamp("2025-06-30")),
])
def test_get_tier_returns_correct_slice(tier, lo, hi):
    s = _full_prices()
    out = get_tier(s, tier)
    assert isinstance(out, pd.Series)
    if len(out):
        assert out.index.min() >= lo
        assert out.index.max() <= hi


def test_split_handles_empty_tiers_gracefully():
    """Series limited to IS_TRAIN only -> other tiers empty."""
    idx = pd.date_range("1995-01-01", "2009-12-31", freq="B")
    s = pd.Series(np.arange(len(idx)), index=idx, name="X")
    out = split_by_tier(s)
    assert len(out.is_train) == len(s)
    assert len(out.is_valid) == 0
    assert len(out.oos_dev) == 0
    assert len(out.oos_locked) == 0
    assert len(out.forward) == 0
