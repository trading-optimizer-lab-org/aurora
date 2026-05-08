"""Tests for ml.features_pipeline.

Run: uv run pytest quantforge/tests/test_features_pipeline.py -v
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from quantforge.ml.features_pipeline import (
    FeaturePipeline,
    FeaturePipelineConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 1000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    rets = rng.normal(0.0004, 0.012, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    span = rng.uniform(0.002, 0.012, n)
    high = close * (1.0 + span)
    low = close * (1.0 - span)
    volume = rng.integers(1_000, 10_000, n).astype(float)
    return pd.DataFrame(
        {"close": close, "high": high, "low": low, "volume": volume},
        index=idx,
    )


@pytest.fixture
def ohlcv():
    return _make_ohlcv(1000, seed=7)


@pytest.fixture
def close_only():
    df = _make_ohlcv(800, seed=11)
    return df[["close"]]


# ---------------------------------------------------------------------------
# 1. shape / basic flow
# ---------------------------------------------------------------------------

def test_fit_transform_shape(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 10, 20),
        return_lags=(1, 2, 5),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)

    assert isinstance(feats, pd.DataFrame)
    assert len(feats) == len(ohlcv)
    # Same DatetimeIndex
    assert (feats.index == ohlcv.index).all()
    # multiple feature columns
    assert feats.shape[1] >= 10
    # No infinities
    assert not np.isinf(feats.to_numpy(dtype=float)).any()


# ---------------------------------------------------------------------------
# 2. anti-lookahead
# ---------------------------------------------------------------------------

def test_no_lookahead(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 20),
        return_lags=(1, 5),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=60,
    )
    pipe = FeaturePipeline(cfg)
    feats_orig = pipe.fit_transform(ohlcv)

    # Pick a probe time well past warm-up.
    t = 500

    # Mutate everything strictly after t and recompute features.
    perturbed = ohlcv.copy()
    rng = np.random.default_rng(123)
    perturbed.iloc[t + 1:, perturbed.columns.get_loc("close")] *= (
        1.0 + rng.normal(0, 0.05, len(perturbed) - (t + 1))
    )
    perturbed.iloc[t + 1:, perturbed.columns.get_loc("high")] *= (
        1.0 + rng.normal(0, 0.05, len(perturbed) - (t + 1))
    )
    perturbed.iloc[t + 1:, perturbed.columns.get_loc("low")] *= (
        1.0 + rng.normal(0, 0.05, len(perturbed) - (t + 1))
    )

    pipe2 = FeaturePipeline(cfg)
    feats_perturbed = pipe2.fit_transform(perturbed)

    # Row at t must be identical (allowing NaN==NaN).
    row_orig = feats_orig.iloc[t]
    row_pert = feats_perturbed.iloc[t]
    pd.testing.assert_series_equal(row_orig, row_pert, check_names=False)


# ---------------------------------------------------------------------------
# 3. rolling z-score window: only past N bars
# ---------------------------------------------------------------------------

def test_rolling_zscore_window(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=False,
        include_volatility=False,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=50,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)

    # Pick a column produced before standardization for spot-checking.
    col = feats.columns[0]

    # Recompute the raw feature, then manually z-score with window=50.
    raw = pipe._compute_raw(ohlcv)[col]
    mean = raw.rolling(50, min_periods=50).mean()
    std = raw.rolling(50, min_periods=50).std(ddof=1)
    expected = (raw - mean) / std

    # Compare on the rows that have enough warm-up for both rolling and z.
    valid = expected.notna() & feats[col].notna()
    assert valid.sum() > 100  # plenty of valid rows
    np.testing.assert_allclose(
        feats[col][valid].to_numpy(),
        expected[valid].to_numpy(),
        rtol=1e-9,
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# 4. feature_names matches columns
# ---------------------------------------------------------------------------

def test_feature_names_match_columns(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 10),
        return_lags=(1, 2),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)
    assert pipe.feature_names() == feats.columns.tolist()


# ---------------------------------------------------------------------------
# 5. warmup NaN
# ---------------------------------------------------------------------------

def test_warmup_nan(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 10, 20, 60),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=False,
        include_volatility=False,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)

    max_w = max(cfg.rolling_windows)
    # The first column we produce per window block is roll_mean_W on returns,
    # which itself loses one bar to pct_change; first non-NaN appears at
    # row index = max_w (zero-based) for window=max_w.
    col = f"roll_mean_{max_w}"
    # Ensure at least max_w-1 rows are NaN.
    assert feats[col].iloc[: max_w - 1].isna().all()
    # And the column is non-empty after warm-up.
    assert feats[col].iloc[max_w:].notna().sum() > 0


# ---------------------------------------------------------------------------
# 6. microstructure optional
# ---------------------------------------------------------------------------

def test_microstructure_with_volume(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=True,
        include_volatility=False,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)
    assert "cs_spread" in feats.columns
    assert "signed_volume" in feats.columns


def test_microstructure_missing_volume_warns(close_only):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=True,
        include_volatility=False,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        feats = pipe.fit_transform(close_only)
        msgs = [str(x.message) for x in w]
        assert any("microstructure" in m.lower() for m in msgs)
    assert "cs_spread" not in feats.columns
    assert "signed_volume" not in feats.columns


# ---------------------------------------------------------------------------
# 7. flags: technicals off
# ---------------------------------------------------------------------------

def test_no_technicals_flag(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=False,
        include_volatility=False,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(ohlcv)
    for forbidden in ("rsi_14", "macd_line", "macd_signal", "macd_hist",
                      "bb_upper", "bb_middle", "bb_lower", "bb_width"):
        assert forbidden not in feats.columns


# ---------------------------------------------------------------------------
# 8. standardize='none' leaves raw features
# ---------------------------------------------------------------------------

def test_standardize_none(ohlcv):
    cfg_raw = FeaturePipelineConfig(
        rolling_windows=(5, 10),
        return_lags=(1,),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=False,
    )
    cfg_none = FeaturePipelineConfig(
        rolling_windows=(5, 10),
        return_lags=(1,),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=True,
        standardize_method="none",
    )
    feats_raw = FeaturePipeline(cfg_raw).fit_transform(ohlcv)
    feats_none = FeaturePipeline(cfg_none).fit_transform(ohlcv)
    pd.testing.assert_frame_equal(feats_raw, feats_none)


# ---------------------------------------------------------------------------
# 9. fit_transform == fit then transform
# ---------------------------------------------------------------------------

def test_fit_transform_consistency(ohlcv):
    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 20),
        return_lags=(1, 2, 5),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=100,
    )
    p1 = FeaturePipeline(cfg).fit_transform(ohlcv)
    pipe2 = FeaturePipeline(cfg).fit(ohlcv)
    p2 = pipe2.transform(ohlcv)
    pd.testing.assert_frame_equal(p1, p2)


# ---------------------------------------------------------------------------
# 10. transform on new data: no fit-leakage
# ---------------------------------------------------------------------------

def test_transform_new_data(ohlcv):
    """Pipeline fitted on train data must transform unseen test data without
    leaking either statistic. Rolling z-score uses only the test window's own
    past bars, so feeding train-then-test concatenation must give the same
    test-segment values as transforming the same concatenation directly.
    """
    train = ohlcv.iloc[:600]
    test = ohlcv.iloc[600:]

    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 20),
        return_lags=(1, 5),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=60,
    )
    pipe = FeaturePipeline(cfg)
    pipe.fit(train)

    full = pd.concat([train, test])
    feats_full = pipe.transform(full)
    # Transform test alone. Without train context the early test bars miss
    # warm-up. We compare on the post-warmup tail only.
    feats_test_solo = pipe.transform(test)

    # Test segment of full transform should be exactly the slice of full output.
    feats_test_via_full = feats_full.iloc[600:]
    assert (feats_test_via_full.index == test.index).all()

    # Pipeline columns and order must match what fit produced.
    assert feats_test_via_full.columns.tolist() == pipe.feature_names()
    assert feats_test_solo.columns.tolist() == pipe.feature_names()

    # Tail rows that have full warm-up in *both* should agree on their own
    # rolling stats (they don't depend on the previous train data, since the
    # window is 60 bars and we look at rows >= 600 + 100 i.e. far past warm-up
    # of the solo test transform too).
    tail_via_full = feats_test_via_full.iloc[200:]
    tail_solo = feats_test_solo.iloc[200:]

    # Long-memory features (RSI Wilder smoothing, MACD/EWMA recursions) seed
    # from the first input bar, so they legitimately diverge when the start of
    # the input window differs. Test their tails with a loose tolerance.
    long_memory = {"rsi_14", "macd_line", "macd_signal", "macd_hist",
                   "ewma_vol_20"}

    # Finite-window features must agree exactly on the post-warm-up tail.
    finite_window_cols = [
        c for c in tail_via_full.columns
        if c not in long_memory
        and tail_via_full[c].notna().all()
        and tail_solo[c].notna().all()
    ]
    assert len(finite_window_cols) > 0
    pd.testing.assert_frame_equal(
        tail_via_full[finite_window_cols],
        tail_solo[finite_window_cols],
        check_exact=False,
        rtol=1e-6,
        atol=1e-9,
    )

    # Long-memory features agree up to a loose tolerance: the seed effect
    # decays exponentially, so 200 bars in the tail give well under 1% error.
    for c in long_memory:
        if c in tail_via_full.columns:
            a = tail_via_full[c].to_numpy()
            b = tail_solo[c].to_numpy()
            mask = np.isfinite(a) & np.isfinite(b)
            if mask.any():
                np.testing.assert_allclose(
                    a[mask], b[mask], rtol=5e-2, atol=5e-2,
                )


# ---------------------------------------------------------------------------
# 11. rolling z-score strict causality on the test set
# ---------------------------------------------------------------------------

def test_rolling_zscore_strict_causality_test_set(ohlcv):
    """Rolling z-score on the test segment must use only past values within
    that test segment. Mutating bars at i+1..end must not change z-score at i.

    This pins down that fit on the train segment does not leak any global
    statistic into transform on the test segment, and that the rolling
    z-score itself is causal (its mean/std at bar i depend only on bars
    [i - window + 1, i] of the *transform input*).
    """
    train = ohlcv.iloc[:600]
    test = ohlcv.iloc[600:].copy()

    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 20),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=False,
        include_volatility=False,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=60,
    )
    pipe = FeaturePipeline(cfg)
    pipe.fit(train)

    feats_test_orig = pipe.transform(test)

    # Probe causality at multiple positions (relative to the test segment).
    rng = np.random.default_rng(7)
    for probe in (100, 130, 160):
        test_pert = test.copy()
        # Aggressively perturb everything strictly after probe.
        for col in ("close", "high", "low"):
            scale = rng.uniform(0.5, 1.5, len(test_pert) - (probe + 1))
            test_pert.iloc[probe + 1:, test_pert.columns.get_loc(col)] *= scale

        feats_test_pert = pipe.transform(test_pert)

        # The standardized row at probe must be byte-identical (NaN==NaN).
        row_orig = feats_test_orig.iloc[probe]
        row_pert = feats_test_pert.iloc[probe]
        # Allow NaN equality via pd.testing.
        pd.testing.assert_series_equal(row_orig, row_pert, check_names=False)


def test_rolling_zscore_does_not_leak_train_stats(ohlcv):
    """Pipeline fit on train must not bake train mean/std into transform.

    If the rolling z-score is truly causal, then transform(test) is fully
    determined by the test DataFrame plus cfg, regardless of what data was
    seen at fit time. Two pipelines fit on disjoint train segments must
    produce identical features when applied to the same test segment.
    """
    test = ohlcv.iloc[700:].copy()
    train_a = ohlcv.iloc[:300]
    train_b = ohlcv.iloc[300:600]

    cfg = FeaturePipelineConfig(
        rolling_windows=(5, 20),
        return_lags=(1,),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=True,
        standardize=True,
        standardize_method="rolling_zscore",
        standardize_window=60,
    )
    pipe_a = FeaturePipeline(cfg).fit(train_a)
    pipe_b = FeaturePipeline(cfg).fit(train_b)

    feats_a = pipe_a.transform(test)
    feats_b = pipe_b.transform(test)

    # Same columns, same order.
    assert pipe_a.feature_names() == pipe_b.feature_names()
    pd.testing.assert_frame_equal(feats_a, feats_b)


# ---------------------------------------------------------------------------
# Audit fix: bb_width must not blow up to inf when rolling mid is 0.
# ---------------------------------------------------------------------------


def test_bb_width_safe_when_rolling_mid_zero():
    """A constant-zero close rolls a zero rolling mean, which would otherwise
    produce inf bb_width. The pipeline must coerce this to NaN.
    """
    n = 60
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {"close": np.zeros(n), "high": np.zeros(n), "low": np.zeros(n)},
        index=idx,
    )
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=True,
        include_microstructure=False,
        include_volatility=False,
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    feats = pipe.fit_transform(df)
    if "bb_width" in feats.columns:
        # Either NaN (preferred) or zero — never +/-inf.
        bbw = feats["bb_width"].to_numpy()
        assert not np.isinf(bbw).any()


def test_hl_realized_vol_rejects_non_positive_low():
    """A non-positive low must raise immediately rather than silently emit
    NaN/-inf log values that leak into the standardization step.
    """
    n = 40
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    high = np.linspace(100.0, 110.0, n)
    low = np.linspace(99.0, 109.0, n)
    low[5] = 0.0  # poison
    df = pd.DataFrame(
        {"close": (high + low) / 2.0, "high": high, "low": low},
        index=idx,
    )
    cfg = FeaturePipelineConfig(
        rolling_windows=(5,),
        return_lags=(1,),
        include_technicals=False,
        include_microstructure=False,
        include_volatility=True,  # triggers the hl_realized_vol path
        standardize=False,
    )
    pipe = FeaturePipeline(cfg)
    with pytest.raises(ValueError, match="positive"):
        pipe.fit_transform(df)
