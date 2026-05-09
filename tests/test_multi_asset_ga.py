"""Tests for multi-asset GA runner.

Run:
    pytest quantforge/tests/test_multi_asset_ga.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import PairTrade
from aurora.ga.multi_asset_runner import (
    run_multi_asset_ga,
    multi_asset_fitness,
    MultiAssetGAConfig,
    _decode_genome,
)


# ------------------------------------------------------------------ #
# Fixtures: synthetic cointegrated pair (mean-reverting spread).     #
# ------------------------------------------------------------------ #
def _cointegrated_pair(n=600, seed=42):
    """Two assets sharing a common factor + idiosyncratic mean-rev noise.

    Spread = pa - pb mean-reverts -> z-score crosses entry/exit thresholds,
    so a PairTrade with reasonable params should generate non-trivial trades.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    factor = np.cumsum(rng.normal(0.0, 0.01, n))
    # AR(1) idiosyncratic noise -> spread has finite variance and reverts
    eps_a = rng.normal(0.0, 0.005, n)
    eps_b = rng.normal(0.0, 0.005, n)
    pa = 100.0 + factor + eps_a
    pb = 100.0 + factor + eps_b
    return {
        "AAA": pd.Series(pa, index=idx, name="AAA"),
        "BBB": pd.Series(pb, index=idx, name="BBB"),
    }


def _split_is_oos(price_dict, frac=0.6):
    """Split each series at a fraction of the bars."""
    out_is, out_oos = {}, {}
    for k, s in price_dict.items():
        cut = int(len(s) * frac)
        out_is[k] = s.iloc[:cut]
        out_oos[k] = s.iloc[cut:]
    return out_is, out_oos


# ------------------------------------------------------------------ #
# 1. Fitness on a fixed PairTrade returns a finite 4-tuple           #
# ------------------------------------------------------------------ #
def test_multi_asset_fitness_basic():
    pair = _cointegrated_pair(n=600, seed=42)
    is_p, oos_p = _split_is_oos(pair)

    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)

    fit = multi_asset_fitness(
        is_p, oos_p, pt.weights,
        gross_leverage_cap=1.0, net_leverage_cap=2.0, ppy=252,
    )
    assert isinstance(fit, tuple) and len(fit) == 4
    cal, sh, robust, mdd_pen = fit
    # All entries must be finite floats (no NaN/inf)
    for x in fit:
        assert np.isfinite(x), f"fitness has non-finite component: {fit}"
    # Sentinel must NOT have fired
    assert fit != (-99.0, -99.0, -99.0, 99.0), \
        "fitness fell into sentinel branch on a healthy fixture"
    # Robustness <= 0 by construction (negative |gap|)
    assert robust <= 0.0
    # MDD penalty >= 0
    assert mdd_pen >= 0.0


# ------------------------------------------------------------------ #
# 2. End-to-end small GA returns a non-empty Pareto front            #
# ------------------------------------------------------------------ #
def test_run_ga_pair_trade():
    pair = _cointegrated_pair(n=600, seed=7)
    is_p, oos_p = _split_is_oos(pair)

    cfg = MultiAssetGAConfig(population=8, generations=2, seed=7)
    pareto = run_multi_asset_ga(
        PairTrade,
        price_dict_is=is_p,
        price_dict_oos=oos_p,
        symbols=["AAA", "BBB"],
        fitness_fn=multi_asset_fitness,
        config=cfg,
        verbose=False,
    )
    assert isinstance(pareto, list)
    assert len(pareto) > 0, "Pareto front is empty"
    for params, fit in pareto:
        assert isinstance(params, dict)
        assert set(params.keys()) == {
            "lookback",
            "entry_z",
            "exit_z",
            "hedge_ratio",
            "recompute_hedge_ratio_every",
        }
        assert isinstance(fit, tuple) and len(fit) == 4


# ------------------------------------------------------------------ #
# 3. Genome encode/decode round-trips PairTrade params correctly     #
# ------------------------------------------------------------------ #
def test_genome_encoding():
    spec = PairTrade.spec()
    param_keys = sorted(spec.param_ranges.keys())
    assert param_keys == [
        "entry_z",
        "exit_z",
        "hedge_ratio",
        "lookback",
        "recompute_hedge_ratio_every",
    ]

    # all-zero genome -> minima
    g_lo = [0.0] * len(param_keys)
    p_lo = _decode_genome(g_lo, param_keys, spec)
    assert p_lo["lookback"] == 20         # int low
    assert p_lo["entry_z"] == pytest.approx(1.0)
    assert p_lo["exit_z"] == pytest.approx(0.0)
    assert p_lo["hedge_ratio"] == pytest.approx(0.5)
    assert p_lo["recompute_hedge_ratio_every"] == 0  # int low

    # all-one genome -> maxima
    g_hi = [1.0] * len(param_keys)
    p_hi = _decode_genome(g_hi, param_keys, spec)
    assert p_hi["lookback"] == 252        # int high
    assert p_hi["entry_z"] == pytest.approx(3.5)
    assert p_hi["exit_z"] == pytest.approx(1.5)
    assert p_hi["hedge_ratio"] == pytest.approx(2.0)
    assert p_hi["recompute_hedge_ratio_every"] == 252  # int high

    # midpoint genome
    g_mid = [0.5] * len(param_keys)
    p_mid = _decode_genome(g_mid, param_keys, spec)
    assert p_mid["lookback"] == 136       # int(round(20 + 0.5 * 232)) = 136
    assert p_mid["entry_z"] == pytest.approx(2.25)
    assert p_mid["exit_z"] == pytest.approx(0.75)
    assert p_mid["hedge_ratio"] == pytest.approx(1.25)
    assert p_mid["recompute_hedge_ratio_every"] == 126  # int(round(0 + 0.5 * 252))

    # Decoded params must satisfy PairTrade ctor (entry_z > exit_z holds at extremes)
    pt = PairTrade(sym_a="A", sym_b="B", **p_hi)
    assert pt.lookback == 252


# ------------------------------------------------------------------ #
# 4. With 2 synthetic cointegrated assets GA finds non-trivial params #
# ------------------------------------------------------------------ #
def test_with_2_synthetic_assets():
    pair = _cointegrated_pair(n=800, seed=123)
    is_p, oos_p = _split_is_oos(pair, frac=0.5)

    cfg = MultiAssetGAConfig(population=12, generations=3, seed=123)
    pareto = run_multi_asset_ga(
        PairTrade,
        price_dict_is=is_p,
        price_dict_oos=oos_p,
        symbols=["AAA", "BBB"],
        fitness_fn=multi_asset_fitness,
        config=cfg,
        verbose=False,
    )
    assert len(pareto) > 0

    # At least one Pareto solution must escape the all-sentinel state
    healthy = [
        (p, f) for p, f in pareto
        if f != (-99.0, -99.0, -99.0, 99.0)
    ]
    assert len(healthy) > 0, (
        f"every Pareto member is sentinel -> GA never produced a valid run. "
        f"pareto={pareto}"
    )

    # Best Calmar should be > -99 (sentinel) and finite
    best = max(healthy, key=lambda pf: pf[1][0])
    best_params, best_fit = best
    assert np.isfinite(best_fit[0])
    assert best_fit[0] > -99.0
    # Sanity: best params should be inside spec ranges
    assert 20 <= best_params["lookback"] <= 252
    assert 1.0 <= best_params["entry_z"] <= 3.5
    assert 0.0 <= best_params["exit_z"] <= 1.5
    assert 0.5 <= best_params["hedge_ratio"] <= 2.0


# ------------------------------------------------------------------ #
# 5. Input validation                                                 #
# ------------------------------------------------------------------ #
def test_run_ga_validates_symbols_match_price_dict():
    pair = _cointegrated_pair(n=300, seed=1)
    is_p, oos_p = _split_is_oos(pair)
    cfg = MultiAssetGAConfig(population=4, generations=1, seed=1)

    # mismatched symbols -> raises
    with pytest.raises(ValueError, match="price_dict_is keys"):
        run_multi_asset_ga(
            PairTrade,
            price_dict_is=is_p,
            price_dict_oos=oos_p,
            symbols=["AAA", "ZZZ"],   # ZZZ not in price dict
            fitness_fn=multi_asset_fitness,
            config=cfg,
            verbose=False,
        )

    # too few symbols -> raises
    with pytest.raises(ValueError, match="symbols must have"):
        run_multi_asset_ga(
            PairTrade,
            price_dict_is={"AAA": is_p["AAA"]},
            price_dict_oos={"AAA": oos_p["AAA"]},
            symbols=["AAA"],
            fitness_fn=multi_asset_fitness,
            config=cfg,
            verbose=False,
        )


def test_fitness_sentinel_on_invalid_strategy():
    """If weights_fn raises, fitness must return sentinel without propagating."""
    pair = _cointegrated_pair(n=300, seed=5)
    is_p, oos_p = _split_is_oos(pair)

    def bad_weights_fn(_pd):
        raise RuntimeError("boom")

    fit = multi_asset_fitness(is_p, oos_p, bad_weights_fn)
    assert fit == (-99.0, -99.0, -99.0, 99.0)


def test_multi_asset_oos_isolation():
    """OOS-sagrado: multi_asset_fitness_is must be invariant to OOS prices.

    Mutating the OOS dict must not affect the IS-only fitness output. This
    is the multi-asset analog of the single-asset OOS-isolation test in
    test_oos_isolation.py.
    """
    from aurora.ga.multi_asset_runner import multi_asset_fitness_is

    pair = _cointegrated_pair(n=600, seed=42)
    is_p, oos_p = _split_is_oos(pair)
    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)

    fit_a = multi_asset_fitness_is(is_p, pt.weights, ppy=252)

    # Mutate OOS aggressively — fitness_is must not see it.
    oos_mut = {k: pd.Series(np.random.default_rng(0).normal(100, 10, len(v)),
                            index=v.index, name=v.name)
               for k, v in oos_p.items()}
    # Compute again — pass mutated OOS via the deprecated alias to verify
    # the alias also drops OOS.
    from aurora.ga.multi_asset_runner import multi_asset_fitness
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        fit_b = multi_asset_fitness(is_p, oos_mut, pt.weights, ppy=252)
    assert fit_a == fit_b, (
        "multi_asset_fitness leaked OOS into selection signal — "
        "OOS-sagrado violation"
    )


def test_multi_asset_validate_oos_basic():
    """multi_asset_validate_oos returns finite metrics on healthy data."""
    from aurora.ga.multi_asset_runner import multi_asset_validate_oos

    pair = _cointegrated_pair(n=600, seed=42)
    _, oos_p = _split_is_oos(pair)
    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    out = multi_asset_validate_oos(oos_p, pt.weights, ppy=252)
    assert "calmar" in out and "sharpe" in out and "mdd" in out
    assert "error" not in out
    assert np.isfinite(out["calmar"])


def test_run_ga_consecutive_calls_no_creator_collision():
    """Running run_multi_asset_ga twice on the same class must not raise
    a stale-creator collision. Per-call unique names guard this.
    """
    pair = _cointegrated_pair(n=300, seed=1)
    is_p, oos_p = _split_is_oos(pair)
    cfg = MultiAssetGAConfig(population=4, generations=1, seed=1)
    for _ in range(2):
        pareto = run_multi_asset_ga(
            PairTrade,
            price_dict_is=is_p,
            price_dict_oos=oos_p,
            symbols=["AAA", "BBB"],
            fitness_fn=multi_asset_fitness,
            config=cfg,
            verbose=False,
        )
        assert isinstance(pareto, list)
        assert len(pareto) > 0


def test_multi_asset_pareto_deterministic_across_runs():
    """Issue 2: Two seeded runs over the same data must return the Pareto
    front in the SAME order. Without the deterministic _tie_key sort, ties
    in fitness are broken by Python's stable sort over a DEAP-internal
    order that depends on object id() and varies between runs.
    """
    pair = _cointegrated_pair(n=300, seed=7)
    is_p, oos_p = _split_is_oos(pair)
    cfg_a = MultiAssetGAConfig(population=8, generations=2, seed=11)
    cfg_b = MultiAssetGAConfig(population=8, generations=2, seed=11)
    pareto_a = run_multi_asset_ga(
        PairTrade, price_dict_is=is_p, price_dict_oos=oos_p,
        symbols=["AAA", "BBB"], fitness_fn=multi_asset_fitness,
        config=cfg_a, verbose=False,
    )
    pareto_b = run_multi_asset_ga(
        PairTrade, price_dict_is=is_p, price_dict_oos=oos_p,
        symbols=["AAA", "BBB"], fitness_fn=multi_asset_fitness,
        config=cfg_b, verbose=False,
    )
    # Same length and identical fitness ordering.
    assert len(pareto_a) == len(pareto_b)
    fits_a = [tuple(round(v, 9) for v in fit) for _, fit in pareto_a]
    fits_b = [tuple(round(v, 9) for v in fit) for _, fit in pareto_b]
    assert fits_a == fits_b
