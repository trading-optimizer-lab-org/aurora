"""Tests for the data layer: IS/OOS fence, snapshot freeze integration.

Run: uv run pytest aurora/tests/test_data_layer.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.core.data_layer import (
    IS_END,
    OOS_START,
    OOSGuard,
    load_asset,
    load_from_snapshot,
    split_is_oos,
)
from aurora.core.snapshots import DataSnapshot, IntegrityError, SnapshotStore


CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_cache_qf")
SPY_CACHE = os.path.join(CACHE_DIR, "SPY.parquet")


def _spy_required():
    if not os.path.exists(SPY_CACHE):
        pytest.skip("SPY parquet cache not present")


# ---------------------------------------------------------------------------
# IS/OOS fence
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_split_includes_fence_date():
    """IS slice must include 2012-12-31 (last business day of 2012);
    OOS slice must start 2013-01-02 (first business day of 2013, since
    Jan 1 is a market holiday).

    Marked ``integration``: relies on the SPY parquet cache produced by
    a real yfinance download; skipped automatically when absent.
    """
    _spy_required()
    is_only = load_asset("SPY", include_oos=False)
    last_is = is_only.index[-1]
    assert last_is == pd.Timestamp("2012-12-31"), (
        f"last IS day {last_is!r} must equal 2012-12-31 (off-by-one fence bug)"
    )

    with OOSGuard("post_ga_validation"):
        full = load_asset("SPY", include_oos=True)
    _, oos = split_is_oos(full)
    first_oos = oos.index[0]
    assert first_oos in (pd.Timestamp("2013-01-02"), pd.Timestamp("2013-01-03")), (
        f"first OOS day {first_oos!r} must be 2013-01-02 or 2013-01-03"
    )

    # No overlap: last IS strictly before first OOS
    assert last_is < first_oos


def test_is_end_constant_value():
    """The IS_END / OOS_START constants must remain at their canonical values
    so downstream lockbox logic still matches."""
    assert IS_END == "2012-12-31"
    assert OOS_START == "2013-01-01"


# ---------------------------------------------------------------------------
# freeze integration
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_data_layer_freeze_integration(tmp_path: Path, monkeypatch):
    """``load_asset(..., freeze=True)`` returns ``(prices, snapshot)`` and
    writes the parquet+index under the project's data_snapshots/ directory.

    Use a temp directory by monkeypatching PROJ so the test does not pollute
    the repo. Marked ``integration``: requires SPY parquet cache.
    """
    _spy_required()
    import aurora.core.data_layer as dl
    monkeypatch.setattr(dl, "PROJ", str(tmp_path))

    out = load_asset("SPY", include_oos=False, freeze=True, provenance="parquet")
    assert isinstance(out, tuple) and len(out) == 2
    prices, snap = out
    assert isinstance(prices, pd.Series)
    assert isinstance(snap, DataSnapshot)
    assert snap.symbol == "SPY"
    assert snap.provenance == "parquet"
    assert snap.locked is False
    assert os.path.exists(snap.data_path)

    # Round-trip via load_from_snapshot
    monkeypatch.setattr(dl, "PROJ", str(tmp_path))
    reloaded = load_from_snapshot(snap.sha256)
    assert len(reloaded) == len(prices)
    assert np.allclose(reloaded.to_numpy(), prices.to_numpy())


@pytest.mark.integration
def test_data_layer_freeze_oos_is_locked(tmp_path: Path, monkeypatch):
    """When freezing an OOS-bearing slice, the snapshot must be marked
    locked=True so that later loads require an explicit unlock guard.

    Marked ``integration``: requires SPY parquet cache.
    """
    _spy_required()
    import aurora.core.data_layer as dl
    monkeypatch.setattr(dl, "PROJ", str(tmp_path))

    with OOSGuard("post_ga_validation"):
        out = load_asset("SPY", include_oos=True, freeze=True,
                         provenance="parquet")
    prices, snap = out
    assert snap.locked is True

    # Without explicit_unlock, loading the locked snapshot must fail
    with pytest.raises(IntegrityError, match="locked"):
        load_from_snapshot(snap.sha256)

    # Inside explicit_unlock, it succeeds
    with OOSGuard("explicit_unlock"):
        reloaded = load_from_snapshot(snap.sha256)
    assert len(reloaded) == len(prices)
