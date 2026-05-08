"""Retirement glide path: age-based equity/bond allocation.

Implements a configurable target-date glide path that ramps down equity
exposure as the investor approaches the target retirement year. Two preset
shapes are exposed:

- ``"linear"``      : equity = clip(start_equity - slope * years_elapsed)
- ``"target_date"`` : Vanguard-style two-leg curve (high equity until N
  years from target, then linear taper to retirement equity).

Risk-tolerance multiplier shifts the whole curve up (aggressive) or down
(conservative).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_VALID_SHAPES = ("linear", "target_date")


@dataclass
class GlidePathConfig:
    """Configuration for :class:`RetirementGlidePath`."""
    target_retirement_year: int = 2050
    current_age: int = 35
    retirement_age: int = 65
    start_equity: float = 0.90
    end_equity: float = 0.30
    shape: str = "target_date"
    risk_tolerance: float = 1.0   # multiplier in [0.5, 1.5]
    equity_assets: tuple = ("EQUITY",)
    bond_assets: tuple = ("BOND",)

    def __post_init__(self) -> None:
        if self.shape not in _VALID_SHAPES:
            raise ValueError(f"shape {self.shape!r} not in {_VALID_SHAPES}")
        if not (0.0 <= self.start_equity <= 1.0):
            raise ValueError("start_equity must be in [0,1]")
        if not (0.0 <= self.end_equity <= 1.0):
            raise ValueError("end_equity must be in [0,1]")
        if not (0.5 <= self.risk_tolerance <= 1.5):
            raise ValueError("risk_tolerance must be in [0.5, 1.5]")


@dataclass
class GlidePathResult:
    """Output of :meth:`RetirementGlidePath.allocate`."""
    weights: pd.DataFrame              # 1-row, columns = asset classes
    equity_pct: float
    bond_pct: float
    years_to_retirement: float


class RetirementGlidePath:
    """Age-based equity/bond mix.

    Args:
        config: :class:`GlidePathConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[GlidePathConfig] = None):
        self.config = config or GlidePathConfig()

    # --------------------------------------------------------------------- #
    def _years_to_retirement(self, as_of: datetime) -> float:
        years = self.config.target_retirement_year - as_of.year
        return float(years - (as_of.timetuple().tm_yday - 1) / 365.0)

    # --------------------------------------------------------------------- #
    def _equity_pct(self, years_left: float) -> float:
        cfg = self.config
        if cfg.shape == "linear":
            total_horizon = max(cfg.retirement_age - cfg.current_age, 1)
            elapsed = max(total_horizon - years_left, 0.0)
            slope = (cfg.start_equity - cfg.end_equity) / total_horizon
            eq = cfg.start_equity - slope * elapsed
        else:  # target_date
            # Hold start equity until 10y from retirement, then taper.
            taper_window = 10.0
            if years_left >= taper_window:
                eq = cfg.start_equity
            elif years_left <= 0:
                eq = cfg.end_equity
            else:
                ratio = (taper_window - years_left) / taper_window
                eq = cfg.start_equity - ratio * (cfg.start_equity - cfg.end_equity)
        eq = float(np.clip(eq * cfg.risk_tolerance, 0.0, 1.0))
        return eq

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: Optional[pd.DataFrame] = None,
        as_of: Optional[datetime] = None,
    ) -> GlidePathResult:
        """Compute equity/bond split for the configured glide path.

        ``prices`` is accepted for API uniformity but is not used by the
        glide path itself. The return DataFrame uses the configured asset
        names; if a ``prices`` DataFrame is provided we project onto its
        columns, splitting equally within the equity / bond buckets.
        """
        if as_of is None:
            as_of = datetime.utcnow()
        if isinstance(as_of, date) and not isinstance(as_of, datetime):
            as_of = datetime(as_of.year, as_of.month, as_of.day)
        years_left = self._years_to_retirement(as_of)
        eq_pct = self._equity_pct(years_left)
        bd_pct = 1.0 - eq_pct

        if prices is None:
            cols = list(self.config.equity_assets) + list(self.config.bond_assets)
            n_eq = len(self.config.equity_assets)
            n_bd = len(self.config.bond_assets)
            row = (
                [eq_pct / n_eq] * n_eq
                + [bd_pct / n_bd] * n_bd
            )
        else:
            cols = list(prices.columns)
            eq_present = [a for a in cols if a in self.config.equity_assets]
            bd_present = [a for a in cols if a in self.config.bond_assets]
            row = []
            for a in cols:
                if a in eq_present:
                    row.append(eq_pct / max(len(eq_present), 1))
                elif a in bd_present:
                    row.append(bd_pct / max(len(bd_present), 1))
                else:
                    row.append(0.0)
            # Renorm if there is a mix.
            s = sum(row)
            if s > 0:
                row = [x / s for x in row]

        weights_df = pd.DataFrame([row], index=["glide"], columns=cols)
        return GlidePathResult(
            weights=weights_df,
            equity_pct=eq_pct,
            bond_pct=bd_pct,
            years_to_retirement=years_left,
        )
