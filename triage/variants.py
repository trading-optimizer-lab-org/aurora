"""StrategyVariant -- the unit of work for the triage backend.

A ``StrategyVariant`` is a single concrete proposal: a strategy class FQN,
a frozen parameter dict, a universe, and a rebalance cadence. It is
deliberately *cheaper* than a full ``StrategySpec`` (no hypothesis text,
no expected-edge prior, no policy_hash binding) -- triage exists to scan
thousands of variants per second; ceremony cost dominates if we reuse
the factory's spec object directly.

Identity contract
-----------------
``variant_id`` is a deterministic SHA-256 over the canonical
(strategy_class, params, universe, rebalance) tuple. Two variants whose
canonical fields agree MUST have the same ``variant_id`` -- the
``TriageEngine``'s dedup logic relies on this, and the promotion bridge
to the official engine round-trips through it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Any, Iterable, Iterator, Mapping, Optional


def _canonical(payload: dict) -> str:
    """Return the deterministic JSON encoding used everywhere in QuantForge."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _compute_variant_id(
    strategy_class: str,
    params: Mapping[str, Any],
    universe: Iterable[str],
    rebalance: str,
) -> str:
    """SHA-256 over the canonical variant identity tuple."""
    payload = {
        "strategy_class": str(strategy_class),
        "params": dict(params),
        "universe": list(universe),
        "rebalance": str(rebalance),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategyVariant:
    """One concrete strategy candidate.

    Attributes:
        variant_id: deterministic SHA-256 of the canonical identity tuple.
            Always recomputed by :meth:`make`; never trust a caller-supplied
            id.
        strategy_class: fully-qualified import path
            (``"pkg.module.ClassName"``).
        params: keyword arguments to pass to the strategy constructor.
        universe: tickers the strategy trades. Single-asset = list of length 1.
        rebalance: rebalance cadence label (informational for triage;
            promotion to the official engine carries it forward).
    """

    variant_id: str
    strategy_class: str
    params: dict[str, Any]
    universe: list[str]
    rebalance: str

    @classmethod
    def make(
        cls,
        *,
        strategy_class: str,
        params: Optional[Mapping[str, Any]] = None,
        universe: Optional[Iterable[str]] = None,
        rebalance: str = "1d",
        variant_id: Optional[str] = None,  # accepted for parity; ignored
    ) -> "StrategyVariant":
        """Construct a variant with a recomputed ``variant_id``."""
        params_d = dict(params or {})
        universe_l = list(universe or [])
        vid = _compute_variant_id(
            strategy_class=strategy_class,
            params=params_d,
            universe=universe_l,
            rebalance=rebalance,
        )
        return cls(
            variant_id=vid,
            strategy_class=strategy_class,
            params=params_d,
            universe=universe_l,
            rebalance=rebalance,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StrategyVariant":
        return cls.make(
            strategy_class=str(d.get("strategy_class", "")),
            params=dict(d.get("params") or {}),
            universe=list(d.get("universe") or []),
            rebalance=str(d.get("rebalance", "1d")),
        )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def variant_grid(
    strategy_class: str,
    universe: Iterable[str],
    param_grid: Mapping[str, Iterable[Any]],
    *,
    rebalance: str = "1d",
) -> Iterator[StrategyVariant]:
    """Cartesian product of ``param_grid`` -> :class:`StrategyVariant` stream.

    Iteration order is the sorted-by-key product of ``param_grid``. The
    resulting ``variant_id`` is deterministic per (params, universe).

    Args:
        strategy_class: fully-qualified path to the strategy class.
        universe: shared universe for every emitted variant.
        param_grid: mapping ``param_name -> iterable of values``. An empty
            iterable produces zero variants for that key (and therefore zero
            variants overall, matching the empty cartesian product
            convention).
        rebalance: rebalance cadence label propagated onto every variant.

    Yields:
        :class:`StrategyVariant` instances, one per cartesian-product entry.
    """
    universe_l = list(universe)
    keys = sorted(param_grid.keys())
    if not keys:
        # No params -> single variant with empty params.
        yield StrategyVariant.make(
            strategy_class=strategy_class,
            params={},
            universe=universe_l,
            rebalance=rebalance,
        )
        return
    value_lists = [list(param_grid[k]) for k in keys]
    if any(len(v) == 0 for v in value_lists):
        return
    for combo in product(*value_lists):
        yield StrategyVariant.make(
            strategy_class=strategy_class,
            params=dict(zip(keys, combo)),
            universe=universe_l,
            rebalance=rebalance,
        )


def variant_random_sample(
    strategy_class: str,
    universe: Iterable[str],
    param_space: Mapping[str, Any],
    *,
    n: int,
    seed: int,
    rebalance: str = "1d",
) -> Iterator[StrategyVariant]:
    """Random sample over ``param_space`` -> :class:`StrategyVariant` stream.

    Deterministic given ``seed``. The same (param_space, n, seed) will
    always emit the same variants in the same order.

    ``param_space`` values support three shapes:
        * ``(low, high)`` 2-tuple -> uniform float in [low, high]; if both
          bounds are ints, the sample is an int via ``round``.
        * ``list`` -> uniform categorical pick.
        * scalar -> constant value (no draw consumed).

    Args:
        strategy_class: fully-qualified path to the strategy class.
        universe: shared universe.
        param_space: mapping param name -> shape spec (see above).
        n: number of variants to draw.
        seed: RNG seed for reproducibility.
        rebalance: rebalance cadence.

    Yields:
        ``n`` :class:`StrategyVariant` instances.
    """
    if n <= 0:
        return
    import numpy as np
    rng = np.random.default_rng(int(seed))
    universe_l = list(universe)
    keys = sorted(param_space.keys())
    for _ in range(n):
        params: dict[str, Any] = {}
        for k in keys:
            spec = param_space[k]
            if isinstance(spec, tuple) and len(spec) == 2:
                lo, hi = spec
                val: Any
                if isinstance(lo, int) and isinstance(hi, int) \
                        and not isinstance(lo, bool) \
                        and not isinstance(hi, bool):
                    val = int(rng.integers(int(lo), int(hi) + 1))
                else:
                    val = float(rng.uniform(float(lo), float(hi)))
                params[k] = val
            elif isinstance(spec, list):
                if not spec:
                    params[k] = None
                else:
                    idx = int(rng.integers(0, len(spec)))
                    params[k] = spec[idx]
            else:
                # Scalar constant.
                params[k] = spec
        yield StrategyVariant.make(
            strategy_class=strategy_class,
            params=params,
            universe=universe_l,
            rebalance=rebalance,
        )


__all__ = [
    "StrategyVariant",
    "variant_grid",
    "variant_random_sample",
]
