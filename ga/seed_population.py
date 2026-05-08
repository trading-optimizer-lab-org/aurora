"""GA population seeding from known-good configs (Task 5.3).

Avoid cold-start by initializing the GA population with parameters that
prior research already validated. Each KnownConfig encodes a strategy
class name plus a params dict. ``seed_genome_from_known`` inverts the
runner's decode logic to map params back into the [0, 1] genome space.

Sources:
- R111 STANDARD (strategies/sp500_ls_v2/run_r111.py): vectorbt-discovered
  d65_vix43t_40 macro overlay -- not directly representable as a single
  Strategy subclass, but the underlying TS-momentum / mean-reversion
  primitives map onto MACross + RSIMeanRev.
- HEDGE SP v3 R6 (strategies/hedge_sp/hedge_sp_v3_signal.py): trend
  regime + 60-day vol target. The directional core is captured here as
  MACross + TSMomentum.
- INDUSTRY_TREND v1 (strategies/industry_trend_v1/industry_trend_signal.py):
  monthly tsmom6 (~126 trading days) long-only with vol target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Type

import numpy as np


@dataclass
class KnownConfig:
    """A validated parameter set imported from prior research."""
    name: str
    strategy_class: str
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict | None = None
    source: str = ""


# Library of known-good configurations.
# strategy_class is the class __name__ (matches Strategy subclass names in
# quantforge.strategies.library), so callers can filter by class.
KNOWN_CONFIGS: dict[str, KnownConfig] = {
    "macross_spy_baseline": KnownConfig(
        name="macross_spy_baseline",
        strategy_class="MACross",
        params={"fast": 20, "slow": 100, "allow_short": True},
        source="QuantForge default",
    ),
    "tsmom_industry_6m": KnownConfig(
        name="tsmom_industry_6m",
        strategy_class="TSMomentum",
        params={"lookback": 126, "skip": 0, "allow_short": False},
        metrics={"cagr": 9.89, "sharpe": 1.04, "calmar": 0.48, "mdd": -20.56},
        source="INDUSTRY_TREND v1 (tsmom6_voltgt8) -- TS-momentum core",
    ),
    "tsmom_12_1": KnownConfig(
        name="tsmom_12_1",
        strategy_class="TSMomentum",
        params={"lookback": 252, "skip": 21, "allow_short": True},
        source="Classic 12-1 cross-sectional momentum literature",
    ),
    "macross_hedge_sp_trend": KnownConfig(
        name="macross_hedge_sp_trend",
        strategy_class="MACross",
        params={"fast": 50, "slow": 200, "allow_short": True},
        metrics={"calmar_is": 4.963, "calmar_oos": 5.648},
        source="HEDGE SP v3 R6 trend core (50/200 long-term filter)",
    ),
    "rsi_meanrev_r111": KnownConfig(
        name="rsi_meanrev_r111",
        strategy_class="RSIMeanRev",
        params={"period": 2, "oversold": 11.0, "overbought": 86.0,
                "allow_short": True},
        source="R111 STANDARD: rsi2 < 11 long, rsi2 > rsi2_thr_high=86 short",
    ),
    "rsi_meanrev_classic_2_10_90": KnownConfig(
        name="rsi_meanrev_classic_2_10_90",
        strategy_class="RSIMeanRev",
        params={"period": 2, "oversold": 10.0, "overbought": 90.0,
                "allow_short": True},
        source="Larry Connors RSI(2) classic",
    ),
    "donchian_turtle": KnownConfig(
        name="donchian_turtle",
        strategy_class="DonchianBreakout",
        params={"channel": 55, "exit_channel": 20, "allow_short": True},
        source="Turtle Traders S2 system",
    ),
    "dual_momentum_antonacci": KnownConfig(
        name="dual_momentum_antonacci",
        strategy_class="DualMomentum",
        params={"lookback": 252, "skip": 21, "rf_proxy": 0.02,
                "allow_short": False},
        source="Antonacci dual momentum default (12m lookback, 1m skip)",
    ),
}


def load_known_configs(strategy_class) -> list[KnownConfig]:
    """Return all KNOWN_CONFIGS matching the given strategy class.

    Args:
        strategy_class: either a Strategy subclass or its ``__name__`` str.
    """
    if isinstance(strategy_class, str):
        target = strategy_class
    else:
        target = strategy_class.__name__
    return [c for c in KNOWN_CONFIGS.values() if c.strategy_class == target]


def seed_genome_from_known(strategy_class, params: dict) -> list[float]:
    """Encode a known params dict into a normalized [0, 1] genome.

    This inverts the decode logic in ``quantforge.ga.runner._make_evaluate``:
    - tuple range (lo, hi) -> g = (val - lo) / (hi - lo)
    - list categorical -> g = (idx + 0.5) / len(list)  (midpoint of slot)

    Genome order matches ``sorted(spec.param_ranges.keys())``, the same
    ordering ``run_ga`` uses.

    Raises:
        TypeError: if ``strategy_class`` has ``is_wrapper=True``. Wrapper
            strategies (e.g. VolatilityTargetWrapper, StopWrapper) require a
            ``base`` Strategy in their ctor that is not in
            ``spec().param_ranges``; ``run_ga`` already refuses them, so the
            seed builder must too. Mirrors ``runner.run_ga:128-133``.
    """
    if getattr(strategy_class, "is_wrapper", False):
        raise TypeError(
            f"{strategy_class.__name__} is marked is_wrapper=True; it requires "
            "a `base` Strategy in its ctor that is not in spec().param_ranges. "
            "Build a wrapper_factory closing over a concrete base and pass that."
        )
    spec = strategy_class.spec()
    keys = sorted(spec.param_ranges.keys())
    genome: list[float] = []
    for k in keys:
        rng = spec.param_ranges[k]
        # If a known config omits a param, fall back to the spec default
        # so we always produce a valid genome.
        val = params.get(k, spec.params.get(k))
        if isinstance(rng, list):
            # Categorical: pick midpoint of the matching slot. The decode
            # uses int(clip(g * n, 0, n-1)), so g in [idx/n, (idx+1)/n)
            # decodes to idx. Midpoint (idx + 0.5)/n is the safe choice.
            try:
                idx = rng.index(val)
            except ValueError:
                # Fallback: closest by string equality on str(val).
                idx = 0
                for i, candidate in enumerate(rng):
                    if str(candidate) == str(val):
                        idx = i
                        break
            n = len(rng)
            g = (idx + 0.5) / n
        elif isinstance(rng, tuple) and len(rng) == 2:
            lo, hi = rng
            if hi == lo:
                g = 0.0
            else:
                g = (float(val) - float(lo)) / (float(hi) - float(lo))
        else:
            g = 0.5
        genome.append(float(np.clip(g, 0.0, 1.0)))
    return genome


def seed_initial_population(strategy_class, population_size: int,
                            include_known: bool = True,
                            seed: int = 42) -> list[list[float]]:
    """Build an initial GA population.

    The first slots are encoded known configs that match ``strategy_class``.
    Remaining slots are random uniform [0, 1] genomes. If ``include_known``
    is False or no configs match the class, the entire population is random.

    Raises:
        TypeError: if ``strategy_class`` has ``is_wrapper=True``. Mirrors
            ``run_ga`` so callers cannot accidentally seed a population for
            a wrapper strategy that the GA itself cannot run.
    """
    if getattr(strategy_class, "is_wrapper", False):
        raise TypeError(
            f"{strategy_class.__name__} is marked is_wrapper=True; it requires "
            "a `base` Strategy in its ctor that is not in spec().param_ranges. "
            "Build a wrapper_factory closing over a concrete base and pass that."
        )
    spec = strategy_class.spec()
    n_genes = len(sorted(spec.param_ranges.keys()))

    rng = np.random.default_rng(seed)
    pop: list[list[float]] = []

    if include_known:
        for cfg in load_known_configs(strategy_class):
            if len(pop) >= population_size:
                break
            pop.append(seed_genome_from_known(strategy_class, cfg.params))

    while len(pop) < population_size:
        pop.append([float(x) for x in rng.random(n_genes)])

    return pop[:population_size]
