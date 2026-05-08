"""Strategy abstract base + spec dataclass.

Conventions:
- Strategy.signals(prices, **params) -> np.array of weights in [-1, 1]
- weights[i] is position at close of bar i, applied to return of bar i+1
- Strategy MUST NOT use prices[i+1:] when computing signal[i] (anti-lookahead)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import numpy as np
import pandas as pd


@dataclass
class StrategySpec:
    """Genome-friendly spec. Defines parameter ranges for GA encoding."""
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    param_ranges: dict[str, tuple] = field(default_factory=dict)
    """param_ranges: dict[name -> (low, high) for floats or list of ints/categories]"""

    def to_genome(self) -> list[float]:
        """Encode current params as a unit-cube genome (each gene in [0, 1]).

        Convention matches quantforge.ga.runner._make_evaluate.decode: each
        gene corresponds to a sorted param key and is normalized to [0, 1]
        using the declared param_range. Values without a declared range pass
        through as-is (rare).

        Categorical encoding: ``(idx + 0.5) / n`` (slot midpoint). The decode
        path uses ``int(clip(g * n, 0, n-1))`` so genes in
        ``[idx/n, (idx+1)/n)`` map back to ``idx``. The midpoint is the safe
        round-trip: ``encode(decode(g))`` recovers the original index when
        sampled near a slot midpoint, and matches
        ``seed_population.seed_genome_from_known``. The previous
        ``idx / (n-1)`` form was off-by-one and broke round-trip for the
        last slot.
        """
        out = []
        for k in sorted(self.param_ranges.keys()):
            v = self.params.get(k, 0.0)
            rng = self.param_ranges[k]
            if isinstance(rng, list):
                # Categorical: midpoint of matching slot.
                n = len(rng)
                if n == 0:
                    out.append(0.0)
                    continue
                try:
                    idx = rng.index(v)
                except ValueError:
                    idx = 0
                g = (idx + 0.5) / n
                out.append(float(np.clip(g, 0.0, 1.0)))
            elif isinstance(rng, tuple) and len(rng) == 2:
                lo, hi = rng
                if hi == lo:
                    out.append(0.0)
                else:
                    g = (float(v) - float(lo)) / (float(hi) - float(lo))
                    out.append(float(np.clip(g, 0.0, 1.0)))
            else:
                out.append(0.0)
        return out

    def from_genome(self, genome: list[float]) -> "StrategySpec":
        """Decode a unit-cube genome (each gene in [0, 1]) into a new spec.

        Uses the same convention as quantforge.ga.runner._make_evaluate.decode
        so a round-trip ``spec.from_genome(spec.to_genome()).params`` recovers
        the discrete projection of the original params.
        """
        new_params = dict(self.params)
        keys = sorted(self.param_ranges.keys())
        for k, g in zip(keys, genome):
            rng = self.param_ranges[k]
            if isinstance(rng, list):
                idx = int(np.clip(g * len(rng), 0, len(rng) - 1))
                new_params[k] = rng[idx]
            elif isinstance(rng, tuple) and len(rng) == 2:
                lo, hi = rng
                gc = float(np.clip(g, 0.0, 1.0))
                v = lo + (hi - lo) * gc
                if (isinstance(lo, int) and isinstance(hi, int)
                        and not isinstance(lo, bool) and not isinstance(hi, bool)):
                    v = int(round(v))
                new_params[k] = v
            else:
                new_params[k] = g
        return StrategySpec(self.name, new_params, self.param_ranges)


class Strategy(ABC):
    """Abstract strategy. Subclass and implement signals()."""

    @abstractmethod
    def signals(self, prices: pd.Series) -> np.ndarray:
        """Return np.array of target weights, same length as prices.

        weights[i] in [-1, 1]. NaN forbidden. Causality: weights[i] uses prices[:i+1] only.
        """
        ...

    @classmethod
    def spec(cls) -> StrategySpec:
        """Return StrategySpec defining default params + ranges. Override in subclass."""
        return StrategySpec(name=cls.__name__)

    def with_params(self, **kwargs) -> "Strategy":
        """Return new instance with updated params. Default: replace attrs."""
        new = self.__class__()
        for k, v in kwargs.items():
            setattr(new, k, v)
        return new
