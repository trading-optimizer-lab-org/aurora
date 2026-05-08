"""AI Auto-CEO — LLM acts as fund CEO.

Reads news headlines, current positions, and recent PnL, then makes
strategic decisions: capital allocation across strategies and
promote/demote signals. The LLM call is fully mocked so tests run
offline and deterministically.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Optional


def _mock_llm(prompt: str) -> str:
    """Deterministic stand-in for an LLM call.

    Returns a pseudo decision keyed by a stable hash of the prompt.
    """
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    bucket = int(h[:4], 16) % 3
    return ("risk_on", "neutral", "risk_off")[bucket]


@dataclass
class AIAutoCEO:
    """LLM-as-CEO that allocates capital and promotes / demotes strategies.

    Parameters
    ----------
    risk_budget : float
        Total fraction of capital available for risk in (0, 1].
    llm : Callable[[str], str], optional
        Override the mock LLM with a custom callable.
    """

    risk_budget: float = 0.6
    llm: Callable[[str], str] = field(default=_mock_llm)

    def __post_init__(self) -> None:
        if not (0.0 < self.risk_budget <= 1.0):
            raise ValueError("risk_budget must be in (0, 1]")

    def _build_prompt(
        self,
        news: list[str],
        positions: dict[str, float],
        pnl: dict[str, float],
    ) -> str:
        parts = [
            "You are CEO of a quant fund. Decide stance.",
            f"Headlines: {' | '.join(news[:10])}",
            f"Positions: {positions}",
            f"PnL: {pnl}",
        ]
        return "\n".join(parts)

    def decide(
        self,
        news: list[str],
        positions: dict[str, float],
        pnl: dict[str, float],
    ) -> dict:
        """Return a strategic decision package."""
        prompt = self._build_prompt(news, positions, pnl)
        stance = self.llm(prompt)
        if stance not in ("risk_on", "neutral", "risk_off"):
            stance = "neutral"

        scaler = {"risk_on": 1.0, "neutral": 0.5, "risk_off": 0.2}[stance]
        gross = self.risk_budget * scaler

        promote: list[str] = []
        demote: list[str] = []
        for strat, p in pnl.items():
            if p > 0:
                promote.append(strat)
            elif p < 0:
                demote.append(strat)

        n = max(len(promote), 1)
        allocation = {s: gross / n for s in promote}

        return {
            "stance": stance,
            "gross_exposure": gross,
            "allocation": allocation,
            "promote": promote,
            "demote": demote,
        }
