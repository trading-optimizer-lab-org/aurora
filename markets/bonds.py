"""Bond yield curve, butterfly trades, duration / convexity.

Builds a discount curve from par yields via a straightforward bootstrap and
provides duration/convexity for fixed-coupon bonds plus a 2-5-10 butterfly
spread signal.

Mock generator returns a typical upward-sloping curve for tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class BondConfig:
    """Curve / pricing settings.

    Attributes:
        compounding: 'annual' or 'semi'. Affects bond price/duration math.
        butterfly_legs: tenors (years) for the butterfly: (wing, body, wing).
        seed: mock generator seed.
    """
    compounding: str = "semi"
    butterfly_legs: tuple[float, float, float] = (2.0, 5.0, 10.0)
    seed: int = 13


class BondYieldCurve:
    """Yield curve + bond analytics."""

    _CURVE_COLS = ("tenor", "par_yield", "discount", "zero_rate")

    def __init__(self, config: Optional[BondConfig] = None) -> None:
        self.config = config or BondConfig()

    def analyze(self, par_yields: Optional[dict[float, float]] = None,
                mock: bool = True) -> pd.DataFrame:
        """Return a curve DataFrame: tenor, par_yield, discount, zero_rate."""
        if par_yields is None:
            if not mock:
                raise NotImplementedError("Live curve feed not configured.")
            par_yields = self._mock_par_yields()
        return self.build_curve(par_yields)

    def build_curve(self, par_yields: dict[float, float]) -> pd.DataFrame:
        """Bootstrap zero rates from par yields."""
        tenors = sorted(par_yields)
        rows = []
        # m = pmts per year
        m = 2 if self.config.compounding == "semi" else 1
        # Use a continuously compounded zero rate where the discount factor is
        # exp(-z*T). We solve for the zero rate at each tenor sequentially so
        # that the bond at par yield prices exactly to par.
        zero_curve: dict[float, float] = {}
        for T in tenors:
            c = par_yields[T]  # annual coupon rate
            n_periods = max(1, int(round(T * m)))
            coupon = c / m
            # Sum of discounted coupons using already-bootstrapped rates,
            # interpolating onto coupon dates.
            pv_coupons = 0.0
            for k in range(1, n_periods):
                t_k = k / m
                z_k = self._interp_zero(t_k, zero_curve)
                pv_coupons += coupon * np.exp(-z_k * t_k)
            # Final payment = (1 + coupon) at T; solve for z(T).
            target = 1.0 - pv_coupons  # PV of last cashflow
            final_cf = 1.0 + coupon
            if target <= 0 or final_cf <= 0:
                z_T = c  # fallback
            else:
                z_T = -np.log(target / final_cf) / T
            zero_curve[T] = z_T
            rows.append({"tenor": T, "par_yield": c,
                         "discount": float(np.exp(-z_T * T)),
                         "zero_rate": z_T})
        return pd.DataFrame(rows, columns=list(self._CURVE_COLS))

    @staticmethod
    def _interp_zero(t: float, curve: dict[float, float]) -> float:
        """Linear interpolation on zero rates; flat extrapolation."""
        if not curve:
            return 0.0
        ts = sorted(curve)
        if t <= ts[0]:
            return curve[ts[0]]
        if t >= ts[-1]:
            return curve[ts[-1]]
        for i in range(1, len(ts)):
            if t <= ts[i]:
                t0, t1 = ts[i - 1], ts[i]
                w = (t - t0) / (t1 - t0)
                return curve[t0] + w * (curve[t1] - curve[t0])
        return curve[ts[-1]]

    def duration_convexity(self, coupon: float, T: float, ytm: float,
                           face: float = 100.0) -> dict:
        """Macaulay duration, modified duration, convexity, price.

        Coupon and ytm are decimals (0.05 = 5%). Compounding follows config.
        """
        m = 2 if self.config.compounding == "semi" else 1
        n = max(1, int(round(T * m)))
        c = coupon * face / m
        y_period = ytm / m
        price = 0.0
        weighted_t = 0.0
        convexity = 0.0
        for k in range(1, n + 1):
            cf = c + (face if k == n else 0.0)
            t_year = k / m
            df = (1.0 + y_period) ** (-k)
            pv = cf * df
            price += pv
            weighted_t += t_year * pv
            convexity += k * (k + 1) * cf * (1.0 + y_period) ** (-k - 2)
        macaulay = weighted_t / price if price > 0 else 0.0
        modified = macaulay / (1.0 + y_period)
        convexity = convexity / (price * (m ** 2)) if price > 0 else 0.0
        return {"price": price, "macaulay_duration": macaulay,
                "modified_duration": modified, "convexity": convexity}

    def signals(self, curve: pd.DataFrame) -> pd.DataFrame:
        """Butterfly spread on configured legs (negative = body cheap)."""
        if curve.empty:
            return pd.DataFrame(columns=["wing_short", "body", "wing_long",
                                         "butterfly_bps"])
        w1, b, w2 = self.config.butterfly_legs
        y_w1 = self._yield_at(curve, w1)
        y_b = self._yield_at(curve, b)
        y_w2 = self._yield_at(curve, w2)
        # Butterfly = body - 0.5 * (wing1 + wing2). Negative => body rich.
        bp = (y_b - 0.5 * (y_w1 + y_w2)) * 1e4
        return pd.DataFrame([{
            "wing_short": w1, "body": b, "wing_long": w2,
            "butterfly_bps": float(bp),
        }])

    @staticmethod
    def _yield_at(curve: pd.DataFrame, T: float) -> float:
        """Interpolate par yield at tenor T from a built curve."""
        ts = curve["tenor"].to_numpy()
        ys = curve["par_yield"].to_numpy()
        return float(np.interp(T, ts, ys))

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_par_yields(self) -> dict[float, float]:
        rng = np.random.default_rng(self.config.seed)
        # Upward-sloping with small noise.
        tenors = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0]
        base = [0.045, 0.046, 0.045, 0.044, 0.042, 0.043, 0.044, 0.045]
        noise = rng.normal(0, 0.0005, len(tenors))
        return {t: float(b + n) for t, b, n in zip(tenors, base, noise)}
