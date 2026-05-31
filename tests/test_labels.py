"""Tests for triple-barrier labeling, meta-labeling and bet sizing.

Run: uv run --with scipy pytest aurora/tests/test_labels.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.ml.labels import (
    TripleBarrierResult,
    daily_volatility,
    triple_barrier_labels,
    meta_labels,
    bet_size_from_proba,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_idx():
    return pd.date_range("2020-01-01", periods=200, freq="B")


@pytest.fixture
def random_prices(flat_idx):
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.012, len(flat_idx))
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=flat_idx, name="P")


# ---------------------------------------------------------------------------
# daily_volatility
# ---------------------------------------------------------------------------

def test_daily_vol_basic(random_prices):
    vol = daily_volatility(random_prices, lookback=50)
    assert isinstance(vol, pd.Series)
    assert len(vol) == len(random_prices)
    finite = vol.dropna()
    assert len(finite) > 0
    assert (finite > 0).all()
    # Sanity: realized std of log returns is in roughly the same ballpark as ewma
    realized = np.log(random_prices).diff().std()
    assert 0.2 * realized < finite.mean() < 5 * realized


def test_daily_vol_validation():
    with pytest.raises(TypeError):
        daily_volatility([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        daily_volatility(pd.Series([1.0, 2.0]), lookback=1)


# ---------------------------------------------------------------------------
# triple_barrier_labels
# ---------------------------------------------------------------------------

def test_triple_barrier_pt_hit(flat_idx):
    """Monotonically up price -> profit barrier hits first -> +1 label."""
    p = pd.Series(100.0 * (1.0 + 0.01) ** np.arange(len(flat_idx)),
                  index=flat_idx, name="up")
    vol = pd.Series(0.01, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10], flat_idx[50]])
    res = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=20,
        vol=vol,
    )
    assert isinstance(res, TripleBarrierResult)
    assert (res.labels == 1).all()
    assert res.touch_times["pt_touch"].notna().all()
    assert (res.returns > 0).all()


def test_triple_barrier_sl_hit(flat_idx):
    """Monotonically down price -> stop barrier hits first -> -1 label."""
    p = pd.Series(100.0 * (1.0 - 0.01) ** np.arange(len(flat_idx)),
                  index=flat_idx, name="down")
    vol = pd.Series(0.01, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10], flat_idx[60]])
    res = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=20,
        vol=vol,
    )
    assert (res.labels == -1).all()
    assert res.touch_times["sl_touch"].notna().all()
    assert (res.returns < 0).all()


def test_triple_barrier_vertical(flat_idx):
    """Tiny moves vs huge barriers -> vertical barrier dominates -> 0 label."""
    rng = np.random.default_rng(0)
    # microscopic price drift, way smaller than the barriers
    rets = rng.normal(0.0, 1e-5, len(flat_idx))
    p = pd.Series(100.0 * np.cumprod(1.0 + rets), index=flat_idx)
    # huge vol -> barriers extremely wide -> never touched
    vol = pd.Series(0.5, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[5], flat_idx[40], flat_idx[100]])
    res = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
    )
    assert (res.labels == 0).all()
    assert res.touch_times["pt_touch"].isna().all()
    assert res.touch_times["sl_touch"].isna().all()
    assert res.touch_times["t1_touch"].notna().all()


def test_triple_barrier_adaptive_vol(flat_idx):
    """Higher vol -> wider barriers -> labels less likely to fire."""
    p = pd.Series(100.0 * (1.0 + 0.005) ** np.arange(len(flat_idx)),
                  index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10], flat_idx[40], flat_idx[80]])

    # narrow barriers (low vol)
    res_narrow = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=30,
        vol=pd.Series(0.005, index=flat_idx),
    )
    # wide barriers (10x vol)
    res_wide = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=30,
        vol=pd.Series(0.05, index=flat_idx),
    )
    n_pt_narrow = res_narrow.touch_times["pt_touch"].notna().sum()
    n_pt_wide = res_wide.touch_times["pt_touch"].notna().sum()
    # wider barriers should fire fewer (or equal) PT touches over the same drift
    assert n_pt_wide <= n_pt_narrow


def test_triple_barrier_min_return(flat_idx):
    """min_return zeroes-out tiny touches."""
    p = pd.Series(100.0 * (1.0 + 0.001) ** np.arange(len(flat_idx)),
                  index=flat_idx)
    vol = pd.Series(0.001, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10], flat_idx[50]])
    res_lo = triple_barrier_labels(
        p, events, pt_sl_factors=(1.0, 1.0), holding_period_days=10,
        vol=vol, min_return=0.0,
    )
    res_hi = triple_barrier_labels(
        p, events, pt_sl_factors=(1.0, 1.0), holding_period_days=10,
        vol=vol, min_return=0.5,  # huge threshold -> nothing qualifies
    )
    assert (res_hi.labels == 0).all()
    # at least one of the loose-threshold labels is non-zero
    assert (res_lo.labels != 0).any()


def test_triple_barrier_empty_events(random_prices):
    res = triple_barrier_labels(
        random_prices, pd.DatetimeIndex([]),
        pt_sl_factors=(1.0, 1.0), holding_period_days=5,
    )
    assert len(res.labels) == 0
    assert len(res.touch_times) == 0


def test_triple_barrier_events_max_index_guard(flat_idx):
    """events_max_index raises if any event timestamp exceeds the cutoff.

    This guards against lookahead in the upstream feature that produced the
    events: callers must declare the cutoff date through which their feature
    is causal, and any later events are flagged as bias.
    """
    p = pd.Series(100.0 * (1.0 + 0.005) ** np.arange(len(flat_idx)),
                  index=flat_idx)
    vol = pd.Series(0.01, index=flat_idx)
    cutoff = flat_idx[100]

    # Below-cutoff events must work fine.
    safe_events = pd.DatetimeIndex([flat_idx[10], flat_idx[50], flat_idx[100]])
    res = triple_barrier_labels(
        p, safe_events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=20,
        vol=vol,
        events_max_index=cutoff,
    )
    assert len(res.labels) == 3

    # An event past the cutoff must raise.
    leaky_events = pd.DatetimeIndex(
        [flat_idx[10], flat_idx[50], flat_idx[150]]
    )
    with pytest.raises(ValueError, match="events_max_index"):
        triple_barrier_labels(
            p, leaky_events,
            pt_sl_factors=(1.0, 1.0),
            holding_period_days=20,
            vol=vol,
            events_max_index=cutoff,
        )

    # And without the guard it does not raise (backward compatible).
    res2 = triple_barrier_labels(
        p, leaky_events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=20,
        vol=vol,
    )
    assert len(res2.labels) == 3


def test_triple_barrier_excludes_t0(flat_idx):
    """t0 itself is excluded from barrier search (forward-looking only).

    Build a series whose price at t0 already violates the upper barrier
    by construction; the touch must be recorded at the *next* bar (which
    also violates), not at t0 itself.
    """
    n = len(flat_idx)
    p = pd.Series(100.0, index=flat_idx).copy()
    # set a steady price, then a level above any plausible barrier from bar
    # of t0 onwards: t0 already sits above the barrier. The first bar after
    # t0 also sits above the barrier; the test asserts the touch is the
    # *next* bar, not t0.
    t0_pos = 50
    p.iloc[t0_pos:] = 110.0  # +10% jump at t0 and held thereafter

    # Vol is calibrated so the 1-sigma upper barrier from p0 = 110 sits at
    # 110 * (1 + 0.01) = 111.10. Since the post-t0 price is 110 (equal to p0),
    # the barrier is NOT crossed strictly; we want a case where it IS crossed
    # the bar after t0 but t0 itself is at p0 = 110 (so trivially crossing the
    # entry-relative barrier means looking at t0 == upper, which counts as a
    # touch only if t0 is searched). Use a price path that is exactly p0 at
    # t0 then jumps above the barrier on the next bar.
    p.iloc[t0_pos] = 100.0
    p.iloc[t0_pos + 1:] = 102.0  # next bar +2%

    vol = pd.Series(0.01, index=flat_idx)  # 1-sigma barrier at +/-1%
    events = pd.DatetimeIndex([flat_idx[t0_pos]])
    res = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
    )
    # PT must hit on bar t0+1 (102 > 101), NOT on t0 itself (price = 100).
    pt_touch = res.touch_times["pt_touch"].iloc[0]
    assert pt_touch == flat_idx[t0_pos + 1]
    assert pt_touch != flat_idx[t0_pos]
    # And label is +1 (PT).
    assert res.labels.iloc[0] == 1

    # Now an aggressive case: t0 price already above the future barrier
    # because barrier is computed from p0, so the entry bar trivially does
    # not violate. But the *next* bar violates; touch must be next bar.
    p2 = pd.Series(100.0, index=flat_idx).copy()
    p2.iloc[t0_pos] = 100.0
    p2.iloc[t0_pos + 1] = 200.0  # huge jump on next bar
    p2.iloc[t0_pos + 2:] = 200.0
    res2 = triple_barrier_labels(
        p2, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
    )
    assert res2.touch_times["pt_touch"].iloc[0] == flat_idx[t0_pos + 1]


def test_triple_barrier_slippage_applied(flat_idx):
    """slippage_bps reduces realized return at PT touches by exactly that amount.

    Same trade with 0 vs 5 bps slippage: the realized return on the PT-touch
    case must differ by exactly 5e-4 (slippage subtracts on a long PT).
    """
    n = len(flat_idx)
    p = pd.Series(100.0 * (1.0 + 0.01) ** np.arange(n), index=flat_idx)
    vol = pd.Series(0.005, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10]])

    res_clean = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=0.0,
    )
    res_slip = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=5.0,
    )
    # Touch bar is identical (slippage doesn't change which barrier hits first).
    assert (
        res_clean.touch_times["pt_touch"].iloc[0]
        == res_slip.touch_times["pt_touch"].iloc[0]
    )
    # Both must be PT touches.
    assert res_clean.labels.iloc[0] == 1
    assert res_slip.labels.iloc[0] == 1
    # Realized return delta = exactly 5 bps (long PT: realized -= slip).
    delta = res_clean.returns.iloc[0] - res_slip.returns.iloc[0]
    assert np.isclose(delta, 5e-4, atol=1e-12)

    # SL leg: long, falling price -> SL hits, realized < quoted (more negative).
    p_dn = pd.Series(100.0 * (1.0 - 0.01) ** np.arange(n), index=flat_idx)
    res_clean_sl = triple_barrier_labels(
        p_dn, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=0.0,
    )
    res_slip_sl = triple_barrier_labels(
        p_dn, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=5.0,
    )
    assert res_clean_sl.labels.iloc[0] == -1
    assert res_slip_sl.labels.iloc[0] == -1
    # Long SL: realized goes from r to r - slip (more negative).
    delta_sl = res_clean_sl.returns.iloc[0] - res_slip_sl.returns.iloc[0]
    assert np.isclose(delta_sl, 5e-4, atol=1e-12)

    # Short side: PT touched on a falling price; realized return on short
    # entry should be improved by -slippage (we subtract favorably -> +slip).
    res_short = triple_barrier_labels(
        p_dn, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=5.0,
        side=-1,
    )
    res_short_clean = triple_barrier_labels(
        p_dn, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=10,
        vol=vol,
        slippage_bps=0.0,
        side=-1,
    )
    # short slip: realized = r + slip (since slippage_bps adds for short SL).
    delta_short = res_short.returns.iloc[0] - res_short_clean.returns.iloc[0]
    assert np.isclose(delta_short, 5e-4, atol=1e-12)


def test_triple_barrier_slippage_validation(random_prices):
    events = pd.DatetimeIndex([random_prices.index[10]])
    with pytest.raises(ValueError, match="slippage_bps"):
        triple_barrier_labels(
            random_prices, events,
            pt_sl_factors=(1.0, 1.0),
            holding_period_days=5,
            slippage_bps=-1.0,
        )
    with pytest.raises(ValueError, match="side"):
        triple_barrier_labels(
            random_prices, events,
            pt_sl_factors=(1.0, 1.0),
            holding_period_days=5,
            side=0,
        )


def test_triple_barrier_no_slippage_on_vertical(flat_idx):
    """Slippage must NOT alter the realized return at vertical-barrier exits."""
    n = len(flat_idx)
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 1e-5, n)  # tiny noise
    p = pd.Series(100.0 * np.cumprod(1.0 + rets), index=flat_idx)
    vol = pd.Series(0.5, index=flat_idx)  # huge barrier -> vertical wins
    events = pd.DatetimeIndex([flat_idx[5], flat_idx[40]])

    res_clean = triple_barrier_labels(
        p, events, pt_sl_factors=(1.0, 1.0), holding_period_days=10,
        vol=vol, slippage_bps=0.0,
    )
    res_slip = triple_barrier_labels(
        p, events, pt_sl_factors=(1.0, 1.0), holding_period_days=10,
        vol=vol, slippage_bps=10.0,
    )
    # All labels are 0 (vertical) -> returns must be identical.
    assert (res_clean.labels == 0).all()
    assert (res_slip.labels == 0).all()
    np.testing.assert_allclose(
        res_clean.returns.to_numpy(),
        res_slip.returns.to_numpy(),
        atol=1e-15,
    )


# ---------------------------------------------------------------------------
# meta_labels
# ---------------------------------------------------------------------------

def test_meta_labels_correct():
    idx = pd.date_range("2020-01-01", periods=4, freq="D")
    primary = pd.Series([1, 1, -1, -1], index=idx)
    rets = pd.Series([0.02, 0.03, -0.01, -0.04], index=idx)
    meta = meta_labels(primary, rets, threshold=0.0)
    assert (meta == 1).all()


def test_meta_labels_incorrect():
    idx = pd.date_range("2020-01-01", periods=4, freq="D")
    primary = pd.Series([1, 1, -1, -1], index=idx)
    rets = pd.Series([-0.01, -0.02, 0.01, 0.05], index=idx)
    meta = meta_labels(primary, rets, threshold=0.0)
    assert (meta == 0).all()


def test_meta_labels_threshold():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    primary = pd.Series([1, 1, 1], index=idx)
    rets = pd.Series([0.001, 0.05, 0.1], index=idx)
    meta = meta_labels(primary, rets, threshold=0.01)
    # only returns above threshold count as "correct"
    assert meta.tolist() == [0, 1, 1]


def test_meta_labels_zero_signal_is_zero():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    primary = pd.Series([0, 1, -1], index=idx)
    rets = pd.Series([0.05, 0.05, -0.05], index=idx)
    meta = meta_labels(primary, rets)
    assert meta.tolist() == [0, 1, 1]


# ---------------------------------------------------------------------------
# bet_size_from_proba
# ---------------------------------------------------------------------------

def test_bet_size_sigmoid_bounds():
    rng = np.random.default_rng(0)
    p = pd.Series(rng.uniform(0.0, 1.0, 500))
    sizes = bet_size_from_proba(p, threshold=0.5, method="sigmoid")
    assert sizes.between(-1.0, 1.0).all()


def test_bet_size_proba_05():
    """Probability == threshold -> bet size == 0."""
    p = pd.Series([0.5, 0.5, 0.5])
    s_sig = bet_size_from_proba(p, threshold=0.5, method="sigmoid")
    s_lin = bet_size_from_proba(p, threshold=0.5, method="linear")
    s_pow = bet_size_from_proba(p, threshold=0.5, method="power")
    assert np.allclose(s_sig.values, 0.0, atol=1e-6)
    assert np.allclose(s_lin.values, 0.0, atol=1e-12)
    assert np.allclose(s_pow.values, 0.0, atol=1e-12)


def test_bet_size_proba_1():
    """Probability ~1 -> max long size; probability ~0 -> max short size."""
    p_hi = pd.Series([0.999999])
    p_lo = pd.Series([0.000001])
    for method in ("sigmoid", "linear", "power"):
        s_hi = bet_size_from_proba(p_hi, threshold=0.5, method=method).iloc[0]
        s_lo = bet_size_from_proba(p_lo, threshold=0.5, method=method).iloc[0]
        assert s_hi > 0.95, f"{method}: expected near +1 long, got {s_hi}"
        assert s_lo < -0.95, f"{method}: expected near -1 short, got {s_lo}"


def test_bet_size_monotonic():
    """Higher probability -> larger (more positive) size for sigmoid method."""
    p = pd.Series(np.linspace(0.05, 0.95, 19))
    sizes = bet_size_from_proba(p, threshold=0.5, method="sigmoid")
    assert (sizes.diff().dropna() >= -1e-9).all()


def test_bet_size_invalid_method():
    p = pd.Series([0.6, 0.7])
    with pytest.raises(ValueError):
        bet_size_from_proba(p, method="bogus")
    with pytest.raises(ValueError):
        bet_size_from_proba(p, threshold=0.0)
    with pytest.raises(ValueError):
        bet_size_from_proba(p, threshold=1.0)


# ---------------------------------------------------------------------------
# Audit fix: triple-barrier slicing must be unique-index + positional
# ---------------------------------------------------------------------------


def test_triple_barrier_unique_index_required():
    """Duplicate-indexed prices must be rejected up front (audit fix #1)."""
    idx = pd.DatetimeIndex(
        ["2020-01-01", "2020-01-02", "2020-01-02", "2020-01-03"]
    )
    p = pd.Series([100.0, 101.0, 101.5, 102.0], index=idx)
    events = pd.DatetimeIndex([idx[0]])
    with pytest.raises(ValueError, match="unique"):
        triple_barrier_labels(p, events, holding_period_days=2,
                              vol=pd.Series(0.01, index=idx))


def test_triple_barrier_get_loc_path():
    """Positional barrier-search window matches a manual slice via get_loc.

    Construct a strictly monotone up price so the PT must be hit at exactly
    the bar where price first crosses ``p0 * (1 + sigma)``. The label and the
    PT-touch timestamp must agree with manual computation that uses the same
    positional slice.
    """
    idx = pd.date_range("2020-06-01", periods=30, freq="B")
    p = pd.Series(100.0 * (1.0 + 0.005) ** np.arange(len(idx)), index=idx)
    sigma = 0.02
    vol = pd.Series(sigma, index=idx)
    events = pd.DatetimeIndex([idx[5]])
    res = triple_barrier_labels(
        p, events,
        pt_sl_factors=(1.0, 1.0),
        holding_period_days=15,
        vol=vol,
    )
    # Manual: positional slice from event index, look for first cross.
    i0 = idx.get_loc(idx[5])
    p0 = float(p.iloc[i0])
    upper = p0 * (1.0 + sigma)
    future = p.iloc[i0 + 1:]
    expected_pt = future.index[future.values >= upper][0]
    assert res.touch_times.loc[idx[5], "pt_touch"] == expected_pt
    assert int(res.labels.iloc[0]) == 1


def test_triple_barrier_nan_policy_raise():
    """nan_policy='raise' rejects events whose vol is non-finite."""
    idx = pd.date_range("2020-01-01", periods=20, freq="B")
    p = pd.Series(100.0 + np.arange(len(idx)) * 0.1, index=idx)
    vol = pd.Series(np.nan, index=idx)  # all NaN
    events = pd.DatetimeIndex([idx[5], idx[10]])
    with pytest.raises(ValueError, match="non-finite vol"):
        triple_barrier_labels(p, events, vol=vol, nan_policy="raise",
                              holding_period_days=3)


def test_triple_barrier_valid_vol_column(flat_idx):
    """Audit fix: touch_times exposes a ``valid_vol`` boolean column that
    is True only for events with a finite, positive vol estimate (where
    barriers were actually sized).
    """
    n = len(flat_idx)
    p = pd.Series(100.0 + np.arange(n) * 0.1, index=flat_idx)
    # Mix of valid and missing vol observations.
    vol = pd.Series(0.01, index=flat_idx)
    vol.iloc[40:55] = np.nan
    events = pd.DatetimeIndex(
        [flat_idx[10], flat_idx[45], flat_idx[60], flat_idx[80]]
    )
    res = triple_barrier_labels(
        p, events, pt_sl_factors=(1.0, 1.0), holding_period_days=10, vol=vol
    )
    assert "valid_vol" in res.touch_times.columns
    # The event at idx 45 falls in the NaN-vol stretch -> not valid.
    assert bool(res.touch_times.loc[flat_idx[10], "valid_vol"]) is True
    assert bool(res.touch_times.loc[flat_idx[45], "valid_vol"]) is False
    assert bool(res.touch_times.loc[flat_idx[60], "valid_vol"]) is True
    assert bool(res.touch_times.loc[flat_idx[80], "valid_vol"]) is True


def test_triple_barrier_slippage_signed_pnl_identity(flat_idx):
    """Audit fix: slippage should reduce realized PnL by exactly ``slip``
    regardless of the side. The unified expression
    ``ret_adj = ret - side * slip`` implies
    ``side * ret_adj = side * ret - slip``, i.e. signed PnL drops by exactly
    ``slip`` for both longs and shorts on either barrier.
    """
    n = len(flat_idx)
    p_up = pd.Series(100.0 * (1.0 + 0.01) ** np.arange(n), index=flat_idx)
    p_dn = pd.Series(100.0 * (1.0 - 0.01) ** np.arange(n), index=flat_idx)
    vol = pd.Series(0.005, index=flat_idx)
    events = pd.DatetimeIndex([flat_idx[10]])
    slip_bps = 7.0
    slip = slip_bps / 10_000.0

    for side, p_path in ((+1, p_up), (-1, p_dn), (+1, p_dn), (-1, p_up)):
        clean = triple_barrier_labels(
            p_path, events,
            pt_sl_factors=(1.0, 1.0), holding_period_days=10,
            vol=vol, slippage_bps=0.0, side=side,
        )
        slipped = triple_barrier_labels(
            p_path, events,
            pt_sl_factors=(1.0, 1.0), holding_period_days=10,
            vol=vol, slippage_bps=slip_bps, side=side,
        )
        signed_pnl_clean = side * float(clean.returns.iloc[0])
        signed_pnl_slipped = side * float(slipped.returns.iloc[0])
        # Realized signed PnL drops by exactly slip on every barrier+side.
        assert np.isclose(
            signed_pnl_clean - signed_pnl_slipped, slip, atol=1e-12
        ), f"side={side} path={p_path.iloc[-1]:.3f} mismatch"


def test_meta_labels_nan_warns():
    """meta_labels emits a UserWarning when >5% of returns are non-finite."""
    n = 100
    sig = pd.Series(np.tile([1, -1], n // 2))
    rets = pd.Series(np.full(n, np.nan))  # 100% NaN
    with pytest.warns(UserWarning, match="non-finite"):
        out = meta_labels(sig, rets, threshold=0.0, nan_warn_threshold=0.05)
    assert (out == 0).all()
