"""R164 - Mandatory benchmark comparison pack.

Strategy reports must compare against a fixed set of naive baselines
before promotion. Builds a deterministic :class:`BenchmarkPack` that
records every baseline's metrics, the seed used for the random baseline,
and a plain-language verdict per baseline.

Baselines:

* ``cash`` -- zero return.
* ``buy_and_hold`` -- raw asset returns.
* ``equal_weight`` -- equal-weight basket where multi-asset returns are
  supplied; degrades to buy-and-hold when only one return stream exists.
* ``sixty_forty`` -- 0.6 equity + 0.4 bond proxy when bond returns are
  provided; otherwise marked unavailable.
* ``simple_momentum`` -- long if trailing 20-period return > 0.
* ``simple_mean_reversion`` -- long if trailing 5-period return < 0.
* ``random_comparable_turnover`` -- random sign series; deterministic
  via ``random_seed``.
* ``previous_production`` -- supplied production return series, when
  available.

The pack is the unit of evidence: validation reports must include it
unaltered, evidence packs hash it, and promotion gates can require
``beats_baseline`` for the strategy's primary baseline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


_PERIODS_PER_YEAR_DEFAULT = 252


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


Verdict = str  # "beats" | "ties" | "fails" | "inconclusive" | "unavailable"


@dataclass(frozen=True)
class BaselineMetric:
    """Per-baseline metrics inside a :class:`BenchmarkPack`."""

    name: str
    available: bool
    annualised_return: float
    annualised_volatility: float
    sharpe: float
    excess_return: float
    excess_sharpe: float
    sharpe_diff: float
    verdict: Verdict
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkPack:
    """Aggregate of mandatory baselines vs a strategy."""

    strategy_id: str
    primary_baseline: str
    periods_per_year: int
    random_seed: int
    metrics: Tuple[BaselineMetric, ...]
    overall_verdict: Verdict
    pack_hash: str
    n_periods: int

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_baseline": self.primary_baseline,
            "periods_per_year": self.periods_per_year,
            "random_seed": self.random_seed,
            "metrics": [m.to_dict() for m in self.metrics],
            "overall_verdict": self.overall_verdict,
            "pack_hash": self.pack_hash,
            "n_periods": self.n_periods,
        }

    def metric(self, name: str) -> BaselineMetric:
        for m in self.metrics:
            if m.name == name:
                return m
        raise KeyError(name)

    def beats(self, name: str) -> bool:
        return self.metric(name).verdict == "beats"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_array(arr: Any) -> np.ndarray:
    return np.asarray(arr, dtype=float).ravel()


def _annualise_return(returns: np.ndarray, periods_per_year: int) -> float:
    if returns.size == 0:
        return 0.0
    return float(np.mean(returns) * periods_per_year)


def _annualise_vol(returns: np.ndarray, periods_per_year: int) -> float:
    if returns.size == 0:
        return 0.0
    std = float(np.std(returns, ddof=0))
    if std == 0.0 or not np.isfinite(std):
        return 0.0
    return std * float(np.sqrt(periods_per_year))


def _annualise_sharpe(returns: np.ndarray, periods_per_year: int) -> float:
    vol = _annualise_vol(returns, periods_per_year)
    if vol == 0.0:
        return 0.0
    return _annualise_return(returns, periods_per_year) / vol


def _verdict(
    sharpe_diff: float, *,
    beat_threshold: float = 0.05,
    tie_band: float = 0.05,
) -> Verdict:
    if not np.isfinite(sharpe_diff):
        return "inconclusive"
    if sharpe_diff > beat_threshold:
        return "beats"
    if sharpe_diff < -beat_threshold:
        return "fails"
    if abs(sharpe_diff) <= tie_band:
        return "ties"
    return "inconclusive"


def _hash_pack(metrics: Tuple[BaselineMetric, ...], strategy_id: str, seed: int) -> str:
    payload = {
        "strategy_id": strategy_id,
        "random_seed": seed,
        "metrics": [m.to_dict() for m in metrics],
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _simple_momentum_returns(asset: np.ndarray, lookback: int = 20) -> np.ndarray:
    n = asset.size
    out = np.zeros(n, dtype=float)
    for i in range(lookback, n):
        if float(np.sum(asset[i - lookback:i])) > 0:
            out[i] = asset[i]
    return out


def _simple_mean_reversion_returns(asset: np.ndarray, lookback: int = 5) -> np.ndarray:
    n = asset.size
    out = np.zeros(n, dtype=float)
    for i in range(lookback, n):
        if float(np.sum(asset[i - lookback:i])) < 0:
            out[i] = asset[i]
    return out


def _random_signs(asset: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.choice([-1.0, 1.0], size=asset.size) * asset


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def build_benchmark_pack(
    strategy_returns: Any,
    asset_returns: Any,
    *,
    strategy_id: str,
    primary_baseline: str = "buy_and_hold",
    bond_returns: Optional[Any] = None,
    basket_returns: Optional[Any] = None,
    production_returns: Optional[Any] = None,
    periods_per_year: int = _PERIODS_PER_YEAR_DEFAULT,
    random_seed: int = 0,
) -> BenchmarkPack:
    """Build a :class:`BenchmarkPack` for ``strategy_returns``.

    All series are aligned to the shortest common length. ``primary_baseline``
    selects which baseline drives the overall verdict. ``random_seed`` is
    recorded inside the pack so the random baseline is reproducible.
    """
    s = _to_array(strategy_returns)
    a = _to_array(asset_returns)
    n = int(min(s.size, a.size))
    s, a = s[:n], a[:n]

    bond = _to_array(bond_returns)[:n] if bond_returns is not None else None
    basket = _to_array(basket_returns)[:n] if basket_returns is not None else None
    prod = _to_array(production_returns)[:n] if production_returns is not None else None

    sharpe_s = _annualise_sharpe(s, periods_per_year)

    def _eval(name: str, baseline: np.ndarray, *, available: bool, note: str = "") -> BaselineMetric:
        if not available or baseline.size == 0:
            return BaselineMetric(
                name=name,
                available=False,
                annualised_return=0.0,
                annualised_volatility=0.0,
                sharpe=0.0,
                excess_return=0.0,
                excess_sharpe=0.0,
                sharpe_diff=0.0,
                verdict="unavailable",
                note=note or "baseline series not provided",
            )
        excess = s - baseline
        sharpe_b = _annualise_sharpe(baseline, periods_per_year)
        diff = sharpe_s - sharpe_b
        return BaselineMetric(
            name=name,
            available=True,
            annualised_return=_annualise_return(baseline, periods_per_year),
            annualised_volatility=_annualise_vol(baseline, periods_per_year),
            sharpe=sharpe_b,
            excess_return=_annualise_return(excess, periods_per_year),
            excess_sharpe=_annualise_sharpe(excess, periods_per_year),
            sharpe_diff=diff,
            verdict=_verdict(diff),
            note=note,
        )

    cash = np.zeros(n, dtype=float)
    bh = a.copy()
    if basket is not None:
        eq_weight = basket
        eq_note = "from supplied basket_returns"
    else:
        eq_weight = a.copy()
        eq_note = "single-asset; degrades to buy_and_hold"
    if bond is not None:
        sixty_forty = 0.6 * a + 0.4 * bond
        sf_available = True
        sf_note = "0.6 equity + 0.4 bond"
    else:
        sixty_forty = np.zeros(n, dtype=float)
        sf_available = False
        sf_note = "bond_returns not supplied"

    momentum = _simple_momentum_returns(a)
    mean_rev = _simple_mean_reversion_returns(a)
    rand = _random_signs(a, random_seed)
    if prod is not None:
        prev_prod = prod
        prod_available = True
        prod_note = "previous production returns supplied"
    else:
        prev_prod = np.zeros(n, dtype=float)
        prod_available = False
        prod_note = "no previous production reference"

    metrics: List[BaselineMetric] = [
        _eval("cash", cash, available=True),
        _eval("buy_and_hold", bh, available=True),
        _eval(
            "equal_weight", eq_weight, available=True, note=eq_note,
        ),
        _eval(
            "sixty_forty", sixty_forty, available=sf_available, note=sf_note,
        ),
        _eval("simple_momentum", momentum, available=True),
        _eval("simple_mean_reversion", mean_rev, available=True),
        _eval(
            "random_comparable_turnover", rand, available=True,
            note=f"seed={random_seed}",
        ),
        _eval(
            "previous_production", prev_prod, available=prod_available,
            note=prod_note,
        ),
    ]

    metrics_t = tuple(metrics)
    primary = next((m for m in metrics_t if m.name == primary_baseline), None)
    if primary is None:
        raise ValueError(
            f"primary_baseline {primary_baseline!r} not in the pack"
        )
    overall = primary.verdict if primary.available else "inconclusive"
    pack_hash = _hash_pack(metrics_t, strategy_id, random_seed)
    return BenchmarkPack(
        strategy_id=strategy_id,
        primary_baseline=primary_baseline,
        periods_per_year=periods_per_year,
        random_seed=random_seed,
        metrics=metrics_t,
        overall_verdict=overall,
        pack_hash=pack_hash,
        n_periods=n,
    )


def required_pack_keys() -> Tuple[str, ...]:
    """Return the canonical set of baselines a strategy report must include."""
    return (
        "cash",
        "buy_and_hold",
        "equal_weight",
        "sixty_forty",
        "simple_momentum",
        "simple_mean_reversion",
        "random_comparable_turnover",
        "previous_production",
    )


def assert_pack_complete(pack: BenchmarkPack) -> None:
    """Raise ``ValueError`` if ``pack`` is missing a mandatory baseline."""
    have = {m.name for m in pack.metrics}
    missing = [b for b in required_pack_keys() if b not in have]
    if missing:
        raise ValueError(
            f"benchmark pack missing required baselines: {missing}"
        )


__all__ = [
    "BaselineMetric",
    "BenchmarkPack",
    "Verdict",
    "assert_pack_complete",
    "build_benchmark_pack",
    "required_pack_keys",
]
