"""LLM-based portfolio manager.

Wraps an Anthropic Claude client to translate news + macro context into
target portfolio weights. The class accepts any callable client that exposes
a ``messages.create(...)`` method matching the official ``anthropic`` SDK.
A ``MockAnthropicClient`` is provided for testing.

Outputs are always normalised: weights sum to 1.0 (long-only) or to a value
in [-1, 1] when shorts are allowed; absolute values are clipped to
``max_weight``. Parsing is defensive: any malformed model reply produces an
equal-weight fallback rather than raising.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    import anthropic  # type: ignore
    ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]
    ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class LLMPortfolioConfig:
    """Hyperparameters for :class:`LLMPortfolioManager`."""

    universe: Sequence[str] = field(default_factory=lambda: ("SPY", "TLT", "GLD", "USO"))
    max_weight: float = 0.4
    allow_shorts: bool = False
    model: str = "claude-opus-4-7"
    max_tokens: int = 1024


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class _MockMessage:
    def __init__(self, text: str):
        self.content = [type("Block", (), {"text": text, "type": "text"})()]


class MockAnthropicClient:
    """Deterministic stub returning a configurable JSON payload.

    Use in tests instead of the real ``anthropic.Anthropic`` client.
    """

    def __init__(self, reply_text: str = '{"SPY": 0.6, "TLT": 0.4}'):
        self.reply_text = reply_text
        self.call_log: List[Dict[str, Any]] = []
        # Mimic ``client.messages.create``
        self.messages = self  # type: ignore[assignment]

    def create(self, **kwargs) -> _MockMessage:
        self.call_log.append(kwargs)
        return _MockMessage(self.reply_text)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class LLMPortfolioManager:
    """Decides target weights via an LLM call.

    Parameters
    ----------
    client:
        An object exposing ``client.messages.create(model=..., max_tokens=...,
        messages=[...])``. Pass :class:`MockAnthropicClient` for tests, or an
        ``anthropic.Anthropic()`` instance in production.
    config:
        :class:`LLMPortfolioConfig` overrides.
    """

    def __init__(
        self,
        client: Any,
        config: Optional[LLMPortfolioConfig] = None,
    ):
        if client is None:
            raise ValueError("client must not be None; pass MockAnthropicClient for tests")
        self.client = client
        self.config = config if config is not None else LLMPortfolioConfig()
        if not (0.0 < self.config.max_weight <= 1.0):
            raise ValueError("max_weight must be in (0, 1]")
        if len(self.config.universe) < 1:
            raise ValueError("universe must be non-empty")

    # ------------------------------------------------------------------ prompt

    def _build_prompt(self, news: Sequence[str], macro: Dict[str, float]) -> str:
        bullet_news = "\n".join(f"- {n}" for n in news[:10]) or "(no news)"
        macro_str = "\n".join(f"- {k}: {v:.4g}" for k, v in macro.items()) or "(no data)"
        universe = ", ".join(self.config.universe)
        side_hint = (
            "Weights may be negative (shorts allowed)."
            if self.config.allow_shorts
            else "All weights must be in [0, 1]."
        )
        return (
            f"You are a portfolio manager. Return target weights as a single "
            f"JSON object whose keys are exactly: {universe}.\n"
            f"{side_hint} Each weight |w| <= {self.config.max_weight}.\n\n"
            f"News:\n{bullet_news}\n\nMacro:\n{macro_str}\n\n"
            "Return ONLY the JSON object."
        )

    # ------------------------------------------------------------------ parse

    @staticmethod
    def _extract_text(message: Any) -> str:
        try:
            for block in message.content:
                if getattr(block, "type", "text") == "text":
                    return str(block.text)
            return ""
        except (AttributeError, TypeError):
            return ""

    def _parse(self, text: str) -> Dict[str, float]:
        # Find first {...} JSON-shaped substring
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in parsed.items():
            if not isinstance(k, str):
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return out

    def _normalise(self, raw: Dict[str, float]) -> Dict[str, float]:
        """Project to allowed simplex / box. Equal weights as fallback.

        Long-only path:
          1. Drop negatives -> 0.
          2. Iteratively normalise sum to 1 then clip excess to ``max_weight``;
             redistribute the clipped mass to the remaining names. Stops when
             no name exceeds the cap.
        Short path:
          Clip each |w| <= max_weight, then scale so ||w||_1 <= 1.
        """
        universe = list(self.config.universe)
        cleaned: Dict[str, float] = {k: 0.0 for k in universe}
        for k, v in raw.items():
            if k in cleaned:
                cleaned[k] = v
        cap = self.config.max_weight

        if self.config.allow_shorts:
            for k in cleaned:
                cleaned[k] = float(np.clip_local(cleaned[k], -cap, cap))
            total = sum(abs(v) for v in cleaned.values())
            if total > 1.0:
                cleaned = {k: v / total for k, v in cleaned.items()}
            return cleaned

        # Long-only: drop negatives.
        for k in cleaned:
            if cleaned[k] < 0:
                cleaned[k] = 0.0

        total = sum(cleaned.values())
        if total <= 0:
            # Equal-weight fallback (also obeys cap if cap >= 1/N).
            eq = 1.0 / len(universe)
            if eq > cap:
                # If cap forbids equal weight, fall back to uniform-cap-truncate
                cleaned = {k: cap for k in universe}
                total = sum(cleaned.values())
            else:
                cleaned = {k: eq for k in universe}
                total = 1.0
            cleaned = {k: v / total for k, v in cleaned.items()}
            return cleaned

        # Iterate: normalise then cap. Distribute excess to under-cap names.
        for _ in range(10):
            cleaned = {k: v / sum(cleaned.values()) for k, v in cleaned.items()}
            excess = 0.0
            for k in cleaned:
                if cleaned[k] > cap:
                    excess += cleaned[k] - cap
                    cleaned[k] = cap
            if excess <= 1e-9:
                break
            # Distribute excess uniformly across names that are still below cap.
            free = [k for k in cleaned if cleaned[k] < cap - 1e-9]
            if not free:
                # No headroom; we have already saturated. Just normalise.
                break
            share = excess / len(free)
            for k in free:
                cleaned[k] += share
        return cleaned

    # ------------------------------------------------------------------ public

    def decide(self, news: Sequence[str], macro: Dict[str, float]) -> Dict[str, float]:
        """Synchronous LLM call returning normalised target weights."""
        if not isinstance(news, (list, tuple)):
            raise TypeError("news must be a list or tuple of strings")
        if not isinstance(macro, dict):
            raise TypeError("macro must be a dict[str, float]")

        prompt = self._build_prompt(news, macro)
        message = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = self._extract_text(message)
        raw = self._parse(text)
        return self._normalise(raw)


# ---------------------------------------------------------------------------
# Tiny shim so the module does not require numpy import at top-level just for
# clipping. Using a local helper keeps the module self-contained.
# ---------------------------------------------------------------------------


class _NumpyShim:
    @staticmethod
    def clip_local(value: float, lo: float, hi: float) -> float:
        if value < lo:
            return lo
        if value > hi:
            return hi
        return value


np = _NumpyShim()  # type: ignore[assignment]


__all__ = [
    "ANTHROPIC_AVAILABLE",
    "LLMPortfolioConfig",
    "LLMPortfolioManager",
    "MockAnthropicClient",
]
