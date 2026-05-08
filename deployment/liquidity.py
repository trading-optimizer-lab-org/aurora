"""Liquidity-aware position sizing (Task L.2).

Builds a per-asset ``LiquidityProfile`` from price/volume history and exposes
sizing helpers that cap positions by ADV (average daily dollar volume) so the
portfolio cannot demand more liquidity than the market can supply.

Pipeline:
    compute_liquidity_profile(prices, volume) -> LiquidityProfile
        |
        v
    liquidity_adjusted_size / adv_constrained_position / liquidity_haircut
        |
        v
    LiquidityAwarePortfolio.adjust_weights(raw_weights) -> capped weights

Classification thresholds (USD ADV):
    high      > 100M
    medium    10M - 100M
    low       1M  - 10M
    illiquid  < 1M

Haircut factors applied on top of ADV cap:
    high     1.0
    medium   0.7
    low      0.4
    illiquid 0.0  (block trade)

References:
    Almgren-Chriss participation rate framework (see ``core/slippage.py``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADV_HIGH = 100_000_000.0   # > 100M USD -> high
_ADV_MED = 10_000_000.0     # 10M - 100M  -> medium
_ADV_LOW = 1_000_000.0      # 1M  - 10M   -> low
                            # < 1M        -> illiquid

# Default ADV thresholds exposed for callers that want to inspect or override.
# Keys are tier names; values are USD ADV lower bounds for each tier.
# A symbol falls into the highest tier whose threshold it exceeds (strict for
# 'high', inclusive for 'medium' / 'low'); below all thresholds -> 'illiquid'.
_DEFAULT_ADV_THRESHOLDS: dict[str, float] = {
    "high": _ADV_HIGH,
    "medium": _ADV_MED,
    "low": _ADV_LOW,
}

_HAIRCUTS: dict[str, float] = {
    "high": 1.0,
    "medium": 0.7,
    "low": 0.4,
    "illiquid": 0.0,
}

_VALID_CLASSES = frozenset(_HAIRCUTS.keys())


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class LiquidityProfile:
    """Snapshot of an asset's liquidity characteristics."""

    symbol: str
    avg_daily_volume_usd: float
    avg_spread_bps: float
    days_above_threshold_pct: float
    classification: str
    liquidity_score: float


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------


def _classify_adv(adv_usd: float, thresholds: dict | None = None) -> str:
    """Classify ADV into 'high'/'medium'/'low'/'illiquid'.

    Args:
        adv_usd: average daily dollar volume.
        thresholds: optional override for the high/medium/low cutoffs. Keys
            'high', 'medium', 'low' map to USD lower bounds. Missing keys fall
            back to ``_DEFAULT_ADV_THRESHOLDS``.
    """
    th = dict(_DEFAULT_ADV_THRESHOLDS)
    if thresholds:
        for k in ("high", "medium", "low"):
            if k in thresholds:
                th[k] = float(thresholds[k])
    if adv_usd > th["high"]:
        return "high"
    if adv_usd >= th["medium"]:
        return "medium"
    if adv_usd >= th["low"]:
        return "low"
    return "illiquid"


def _adv_score(adv_usd: float) -> float:
    """Map ADV (USD) to a 0-100 sub-score using log scale.

    1M -> ~0, 10M -> ~33, 100M -> ~67, 1B -> 100.
    """
    if adv_usd <= 0:
        return 0.0
    log_adv = np.log10(adv_usd)
    # Anchor: 6.0 (1M) -> 0, 9.0 (1B) -> 100. Clip to [0,100].
    score = (log_adv - 6.0) * (100.0 / 3.0)
    return float(np.clip(score, 0.0, 100.0))


def _spread_score(spread_bps: float) -> float:
    """Lower spread -> higher score. 1bps -> ~100, 100bps -> 0."""
    if spread_bps <= 0:
        # Unknown / zero spread reported -> neutral 50.
        return 50.0
    # Clip 1bps..100bps band.
    s = float(np.clip(spread_bps, 1.0, 100.0))
    return 100.0 * (1.0 - (np.log10(s) / np.log10(100.0)))


def compute_liquidity_profile(
    prices: pd.Series,
    volume: pd.Series,
    spread_history: pd.Series | None = None,
    min_adv_usd: float = 1e6,
    ADV_THRESHOLDS: dict | None = None,
) -> LiquidityProfile:
    """Compute a ``LiquidityProfile`` from price/volume history.

    Args:
        prices: close prices (positive). Index used as the symbol if ``name`` set.
        volume: share volume. Aligned to ``prices`` by index intersection.
        spread_history: optional series of spreads in bps. Mean used as proxy.
        min_adv_usd: threshold for ``days_above_threshold_pct``.
        ADV_THRESHOLDS: optional dict overriding the default classification
            cutoffs. Keys 'high', 'medium', 'low' map to USD ADV lower bounds.
            When None (default), uses ``_DEFAULT_ADV_THRESHOLDS``.

    Returns:
        LiquidityProfile with classification and 0-100 score.
    """
    if prices is None or volume is None:
        raise ValueError("prices and volume must be provided")

    px = pd.Series(prices).astype(float)
    vol = pd.Series(volume).astype(float)
    common = px.index.intersection(vol.index)
    if len(common) == 0:
        raise ValueError("prices and volume have no overlapping index")
    px = px.loc[common]
    vol = vol.loc[common]

    dollar_vol = (px * vol).dropna()
    adv = float(dollar_vol.mean()) if len(dollar_vol) else 0.0
    if not np.isfinite(adv):
        adv = 0.0

    if len(dollar_vol):
        days_above = float((dollar_vol > min_adv_usd).mean()) * 100.0
    else:
        days_above = 0.0

    # Resolve effective thresholds for both classification and the spread proxy
    # so that custom thresholds shape both signals consistently.
    th = dict(_DEFAULT_ADV_THRESHOLDS)
    if ADV_THRESHOLDS:
        for k in ("high", "medium", "low"):
            if k in ADV_THRESHOLDS:
                th[k] = float(ADV_THRESHOLDS[k])

    if spread_history is not None and len(spread_history) > 0:
        avg_spread = float(pd.Series(spread_history).astype(float).mean())
    else:
        # Crude proxy: lower ADV -> wider implied spread.
        if adv >= th["high"]:
            avg_spread = 2.0
        elif adv >= th["medium"]:
            avg_spread = 5.0
        elif adv >= th["low"]:
            avg_spread = 15.0
        else:
            avg_spread = 50.0

    classification = _classify_adv(adv, thresholds=th)

    # Blended score: 50% ADV, 30% spread, 20% days_above pct.
    score = (
        0.50 * _adv_score(adv)
        + 0.30 * _spread_score(avg_spread)
        + 0.20 * float(np.clip(days_above, 0.0, 100.0))
    )
    score = float(np.clip(score, 0.0, 100.0))

    symbol = (
        getattr(prices, "name", None)
        or getattr(volume, "name", None)
        or "UNKNOWN"
    )

    return LiquidityProfile(
        symbol=str(symbol),
        avg_daily_volume_usd=adv,
        avg_spread_bps=avg_spread,
        days_above_threshold_pct=days_above,
        classification=classification,
        liquidity_score=score,
    )


# ---------------------------------------------------------------------------
# Sizing helpers
# ---------------------------------------------------------------------------


def liquidity_haircut(weight: float, classification: str) -> float:
    """Apply classification-based haircut to a weight.

    high=1.0, medium=0.7, low=0.4, illiquid=0.0. Unknown class -> 0.
    """
    factor = _HAIRCUTS.get(classification, 0.0)
    return float(weight) * factor


def liquidity_adjusted_size(
    target_size_usd: float,
    liquidity_profile: LiquidityProfile,
    max_pct_adv: float = 0.05,
) -> float:
    """Cap target position USD by ``max_pct_adv * ADV`` then apply haircut.

    Operates on the absolute target magnitude and re-signs the result so
    short orders (negative ``target_size_usd``) are capped symmetrically
    instead of being silently zeroed.

    Returns 0 for illiquid or non-positive ADV.
    """
    if max_pct_adv <= 0 or target_size_usd == 0:
        return 0.0
    adv = liquidity_profile.avg_daily_volume_usd
    if adv <= 0:
        return 0.0
    sign = 1.0 if float(target_size_usd) > 0 else -1.0
    magnitude = abs(float(target_size_usd))
    adv_cap = adv * max_pct_adv
    capped = min(magnitude, adv_cap)
    haircut_mag = liquidity_haircut(capped, liquidity_profile.classification)
    return sign * float(haircut_mag)


def adv_constrained_position(
    target_weight: float,
    nav: float,
    price: float,
    daily_volume_usd: float,
    max_pct_adv: float = 0.05,
) -> tuple[float, int]:
    """Convert a target weight to ADV-constrained (weight, share_count).

    Supports short targets: negative ``target_weight`` is capped on its
    magnitude and re-signed so the returned ``(adjusted_weight, n_shares)``
    preserves direction (negative shares == short).

    The share count is floored toward zero; ``adjusted_weight`` reflects
    the actual notional after the cap and integer rounding.
    """
    if nav <= 0 or price <= 0 or target_weight == 0:
        return 0.0, 0
    if max_pct_adv <= 0 or daily_volume_usd <= 0:
        return 0.0, 0

    sign = 1.0 if float(target_weight) > 0 else -1.0
    target_notional_mag = abs(float(target_weight)) * float(nav)
    adv_cap = float(daily_volume_usd) * float(max_pct_adv)
    notional_mag = min(target_notional_mag, adv_cap)

    n_shares_mag = int(notional_mag // float(price))
    n_shares_mag = max(0, n_shares_mag)
    realised_notional_mag = n_shares_mag * float(price)
    adjusted_weight = sign * (realised_notional_mag / float(nav))
    n_shares = int(sign * n_shares_mag)
    return adjusted_weight, n_shares


def participation_rate_warning(
    order_size_usd: float,
    daily_volume_usd: float,
    warn_threshold: float = 0.10,
) -> str | None:
    """Return a warning message if order > ``warn_threshold * ADV``."""
    if daily_volume_usd <= 0:
        return "ADV is zero or negative; cannot estimate participation"
    if order_size_usd <= 0:
        return None
    part = float(order_size_usd) / float(daily_volume_usd)
    if part > warn_threshold:
        return (
            f"order is {part * 100:.2f}% of ADV "
            f"(>{warn_threshold * 100:.2f}% threshold)"
        )
    return None


# ---------------------------------------------------------------------------
# Portfolio wrapper
# ---------------------------------------------------------------------------


class LiquidityAwarePortfolio:
    """Cap raw weights by per-asset liquidity, redistribute slack proportionally.

    Args:
        liquidity_profiles: dict[symbol -> LiquidityProfile].
        nav: portfolio value (USD).
        max_pct_adv: per-position cap (default 5% of ADV).
    """

    def __init__(
        self,
        liquidity_profiles: dict[str, LiquidityProfile],
        nav: float,
        max_pct_adv: float = 0.05,
    ) -> None:
        if nav <= 0:
            raise ValueError("nav must be positive")
        if max_pct_adv <= 0:
            raise ValueError("max_pct_adv must be positive")
        self.liquidity_profiles = dict(liquidity_profiles)
        self.nav = float(nav)
        self.max_pct_adv = float(max_pct_adv)

    def _max_weight(self, symbol: str) -> float:
        prof = self.liquidity_profiles.get(symbol)
        if prof is None:
            # No profile -> treat as illiquid -> blocked.
            return 0.0
        if prof.classification == "illiquid":
            return 0.0
        adv_cap_usd = prof.avg_daily_volume_usd * self.max_pct_adv
        haircut = _HAIRCUTS.get(prof.classification, 0.0)
        # Max weight after haircut.
        cap_usd = adv_cap_usd * haircut
        return cap_usd / self.nav

    def adjust_weights(
        self, raw_weights: dict[str, float], return_residual: bool = False
    ) -> dict[str, float] | tuple[dict[str, float], float]:
        """Cap each weight by ADV constraint, redistribute slack proportionally.

        Algorithm:
            1. Compute per-symbol cap.
            2. Initial assignment: ``min(raw_weight, cap)`` per symbol.
            3. Slack = sum(raw - assigned) over capped symbols.
            4. Distribute slack among uncapped symbols proportional to their
               raw weights, then re-cap. Repeat until either slack is exhausted
               or every symbol with room is already at cap.
            5. After the proportional loop ends, if any slack remains, distribute
               it once more across remaining capacity (proportional to residual
               room). If after that some slack still cannot be placed because
               every symbol is at cap, surface it as ``residual_slack``.

        Args:
            raw_weights: dict[symbol -> raw weight].
            return_residual: if True, return (adjusted_weights, residual_slack).
                When False (default), return only adjusted_weights for backward
                compatibility.
        """
        if not raw_weights:
            return ({}, 0.0) if return_residual else {}

        weights = {s: float(w) for s, w in raw_weights.items() if w > 0}
        if not weights:
            empty = {s: 0.0 for s in raw_weights}
            return (empty, 0.0) if return_residual else empty

        caps = {s: self._max_weight(s) for s in weights}

        # Initial cap pass.
        adjusted: dict[str, float] = {}
        slack = 0.0
        for sym, w in weights.items():
            cap = caps[sym]
            if w <= cap:
                adjusted[sym] = w
            else:
                adjusted[sym] = cap
                slack += (w - cap)

        # Redistribution loop.
        max_rounds = len(weights) + 2
        for _ in range(max_rounds):
            if slack <= 1e-15:
                break
            # Names with remaining headroom under their cap.
            with_room = {
                s: weights[s] for s in weights if caps[s] > adjusted[s] + 1e-15
            }
            base_total = sum(with_room.values())
            if base_total <= 0:
                break

            new_slack = 0.0
            for sym, raw_w in with_room.items():
                share = raw_w / base_total
                add = slack * share
                cap = caps[sym]
                room = cap - adjusted[sym]
                if add <= room:
                    adjusted[sym] += add
                else:
                    adjusted[sym] = cap
                    new_slack += (add - room)
            slack = new_slack

        # Final pass: if loop exited with slack > 0 but symbols still have
        # residual capacity, distribute proportional to remaining room.
        if slack > 1e-15:
            room_map = {
                s: caps[s] - adjusted[s]
                for s in weights
                if caps[s] - adjusted[s] > 1e-15
            }
            total_room = sum(room_map.values())
            if total_room > 0:
                if slack <= total_room:
                    # All slack fits when allocated by remaining room.
                    for sym, room in room_map.items():
                        adjusted[sym] += slack * (room / total_room)
                    slack = 0.0
                else:
                    # Cap-fill all rooms; residual remains.
                    for sym, room in room_map.items():
                        adjusted[sym] = caps[sym]
                    slack -= total_room

        out = {s: 0.0 for s in raw_weights}
        for s, v in adjusted.items():
            out[s] = float(v)
        residual = float(max(slack, 0.0))
        if return_residual:
            return out, residual
        return out


__all__ = [
    "LiquidityProfile",
    "compute_liquidity_profile",
    "liquidity_adjusted_size",
    "adv_constrained_position",
    "liquidity_haircut",
    "participation_rate_warning",
    "LiquidityAwarePortfolio",
]
