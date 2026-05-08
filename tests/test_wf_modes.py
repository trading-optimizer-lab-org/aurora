"""Tests for walk-forward window auto-generation modes."""
from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
import pytest

from quantforge.validation.walk_forward import (
    WFWindow, generate_wf_windows, walk_forward,
)


@pytest.fixture
def fake_prices_1000():
    idx = pd.date_range("2010-01-01", periods=1000, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.012, 1000)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def test_rolling_4_windows(fake_prices_1000):
    """Rolling mode: 4 windows, IS slides forward at fixed length."""
    wins = generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=0.20, mode="rolling")
    assert len(wins) == 4

    # Each IS window has the same length (fixed-length rolling)
    is_lens = []
    for w in wins:
        is_slice = fake_prices_1000.loc[w.is_start:w.is_end]
        is_lens.append(len(is_slice))
    assert max(is_lens) - min(is_lens) <= 1  # equal length up to rounding

    # IS slides forward: each is_start later than (or equal to) prior
    for a, b in zip(wins, wins[1:]):
        assert _ts(b.is_start) >= _ts(a.is_start)
        assert _ts(b.is_start) > _ts(a.is_start)  # actually strictly forward in rolling


def test_expanding(fake_prices_1000):
    """Expanding mode: IS always starts at start_date and grows."""
    wins = generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=0.20, mode="expanding")
    assert len(wins) == 4

    first_start = wins[0].is_start
    is_lens = []
    for w in wins:
        assert w.is_start == first_start  # anchor at the beginning
        is_slice = fake_prices_1000.loc[w.is_start:w.is_end]
        is_lens.append(len(is_slice))

    # Lengths strictly increase
    for a, b in zip(is_lens, is_lens[1:]):
        assert b > a


def test_anchored(fake_prices_1000):
    """Anchored mode: IS identical for every window."""
    wins = generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=0.20, mode="anchored")
    assert len(wins) == 4

    is_pairs = {(w.is_start, w.is_end) for w in wins}
    assert len(is_pairs) == 1  # all share the same IS span


def test_oos_non_overlap(fake_prices_1000):
    """OOS periods do not overlap across modes."""
    for mode in ("rolling", "expanding", "anchored"):
        wins = generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=0.20, mode=mode)
        for a, b in zip(wins, wins[1:]):
            assert _ts(a.oos_end) < _ts(b.oos_start), f"overlap in mode={mode}"


def test_oos_covers_range(fake_prices_1000):
    """Union of OOS windows = expected end-portion of the data."""
    n = len(fake_prices_1000)
    oos_pct = 0.20
    expected_oos_bars = int(round(n * oos_pct))

    for mode in ("rolling", "expanding", "anchored"):
        wins = generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=oos_pct, mode=mode)
        # Sum bars across OOS slices (non-overlap guaranteed by previous test)
        total_bars = 0
        for w in wins:
            total_bars += len(fake_prices_1000.loc[w.oos_start:w.oos_end])
        assert total_bars == expected_oos_bars

        # Last OOS_end equals last bar of full range
        assert _ts(wins[-1].oos_end) == fake_prices_1000.index[-1]
        # First OOS_start sits at index n - expected_oos_bars
        first_oos_idx = fake_prices_1000.index.get_loc(_ts(wins[0].oos_start))
        assert first_oos_idx == n - expected_oos_bars


def test_min_bars_warning():
    """Warn when any IS or OOS slice is shorter than min_bars."""
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    prices = pd.Series(100.0 + np.arange(200) * 0.1, index=idx)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # 200 bars, 4 windows, oos_pct=0.20 => 40 OOS bars => 10 per OOS
        # IS=160 bars (>=100, ok); OOS=10 (<100, warn)
        generate_wf_windows(prices, n_windows=4, oos_pct=0.20, mode="rolling", min_bars=100)
    msgs = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("OOS" in m and "100" in m for m in msgs)


def test_walk_forward_auto_generates_windows(fake_prices_1000):
    """walk_forward(windows=None, mode=...) auto-generates and runs."""
    from quantforge.strategies.library import MACross

    def factory():
        return MACross(fast=10, slow=50)

    res = walk_forward(factory, fake_prices_1000, windows=None,
                       mode="rolling", n_windows=4, oos_pct=0.20)
    assert res.n_total == 4
    assert 0 <= res.n_pass <= 4


def test_walk_forward_explicit_windows_still_works(fake_prices_1000):
    """Backward compatibility: explicit windows list still works."""
    from quantforge.strategies.library import MACross

    def factory():
        return MACross(fast=10, slow=50)

    wins = [
        WFWindow("W1", "2010-01-01", "2011-12-31", "2012-01-01", "2012-12-31"),
        WFWindow("W2", "2010-01-01", "2012-12-31", "2013-01-01", "2013-12-31"),
    ]
    res = walk_forward(factory, fake_prices_1000, wins)
    assert res.n_total == 2


def test_walk_forward_requires_windows_or_mode(fake_prices_1000):
    """Calling walk_forward with neither windows nor mode raises."""
    from quantforge.strategies.library import MACross

    with pytest.raises(ValueError):
        walk_forward(lambda: MACross(), fake_prices_1000, windows=None)


def test_invalid_mode_raises(fake_prices_1000):
    with pytest.raises(ValueError):
        generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=0.20, mode="bogus")


def test_invalid_oos_pct_raises(fake_prices_1000):
    with pytest.raises(ValueError):
        generate_wf_windows(fake_prices_1000, n_windows=4, oos_pct=1.5, mode="rolling")


def test_expanding_no_oos_overlap(fake_prices_1000):
    """Expanding mode with many windows: every pair of OOS slices is disjoint.

    Stress-test the non-overlap invariant at the positional level: OOS_start[k+1]
    must be strictly greater than OOS_end[k] for every k.
    """
    for n_w in (3, 4, 8, 12):
        wins = generate_wf_windows(
            fake_prices_1000, n_windows=n_w, oos_pct=0.30, mode="expanding"
        )
        assert len(wins) == n_w
        # Pairwise disjointness via positional indices
        idx = fake_prices_1000.index
        oos_ranges = []
        for w in wins:
            lo = idx.get_loc(_ts(w.oos_start))
            hi = idx.get_loc(_ts(w.oos_end))
            oos_ranges.append((lo, hi))
        for i in range(len(oos_ranges)):
            for j in range(i + 1, len(oos_ranges)):
                a_lo, a_hi = oos_ranges[i]
                b_lo, b_hi = oos_ranges[j]
                # disjoint: a_hi < b_lo or b_hi < a_lo
                assert a_hi < b_lo or b_hi < a_lo, (
                    f"OOS overlap n_w={n_w}: window {i}=[{a_lo},{a_hi}] window {j}=[{b_lo},{b_hi}]"
                )
