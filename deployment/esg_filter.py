"""ESG screening filter for portfolios.

Excludes assets failing E (Environmental), S (Social) and G (Governance)
score thresholds. Scores can come from a mock dict (for testing) or an
external provider (MSCI API stubbed here so the module stays usable
offline).

Output is a 1-row DataFrame on the assets that PASS the screen, equal-weighted
by default (the user can plug an inner allocator that consumes the passing
asset list separately).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


_VALID_SOURCES = ("mock", "msci")


@dataclass
class ESGConfig:
    """Configuration for :class:`ESGFilter`."""
    score_source: str = "mock"
    e_threshold: float = 5.0          # 0-10 scale; >= passes
    s_threshold: float = 5.0
    g_threshold: float = 5.0
    require_all: bool = True          # True = AND across E,S,G; False = OR
    mock_scores: dict = field(default_factory=dict)  # asset -> dict(E=, S=, G=)
    msci_api_key: Optional[str] = None
    inner_weights: Optional[pd.Series] = None  # optional pre-computed weights

    def __post_init__(self) -> None:
        if self.score_source not in _VALID_SOURCES:
            raise ValueError(f"score_source {self.score_source!r} not in {_VALID_SOURCES}")
        for f in ("e_threshold", "s_threshold", "g_threshold"):
            v = getattr(self, f)
            if not (0.0 <= v <= 10.0):
                raise ValueError(f"{f} must be in [0, 10], got {v}")


@dataclass
class ESGFilterResult:
    """Output of :meth:`ESGFilter.allocate`."""
    weights: pd.DataFrame              # 1-row, columns = assets passing screen
    scores: pd.DataFrame               # asset x [E,S,G] for the universe
    excluded: list                     # tickers failing the screen
    pass_mask: pd.Series               # bool per asset


def _fetch_msci_scores(assets: list, api_key: Optional[str]) -> pd.DataFrame:
    """MSCI ESG API stub.

    Real wiring would hit https://api.msci.com/esg/... ; here we deterministically
    derive a (3,) score vector per asset from the ticker hash so tests stay
    offline-reproducible.
    """
    rows = {}
    for a in assets:
        h = abs(hash(a))
        rows[a] = {
            "E": float((h % 100) / 10.0),
            "S": float(((h // 100) % 100) / 10.0),
            "G": float(((h // 10_000) % 100) / 10.0),
        }
    return pd.DataFrame(rows).T


class ESGFilter:
    """Exclude assets failing E/S/G score thresholds.

    Args:
        config: :class:`ESGConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[ESGConfig] = None):
        self.config = config or ESGConfig()

    # --------------------------------------------------------------------- #
    def _scores(self, assets: list) -> pd.DataFrame:
        if self.config.score_source == "mock":
            rows = {}
            for a in assets:
                ms = self.config.mock_scores.get(a, {"E": 5.0, "S": 5.0, "G": 5.0})
                rows[a] = {k: float(ms.get(k, 5.0)) for k in ("E", "S", "G")}
            return pd.DataFrame(rows).T
        return _fetch_msci_scores(assets, self.config.msci_api_key)

    # --------------------------------------------------------------------- #
    def allocate(self, prices: pd.DataFrame) -> ESGFilterResult:
        """Apply ESG screen and equal-weight survivors."""
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 1:
            raise ValueError("need >= 1 asset")

        assets = list(prices.columns)
        scores = self._scores(assets)
        e_ok = scores["E"] >= self.config.e_threshold
        s_ok = scores["S"] >= self.config.s_threshold
        g_ok = scores["G"] >= self.config.g_threshold
        if self.config.require_all:
            mask = e_ok & s_ok & g_ok
        else:
            mask = e_ok | s_ok | g_ok

        survivors = [a for a in assets if bool(mask.loc[a])]
        excluded = [a for a in assets if not bool(mask.loc[a])]

        if not survivors:
            # All filtered out -> empty 1-row DataFrame on the original cols.
            weights_df = pd.DataFrame(
                [[0.0] * len(assets)], index=["esg"], columns=assets,
            )
        elif self.config.inner_weights is not None:
            iw = self.config.inner_weights.reindex(survivors).fillna(0.0)
            s_sum = iw.sum()
            if s_sum > 0:
                iw = iw / s_sum
            else:
                iw = pd.Series(1.0 / len(survivors), index=survivors)
            row = [float(iw.get(a, 0.0)) for a in assets]
            weights_df = pd.DataFrame([row], index=["esg"], columns=assets)
        else:
            ew = 1.0 / len(survivors)
            row = [ew if a in survivors else 0.0 for a in assets]
            weights_df = pd.DataFrame([row], index=["esg"], columns=assets)

        return ESGFilterResult(
            weights=weights_df,
            scores=scores,
            excluded=excluded,
            pass_mask=mask,
        )
