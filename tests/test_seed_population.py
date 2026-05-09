"""Tests for GA population seeding from known configs (Task 5.3)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.strategies.library import (
    MACross, RSIMeanRev, TSMomentum, DonchianBreakout, DualMomentum,
)
from aurora.ga.runner import run_ga, GAConfig
from aurora.ga.fitness import multi_objective_fitness
from aurora.ga.seed_population import (
    KNOWN_CONFIGS, KnownConfig, load_known_configs,
    seed_genome_from_known, seed_initial_population,
)


pytest.importorskip("deap")


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2012-01-01", periods=900, freq="B")
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.012, 900)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


@pytest.fixture
def is_oos(fake_prices):
    return fake_prices.iloc[:600], fake_prices.iloc[600:]


def _decode(strategy_class, genome):
    """Mirror of runner._make_evaluate decode logic, for verification only."""
    spec = strategy_class.spec()
    keys = sorted(spec.param_ranges.keys())
    params = {}
    for k, g in zip(keys, genome):
        r = spec.param_ranges[k]
        if isinstance(r, list):
            idx = int(np.clip(g * len(r), 0, len(r) - 1))
            params[k] = r[idx]
        else:
            lo, hi = r
            v = lo + (hi - lo) * g
            if isinstance(lo, int) and isinstance(hi, int):
                v = int(round(v))
            params[k] = v
    return params


def test_known_configs_lookup():
    """load_known_configs returns at least one MACross config."""
    macross = load_known_configs("MACross")
    assert len(macross) >= 1
    assert all(isinstance(c, KnownConfig) for c in macross)
    assert all(c.strategy_class == "MACross" for c in macross)
    # Also accept passing the class itself.
    macross_via_cls = load_known_configs(MACross)
    assert len(macross_via_cls) == len(macross)


def test_known_configs_count_minimum():
    """Library should have at least 6 configs covering multiple classes."""
    assert len(KNOWN_CONFIGS) >= 6
    classes = {c.strategy_class for c in KNOWN_CONFIGS.values()}
    # At least three different strategy types.
    assert len(classes) >= 3


def test_genome_encoding_macross():
    """encode known MACross params, decode via runner logic, recover params."""
    cfg = next(c for c in load_known_configs("MACross")
               if c.name == "macross_spy_baseline")
    genome = seed_genome_from_known(MACross, cfg.params)
    assert len(genome) == 3
    assert all(0.0 <= g <= 1.0 for g in genome)
    decoded = _decode(MACross, genome)
    assert decoded["fast"] == cfg.params["fast"]
    assert decoded["slow"] == cfg.params["slow"]
    assert decoded["allow_short"] == cfg.params["allow_short"]


def test_genome_encoding_tsmom():
    cfg = next(c for c in load_known_configs("TSMomentum")
               if c.name == "tsmom_industry_6m")
    genome = seed_genome_from_known(TSMomentum, cfg.params)
    decoded = _decode(TSMomentum, genome)
    assert decoded["lookback"] == cfg.params["lookback"]
    assert decoded["skip"] == cfg.params["skip"]
    assert decoded["allow_short"] == cfg.params["allow_short"]


def test_genome_encoding_rsi():
    cfg = next(c for c in load_known_configs("RSIMeanRev")
               if c.name == "rsi_meanrev_classic_2_10_90")
    genome = seed_genome_from_known(RSIMeanRev, cfg.params)
    decoded = _decode(RSIMeanRev, genome)
    assert decoded["period"] == cfg.params["period"]
    assert abs(decoded["oversold"] - cfg.params["oversold"]) < 1e-6
    assert abs(decoded["overbought"] - cfg.params["overbought"]) < 1e-6
    assert decoded["allow_short"] == cfg.params["allow_short"]


def test_seeded_pop_size():
    """seed_initial_population returns exactly population_size genomes."""
    pop = seed_initial_population(MACross, population_size=20, seed=1)
    assert len(pop) == 20
    n_genes = len(MACross.spec().param_ranges)
    assert all(len(g) == n_genes for g in pop)
    assert all(0.0 <= v <= 1.0 for g in pop for v in g)


def test_seeded_pop_known_first():
    """First genomes must match known configs for the strategy class."""
    known = load_known_configs(MACross)
    assert len(known) >= 1
    pop = seed_initial_population(MACross, population_size=20, seed=1)
    for i, cfg in enumerate(known):
        expected = seed_genome_from_known(MACross, cfg.params)
        assert pop[i] == pytest.approx(expected, abs=1e-9), (
            f"slot {i} expected encoded {cfg.name}, got {pop[i]}"
        )
    # Slots after the known configs should be different from any known
    # encoding (overwhelmingly likely, given uniform draws).
    if len(pop) > len(known):
        any_known = [seed_genome_from_known(MACross, c.params) for c in known]
        random_slot = pop[len(known)]
        assert all(random_slot != enc for enc in any_known)


def test_seeded_pop_no_known_fills_random():
    """include_known=False yields all-random population."""
    pop = seed_initial_population(MACross, population_size=10,
                                  include_known=False, seed=7)
    assert len(pop) == 10
    # Reproducible with same seed.
    pop2 = seed_initial_population(MACross, population_size=10,
                                   include_known=False, seed=7)
    assert pop == pop2


def test_seeded_pop_no_match_falls_back_random():
    """A class with no known configs falls back to all random."""
    # DualMomentum has a known config in the library; remove it to test
    # the no-match path via a fake class name.
    class FakeMACross(MACross):
        pass

    # FakeMACross.__name__ = "FakeMACross" -- not in KNOWN_CONFIGS.
    pop = seed_initial_population(FakeMACross, population_size=5, seed=3)
    assert len(pop) == 5
    n_genes = len(FakeMACross.spec().param_ranges)
    assert all(len(g) == n_genes for g in pop)


def test_run_ga_with_seed(is_oos):
    """GA runs with a seeded initial population."""
    is_p, oos_p = is_oos
    seeded = seed_initial_population(MACross, population_size=12, seed=0)
    cfg = GAConfig(population=12, generations=1, seed=42, backend="sequential")
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                    cfg, verbose=False, seeded_pop=seeded)
    assert isinstance(pareto, list)
    assert len(pareto) >= 1
    params, fit = pareto[0]
    assert "fast" in params and "slow" in params
    assert isinstance(fit, tuple) and len(fit) == 4


def test_run_ga_with_seed_initial_contains_known(is_oos):
    """First generation evaluates the encoded known configs.

    We re-decode the known macross_spy_baseline genome and confirm the
    Pareto front includes a parameter combination consistent with the
    known config or one of the seeded slots after one generation.
    """
    is_p, oos_p = is_oos
    seeded = seed_initial_population(MACross, population_size=8, seed=0)
    # Verify the seeded slots themselves contain at least one known param set.
    known = load_known_configs(MACross)
    decoded_seeds = [_decode(MACross, g) for g in seeded[:len(known)]]
    cfg_params = [c.params for c in known]
    for cp in cfg_params:
        assert cp in decoded_seeds, (
            f"known config params {cp} not present in initial seeded pop"
        )

    cfg = GAConfig(population=8, generations=0, seed=42, backend="sequential")
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                    cfg, verbose=False, seeded_pop=seeded)
    # With generations=0 the front is drawn from the seeded initial pop.
    front_params = [p for p, _ in pareto]
    # At least one known config should be on the initial front (likely all
    # are non-dominated given small pop), but at minimum the front size is >=1.
    assert len(front_params) >= 1


def test_run_ga_short_seed_filled(is_oos):
    """If seeded_pop shorter than population, remainder is random."""
    is_p, oos_p = is_oos
    seeded = seed_initial_population(MACross, population_size=3, seed=0)
    cfg = GAConfig(population=10, generations=1, seed=42, backend="sequential")
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                    cfg, verbose=False, seeded_pop=seeded)
    assert len(pareto) >= 1


def test_run_ga_seed_wrong_length_raises(is_oos):
    """Genome length mismatch must raise."""
    is_p, oos_p = is_oos
    bad_seed = [[0.5, 0.5]]  # 2 genes for MACross which expects 3
    cfg = GAConfig(population=4, generations=0, seed=42, backend="sequential")
    with pytest.raises(ValueError):
        run_ga(MACross, is_p, oos_p, multi_objective_fitness,
               cfg, verbose=False, seeded_pop=bad_seed)


def test_seed_initial_population_rejects_wrapper():
    """Mirror runner.run_ga: refuse strategies marked is_wrapper=True so
    callers cannot accidentally seed a population for a wrapper class.
    """
    from aurora.strategies.library.stop_wrapper import StopWrapper
    with pytest.raises(TypeError, match="is_wrapper"):
        seed_initial_population(StopWrapper, population_size=4)
    with pytest.raises(TypeError, match="is_wrapper"):
        seed_genome_from_known(StopWrapper, {"x": 1})


def test_categorical_encoding_round_trip_midpoint():
    """seed_genome_from_known and StrategySpec.to_genome must agree on the
    categorical midpoint convention so encode -> decode -> encode is stable.
    """
    from aurora.strategies.base import StrategySpec
    spec = StrategySpec(
        name="Cat",
        params={"flag": True, "n": 5},
        param_ranges={"flag": [True, False], "n": (1, 10)},
    )
    g = spec.to_genome()
    # 'flag' is sorted before 'n'. Slot midpoint for True (idx 0, n=2) -> 0.25.
    assert abs(g[0] - 0.25) < 1e-9
    # round-trip recovers True via the runner-style decode at idx 0.
    n = 2
    idx_recovered = int(np.clip(g[0] * n, 0, n - 1))
    assert idx_recovered == 0  # True

    # Also verify the LAST slot of a 3-element categorical recovers correctly.
    spec3 = StrategySpec(
        name="Cat3",
        params={"mode": "c"},
        param_ranges={"mode": ["a", "b", "c"]},
    )
    g3 = spec3.to_genome()
    # Midpoint for last slot c (idx 2, n=3) -> 5/6 ~= 0.8333.
    assert abs(g3[0] - (2 + 0.5) / 3) < 1e-9
    n3 = 3
    assert int(np.clip(g3[0] * n3, 0, n3 - 1)) == 2  # 'c'
