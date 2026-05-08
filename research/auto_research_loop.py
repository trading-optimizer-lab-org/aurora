"""Auto Research Loop.

Closed-loop hypothesis-generation -> backtest -> critique -> next-hypothesis
driver. Uses an LLM (lazy anthropic import) for ideation and critique, but
falls back cleanly to a MockLLM for tests so the loop can be exercised
offline without network or API keys.

Loop stages:

    1. propose_hypothesis  -- ask the LLM (or mock) for a hypothesis
       described by {name, signal_fn_template, params}.
    2. instantiate_signal -- build a signal_fn from the template using a
       small whitelist of named primitives (so the loop never executes
       arbitrary Python from the LLM output).
    3. backtest -- run quantforge.core.engine.run_backtest on supplied prices.
    4. critique -- ask the LLM to comment on the metrics; record critique.
    5. record -- append (hypothesis, metrics, critique) to the trail.
    6. next -- repeat until n_iterations reached.

The signal templates are intentionally constrained to:
    * "all_long"       -- weights = 1
    * "all_flat"       -- weights = 0
    * "tsmom"          -- TSMomentum with given lookback/skip
    * "macross"        -- MACross with given fast/slow
    * "bollinger"      -- BollingerMR with given period/num_std
    * "lookback_mom"   -- _LookbackMomentum-equivalent inline

This list is enforced at signal-build time so the loop is safe to run
against an untrusted LLM response.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
import json
import logging
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library.tsmom import TSMomentum
from quantforge.strategies.library.ma_cross import MACross
from quantforge.strategies.library.bollinger_mr import BollingerMR


log = logging.getLogger(__name__)


# ---- Whitelisted signal templates ----------------------------------------


def _signal_all_long(prices: pd.Series, **_: Any) -> np.ndarray:
    return np.ones(len(prices))


def _signal_all_flat(prices: pd.Series, **_: Any) -> np.ndarray:
    return np.zeros(len(prices))


def _signal_tsmom(prices: pd.Series, lookback: int = 60, skip: int = 0,
                  **_: Any) -> np.ndarray:
    return TSMomentum(lookback=int(lookback), skip=int(skip)).signals(prices)


def _signal_macross(prices: pd.Series, fast: int = 20, slow: int = 100,
                    **_: Any) -> np.ndarray:
    return MACross(fast=int(fast), slow=int(slow)).signals(prices)


def _signal_bollinger(prices: pd.Series, period: int = 20,
                      num_std: float = 2.0, **_: Any) -> np.ndarray:
    return BollingerMR(period=int(period), num_std=float(num_std)).signals(prices)


def _signal_lookback_mom(prices: pd.Series, lookback: int = 60,
                         threshold: float = 0.0, **_: Any) -> np.ndarray:
    p = prices.values.astype(float)
    n = len(p)
    sig = np.zeros(n)
    L = int(lookback)
    for i in range(L, n):
        if p[i - L] > 0:
            r = p[i] / p[i - L] - 1.0
            if r > threshold:
                sig[i] = 1.0
    return sig


_TEMPLATES: dict[str, Callable[..., np.ndarray]] = {
    "all_long": _signal_all_long,
    "all_flat": _signal_all_flat,
    "tsmom": _signal_tsmom,
    "macross": _signal_macross,
    "bollinger": _signal_bollinger,
    "lookback_mom": _signal_lookback_mom,
}


# ---- LLM protocol --------------------------------------------------------


class LLMLike(Protocol):
    """Minimal interface used by AutoResearchLoop."""
    def propose(self, context: str) -> dict: ...
    def critique(self, hypothesis: dict, results: dict) -> str: ...


class MockLLM:
    """Deterministic LLM stub for tests.

    Cycles through a fixed list of hypothesis templates, returning each in
    turn. Critique is a templated string referencing the observed sharpe
    and calmar.
    """

    DEFAULT_HYPOTHESES = [
        {"name": "tsmom_60_0", "template": "tsmom",
         "params": {"lookback": 60, "skip": 0}},
        {"name": "macross_10_50", "template": "macross",
         "params": {"fast": 10, "slow": 50}},
        {"name": "bollinger_20_2", "template": "bollinger",
         "params": {"period": 20, "num_std": 2.0}},
        {"name": "lookback_mom_120",
         "template": "lookback_mom", "params": {"lookback": 120}},
    ]

    def __init__(self, hypotheses: list[dict] | None = None):
        self._hypotheses = hypotheses or self.DEFAULT_HYPOTHESES
        self._idx = 0

    def propose(self, context: str) -> dict:
        h = self._hypotheses[self._idx % len(self._hypotheses)]
        self._idx += 1
        return dict(h)  # copy

    def critique(self, hypothesis: dict, results: dict) -> str:
        sharpe = results.get("sharpe", 0.0)
        calmar = results.get("calmar", 0.0)
        verdict = "promising" if sharpe > 0.5 else "weak"
        return (f"Hypothesis {hypothesis.get('name')!r}: sharpe={sharpe:.3f}, "
                f"calmar={calmar:.3f}, verdict={verdict}.")


# ---- Loop record ---------------------------------------------------------


@dataclass
class IterationRecord:
    iteration: int
    hypothesis: dict[str, Any]
    metrics: dict[str, float]
    critique: str


@dataclass
class LoopReport:
    n_iterations: int
    trail: list[IterationRecord] = field(default_factory=list)

    def best_by(self, metric: str = "sharpe") -> IterationRecord | None:
        if not self.trail:
            return None
        valid = [r for r in self.trail
                 if metric in r.metrics
                 and not np.isnan(r.metrics[metric])
                 and not np.isinf(r.metrics[metric])]
        if not valid:
            return None
        return max(valid, key=lambda r: r.metrics[metric])


# ---- The loop ------------------------------------------------------------


class AutoResearchLoop:
    """LLM-driven research loop: hypothesis -> backtest -> critique -> next."""

    def __init__(self, llm: LLMLike | None = None, n_iterations: int = 4,
                 ppy: int = 252):
        if n_iterations < 1:
            raise ValueError("n_iterations must be >= 1")
        self.llm: LLMLike = llm if llm is not None else MockLLM()
        self.n_iterations = int(n_iterations)
        self.ppy = int(ppy)

    def _build_signal(self, hypothesis: dict) -> Callable:
        tmpl_name = hypothesis.get("template")
        if tmpl_name not in _TEMPLATES:
            raise ValueError(
                f"unknown signal template {tmpl_name!r}; "
                f"allowed: {sorted(_TEMPLATES)}"
            )
        params = hypothesis.get("params", {}) or {}

        def signal_fn(prices: pd.Series) -> np.ndarray:
            return _TEMPLATES[tmpl_name](prices, **params)

        return signal_fn

    def run(self, prices: pd.Series, initial_context: str = ""
            ) -> LoopReport:
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        report = LoopReport(n_iterations=0)
        context = initial_context or "Initial context: explore single-asset systematic strategies."
        for i in range(self.n_iterations):
            hypothesis = self.llm.propose(context)
            if not isinstance(hypothesis, dict):
                raise TypeError("llm.propose() must return dict")
            try:
                signal_fn = self._build_signal(hypothesis)
            except ValueError as e:
                # Skip bad templates but still log to the trail with empty metrics
                log.debug("auto_research_loop: bad hypothesis %r: %s", hypothesis, e)
                report.trail.append(IterationRecord(
                    iteration=i, hypothesis=hypothesis, metrics={},
                    critique=f"rejected: {e}",
                ))
                report.n_iterations = i + 1
                context = (f"Previous hypothesis was rejected: {e}. "
                           "Propose a new one using an allowed template.")
                continue
            result = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=self.ppy)
            m = result.metrics
            metrics = {
                "sharpe": float(m.sharpe), "calmar": float(m.calmar),
                "cagr": float(m.cagr), "mdd": float(m.mdd),
                "sortino": float(m.sortino),
            }
            critique = self.llm.critique(hypothesis, metrics)
            report.trail.append(IterationRecord(
                iteration=i, hypothesis=hypothesis,
                metrics=metrics, critique=critique,
            ))
            report.n_iterations = i + 1
            # next iteration's context = current critique
            context = critique
        return report
