"""Pluggable hypothesis generators.

A generator emits :class:`StrategySpec` instances to be fed into
:class:`ResearchFactory`. The contract is intentionally narrow:

    class HypothesisGenerator(Protocol):
        name: str
        def generate(self, n: int, seed: int) -> list[StrategySpec]: ...

Generators MUST NOT load OOS data and MUST NOT set ``policy_hash``
themselves. The factory binds the policy hash on submit so a tampered
generator cannot smuggle in a stale or fake hash.
"""
from __future__ import annotations

import inspect
import logging
import random
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from aurora.research.factory.spec import StrategySpec

_log = logging.getLogger(__name__)


@runtime_checkable
class HypothesisGenerator(Protocol):
    """Structural type every generator must satisfy."""

    name: str

    def generate(self, n: int, seed: int) -> list[StrategySpec]: ...


# ---------------------------------------------------------------------------
# GA-driven generator
# ---------------------------------------------------------------------------


class GAHypothesisGenerator:
    """Wrap a :class:`~aurora.ga.runner.GARunner` Pareto front into specs.

    The GA produces (params, fitness) pairs. We convert each Pareto entry
    into a :class:`StrategySpec` whose ``parent_spec_id`` is set to a
    common ancestor id passed in at construction time, so a downstream
    auditor can see "this batch came from GA run X".
    """

    name = "ga"

    def __init__(
        self,
        strategy_class_path: str,
        pareto_front: list[tuple[dict[str, Any], Any]],
        *,
        universe: Optional[list[str]] = None,
        rebalance: str = "1d",
        parent_spec_id: Optional[str] = None,
        hypothesis: str = "GA-discovered candidate from Pareto front.",
    ) -> None:
        self.strategy_class_path = strategy_class_path
        self.pareto_front = list(pareto_front)
        self.universe = list(universe or ["SPY"])
        self.rebalance = rebalance
        self.parent_spec_id = parent_spec_id
        self.hypothesis = hypothesis

    def generate(self, n: int, seed: int) -> list[StrategySpec]:
        rng = random.Random(int(seed))
        # ``self.pareto_front`` is the canonical source. ``n`` may exceed
        # the Pareto size; we sample with replacement only when callers
        # explicitly ask for more than we have.
        if not self.pareto_front:
            return []
        if n <= len(self.pareto_front):
            picks = self.pareto_front[:n]
        else:
            picks = list(self.pareto_front)
            while len(picks) < n:
                picks.append(rng.choice(self.pareto_front))
        out: list[StrategySpec] = []
        for params, fitness in picks:
            edge = 0.0
            if isinstance(fitness, (list, tuple)) and fitness:
                try:
                    edge = float(fitness[0]) * 1e4  # rough bps interpretation
                except (TypeError, ValueError):
                    edge = 0.0
            out.append(StrategySpec.make(
                name=f"ga:{self.strategy_class_path.rsplit('.', 1)[-1]}",
                hypothesis=self.hypothesis,
                expected_edge_bps=edge,
                strategy_class=self.strategy_class_path,
                params=dict(params),
                universe=list(self.universe),
                rebalance=self.rebalance,
                parent_spec_id=self.parent_spec_id,
                generator=self.name,
            ))
        return out


# ---------------------------------------------------------------------------
# Template / zoo-driven generator
# ---------------------------------------------------------------------------


class TemplateHypothesisGenerator:
    """Sample template entries from :class:`StrategyZoo`-style descriptors.

    The generator accepts a list of ``(name, strategy_class, base_params,
    param_jitter)`` tuples and produces N specs by jittering the base
    parameters. ``param_jitter`` is a dict mapping ``param_key`` to a
    ``(lo_factor, hi_factor)`` tuple. For each int param, the new value
    is ``int(base * uniform(lo_factor, hi_factor))``; for floats, it is
    ``base * uniform(...)``; bools / strings pass through unchanged.

    This generator is deliberately simple: a real "auto research" loop
    would plug a richer search distribution here. The shape exists so
    tests can drive the factory without depending on the full
    StrategyZoo registry.
    """

    name = "template"

    def __init__(
        self,
        templates: list[tuple[str, str, dict[str, Any], dict[str, tuple[float, float]]]],
        *,
        universe: Optional[list[str]] = None,
        rebalance: str = "1d",
        hypothesis_prefix: str = "Template-derived candidate",
    ) -> None:
        self.templates = list(templates)
        self.universe = list(universe or ["SPY"])
        self.rebalance = rebalance
        self.hypothesis_prefix = hypothesis_prefix

    def generate(self, n: int, seed: int) -> list[StrategySpec]:
        rng = random.Random(int(seed))
        if not self.templates:
            return []
        out: list[StrategySpec] = []
        for _ in range(n):
            name, strat_path, base_params, jitter = rng.choice(self.templates)
            params = self._jitter(base_params, jitter, rng)
            out.append(StrategySpec.make(
                name=name,
                hypothesis=f"{self.hypothesis_prefix}: {name}",
                expected_edge_bps=0.0,
                strategy_class=strat_path,
                params=params,
                universe=list(self.universe),
                rebalance=self.rebalance,
                generator=self.name,
            ))
        return out

    @staticmethod
    def _jitter(
        base: dict[str, Any],
        jitter: dict[str, tuple[float, float]],
        rng: random.Random,
    ) -> dict[str, Any]:
        out = dict(base)
        for k, (lo, hi) in jitter.items():
            if k not in out:
                continue
            v = out[k]
            factor = rng.uniform(lo, hi)
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                out[k] = max(1, int(round(v * factor)))
            elif isinstance(v, float):
                out[k] = float(v * factor)
        return out


# ---------------------------------------------------------------------------
# LLM-driven stub generator
# ---------------------------------------------------------------------------


class LLMHypothesisGenerator:
    """Optional LLM-driven generator.

    The shape exists so a real backend (e.g. Anthropic Messages, an
    in-house LLM, etc.) can be plugged in. By default the generator
    refuses to act if no client was injected, so the factory's tests can
    exercise the failure path without needing network credentials.
    """

    name = "llm"

    def __init__(
        self,
        client: Any = None,
        *,
        prompt_builder: Optional[Callable[..., Any]] = None,
        universe: Optional[list[str]] = None,
        rebalance: str = "1d",
    ) -> None:
        self.client = client
        self.prompt_builder = prompt_builder
        self.universe = list(universe or ["SPY"])
        self.rebalance = rebalance

    def generate(self, n: int, seed: int) -> list[StrategySpec]:
        if self.client is None:
            raise RuntimeError(
                "LLMHypothesisGenerator: no client injected. "
                "Construct with a client (e.g. anthropic.Anthropic) "
                "or use TemplateHypothesisGenerator."
            )
        # The actual call shape depends on the client. We avoid hard-coding
        # a vendor here; the prompt_builder is supposed to translate the
        # request into a vendor-specific call. The shape of the response
        # we expect is: ``list[dict]`` where each dict has ``name``,
        # ``hypothesis``, ``strategy_class``, ``params`` keys.
        if not callable(self.prompt_builder):
            raise RuntimeError(
                "LLMHypothesisGenerator: prompt_builder callable required."
            )
        try:
            raw = self.prompt_builder(self.client, n=n, seed=seed)
        except Exception as exc:
            raise RuntimeError(
                f"LLMHypothesisGenerator: prompt_builder failed: {exc}"
            ) from exc
        if not isinstance(raw, list):
            raise RuntimeError(
                "LLMHypothesisGenerator: prompt_builder must return list[dict]"
            )
        out: list[StrategySpec] = []
        for d in raw:
            out.append(StrategySpec.make(
                name=str(d.get("name", "llm:candidate")),
                hypothesis=str(d.get("hypothesis", "LLM-proposed candidate")),
                expected_edge_bps=float(d.get("expected_edge_bps", 0.0)),
                regime_dependence=list(d.get("regime_dependence") or []),
                failure_modes=list(d.get("failure_modes") or []),
                strategy_class=str(d.get("strategy_class", "")),
                params=dict(d.get("params") or {}),
                universe=list(d.get("universe") or self.universe),
                rebalance=str(d.get("rebalance", self.rebalance)),
                generator=self.name,
            ))
        return out


__all__ = [
    "GAHypothesisGenerator",
    "HypothesisGenerator",
    "LLMHypothesisGenerator",
    "TemplateHypothesisGenerator",
]
