"""Black-Litterman with LLM-generated views.

Drives BL views from an LLM (Claude API) reading recent news + macro context.
The LLM call is encapsulated so callers can inject a stub for testing without
hitting the network. When the SDK / API key are missing, ``allocate`` falls
back to the no-views BL posterior (i.e. CAPM-implied prior weights).

Output is a 1-row DataFrame of posterior weights indexed by the date of the
allocation call, suitable for stacking across time.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

from aurora.deployment.black_litterman import (
    BlackLittermanModel,
    market_implied_returns,
)


# ----------- LLM view-generator -------------------------------------------- #
def _default_llm_view_generator(
    assets: list,
    news_text: str,
    macro_text: str,
) -> tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
    """Default LLM view generator.

    Tries to call Claude via the ``anthropic`` SDK; falls back to no views
    when the SDK or API key are missing. The function never raises on
    network errors; on failure it returns ``(None, None)``.

    The schema asked of the model is a JSON list of view dicts:
        [{"asset": "AAPL", "expected_return": 0.05, "confidence": 0.6}, ...]

    Returned tuple is ``(views_p, views_q)`` consumable by
    :class:`BlackLittermanModel`.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None, None

    prompt = (
        "You are a quantitative analyst generating Black-Litterman views.\n"
        f"Assets: {assets}\n"
        f"Recent news:\n{news_text}\n"
        f"Macro context:\n{macro_text}\n\n"
        "Output a JSON array of objects with keys 'asset', 'expected_return' "
        "(decimal, e.g. 0.05 for 5%), and 'confidence' (0 < c <= 1). "
        "Limit to at most 5 views. Output ONLY the JSON array, nothing else."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(block, "text", "") for block in msg.content
        )
    except Exception:
        return None, None

    import json
    try:
        # Handle markdown fencing if model wraps json in ```json ... ```.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)
    except Exception:
        return None, None

    if not isinstance(data, list) or not data:
        return None, None

    rows, q_vals = [], []
    for view in data:
        try:
            asset = view["asset"]
            er = float(view["expected_return"])
        except (KeyError, TypeError, ValueError):
            continue
        if asset not in assets:
            continue
        row = {a: 0.0 for a in assets}
        row[asset] = 1.0
        rows.append(row)
        q_vals.append(er)

    if not rows:
        return None, None

    p = pd.DataFrame(rows, columns=assets)
    q = pd.Series(q_vals)
    return p, q


@dataclass
class BLLLMConfig:
    """Configuration for :class:`BLLLMViews`."""
    risk_aversion: float = 2.5
    tau: float = 0.05
    view_confidence: float = 0.5
    lookback: int = 252
    view_generator: Callable = field(default=_default_llm_view_generator)


@dataclass
class BLLLMResult:
    """Output of :meth:`BLLLMViews.allocate`."""
    weights: pd.DataFrame                # 1-row indexed by allocation date
    posterior_returns: pd.Series
    views_p: pd.DataFrame
    views_q: pd.Series
    used_llm_views: bool                 # False if generator returned None


class BLLLMViews:
    """Black-Litterman where views come from an LLM.

    Args:
        config: :class:`BLLLMConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[BLLLMConfig] = None):
        self.config = config or BLLLMConfig()

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: pd.DataFrame,
        market_caps: Optional[pd.Series] = None,
        news_text: str = "",
        macro_text: str = "",
        as_of: Optional[datetime] = None,
    ) -> BLLLMResult:
        """Generate posterior BL weights using LLM-derived views.

        Args:
            prices: TxN price DataFrame.
            market_caps: per-asset market cap (positive). Falls back to equal
                if missing.
            news_text: free-form recent news passed to the LLM.
            macro_text: free-form macro context passed to the LLM.
            as_of: timestamp to label the output row. Defaults to the last
                index of ``prices`` (or ``utcnow`` if not a datetime).
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 2:
            raise ValueError(f"need >= 2 assets, got {prices.shape[1]}")

        assets = list(prices.columns)
        rets = prices.pct_change().dropna().tail(self.config.lookback)
        if len(rets) < 2:
            raise ValueError("insufficient returns history")
        cov = rets.cov()

        if market_caps is None:
            market_caps = pd.Series(1.0, index=assets)
        mc = market_caps.reindex(assets).fillna(1.0)
        mc = mc.where(mc > 0, 1.0)
        pi = market_implied_returns(
            mc, cov, risk_aversion=self.config.risk_aversion
        )

        views_p, views_q = self.config.view_generator(
            assets=assets,
            news_text=news_text,
            macro_text=macro_text,
        )
        used = views_p is not None and views_q is not None and len(views_p) > 0

        bl = BlackLittermanModel(
            pi, cov,
            views_p=views_p if used else None,
            views_q=views_q if used else None,
            view_confidence=self.config.view_confidence,
            tau=self.config.tau,
        )
        w = bl.optimal_weights(risk_aversion=self.config.risk_aversion)
        w = w.clip(lower=0.0)
        s = w.sum()
        if s > 0:
            w = w / s
        else:
            w = pd.Series(1.0 / len(assets), index=assets)

        if as_of is None:
            try:
                as_of = pd.to_datetime(prices.index[-1])
            except Exception:
                as_of = datetime.utcnow()

        weights_df = pd.DataFrame(
            [w.reindex(assets).values], index=[as_of], columns=assets,
        )
        return BLLLMResult(
            weights=weights_df,
            posterior_returns=bl.posterior_returns(),
            views_p=bl.views_p,
            views_q=bl.views_q,
            used_llm_views=used,
        )
