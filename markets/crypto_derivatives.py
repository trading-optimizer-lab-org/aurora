"""R185 -- Crypto derivatives instrument model + funding rate handling.

Models crypto SPOT, DATED_FUTURE and PERPETUAL as distinct instrument
kinds. Spot has neither expiry nor funding; dated futures have a fixed
expiry but no funding; perpetuals have a periodic funding payment that
accrues to (or against) the position holder.

Funding-rate sign convention used throughout this module:

    A *positive* funding rate means LONG positions PAY funding to SHORT
    positions for that interval (the standard Binance / Bybit convention
    when perpetual mark is above index).

So for the position-weighted PnL series:

    funding_cash_flow_long  = -position_qty * notional * funding_rate
    funding_cash_flow_short = +abs(position_qty) * notional * funding_rate

The :func:`apply_funding` helper subtracts ``position * notional * rate``
from each PnL sample, which yields the same sign convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Instrument kind enum
# ---------------------------------------------------------------------------


class CryptoInstrumentKind(str, Enum):
    """Distinct kinds of crypto instrument the engine can reason about."""

    SPOT = "spot"
    DATED_FUTURE = "dated_future"
    PERPETUAL = "perpetual"

    @classmethod
    def parse(cls, value: "str | CryptoInstrumentKind") -> "CryptoInstrumentKind":
        """Coerce a string or enum value to :class:`CryptoInstrumentKind`."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError(
                f"CryptoInstrumentKind.parse expected str or enum, got "
                f"{type(value).__name__}"
            )
        v = value.strip().lower()
        # Accept a few common aliases
        if v in {"future", "futures", "dated", "dated_future"}:
            return cls.DATED_FUTURE
        if v in {"perp", "perpetual", "swap"}:
            return cls.PERPETUAL
        if v in {"spot"}:
            return cls.SPOT
        raise ValueError(
            f"unknown CryptoInstrumentKind {value!r}; "
            f"expected one of {[k.value for k in cls]}"
        )


# ---------------------------------------------------------------------------
# Crypto instrument record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoInstrument:
    """A frozen, value-equal description of one crypto instrument.

    Attributes:
        symbol: exchange-native instrument symbol (e.g. ``BTCUSDT``,
            ``BTC-PERP``, ``BTC-26SEP25``).
        kind: SPOT / DATED_FUTURE / PERPETUAL.
        base_currency: e.g. ``BTC``.
        quote_currency: e.g. ``USDT``, ``USD``.
        exchange: exchange name as registered in
            :class:`aurora.markets.exchange_capability.ExchangeCapabilityRegistry`.
        contract_size: how much base currency one contract represents.
            Spot is conventionally 1.0; some exchanges quote inverse
            contracts (e.g. 100 USD).
        tick_size: minimum price increment.
        min_qty: minimum order quantity in contracts.
        expiry: settlement timestamp; mandatory for DATED_FUTURE,
            forbidden for SPOT and PERPETUAL.
        settlement_currency: currency in which PnL is settled. Often the
            quote currency for linear contracts; the base currency for
            inverse contracts.
    """

    symbol: str
    kind: CryptoInstrumentKind
    base_currency: str
    quote_currency: str
    exchange: str
    contract_size: float = 1.0
    tick_size: float = 0.01
    min_qty: float = 0.0
    expiry: Optional[pd.Timestamp] = None
    settlement_currency: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("CryptoInstrument.symbol must be non-empty")
        if not isinstance(self.kind, CryptoInstrumentKind):
            # Be permissive about enum coercion at construction time.
            object.__setattr__(self, "kind", CryptoInstrumentKind.parse(self.kind))
        if not self.base_currency or not self.quote_currency:
            raise ValueError(
                "CryptoInstrument.base_currency and quote_currency must be non-empty"
            )
        if not self.exchange:
            raise ValueError("CryptoInstrument.exchange must be non-empty")
        if self.contract_size <= 0:
            raise ValueError(
                f"contract_size must be > 0, got {self.contract_size!r}"
            )
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be > 0, got {self.tick_size!r}")
        if self.min_qty < 0:
            raise ValueError(f"min_qty must be >= 0, got {self.min_qty!r}")

        # Expiry rules:
        #   DATED_FUTURE  : MUST have expiry
        #   SPOT          : MUST NOT have expiry
        #   PERPETUAL     : MUST NOT have expiry (it is, by definition, perpetual)
        if self.kind == CryptoInstrumentKind.DATED_FUTURE:
            if self.expiry is None:
                raise ValueError(
                    "CryptoInstrument(kind=DATED_FUTURE) requires an expiry "
                    "Timestamp"
                )
            if not isinstance(self.expiry, pd.Timestamp):
                # Coerce: callers often pass strings or datetime.datetime.
                object.__setattr__(self, "expiry", pd.Timestamp(self.expiry))
        else:
            if self.expiry is not None:
                raise ValueError(
                    f"CryptoInstrument(kind={self.kind.value}) must not have "
                    f"an expiry; got {self.expiry!r}"
                )

        if self.settlement_currency is None:
            object.__setattr__(self, "settlement_currency", self.quote_currency)

    # Convenience predicates so callers don't import the enum just to ask.
    def is_spot(self) -> bool:
        return self.kind == CryptoInstrumentKind.SPOT

    def is_perpetual(self) -> bool:
        return self.kind == CryptoInstrumentKind.PERPETUAL

    def is_dated_future(self) -> bool:
        return self.kind == CryptoInstrumentKind.DATED_FUTURE


# ---------------------------------------------------------------------------
# Funding rate record + history container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundingRateRecord:
    """One funding-rate observation for a perpetual.

    Attributes:
        instrument_symbol: perpetual symbol (e.g. ``BTC-PERP``).
        exchange: exchange that published the rate.
        ts: observation timestamp (the time at which the rate is paid /
            settled). Coerced to a :class:`pd.Timestamp`.
        rate: per-interval funding rate (decimal). e.g. ``0.0001`` means
            "1 bp paid by longs to shorts at this funding event".
        interval_seconds: funding interval. Default is 8 hours (28800 s),
            which matches Binance / Bybit / OKX conventions.
        source: ingestion source (provider name, file, "manual_seed").
    """

    instrument_symbol: str
    exchange: str
    ts: pd.Timestamp
    rate: float
    interval_seconds: int = 28800  # 8 hours in seconds
    source: str = ""

    def __post_init__(self) -> None:
        if not self.instrument_symbol:
            raise ValueError("FundingRateRecord.instrument_symbol must be non-empty")
        if not self.exchange:
            raise ValueError("FundingRateRecord.exchange must be non-empty")
        if not isinstance(self.ts, pd.Timestamp):
            object.__setattr__(self, "ts", pd.Timestamp(self.ts))
        if self.interval_seconds <= 0:
            raise ValueError(
                f"FundingRateRecord.interval_seconds must be > 0, "
                f"got {self.interval_seconds!r}"
            )

    def annualised(self) -> float:
        """Return the annualised funding rate (simple compounding)."""
        per_year = (365.0 * 24.0 * 3600.0) / float(self.interval_seconds)
        return float(self.rate) * per_year


# ---------------------------------------------------------------------------
# apply_funding -- subtract funding cost from a position-weighted PnL series
# ---------------------------------------------------------------------------


def apply_funding(
    perp_pnl_seq: Sequence[float],
    funding_rates: Iterable[FundingRateRecord],
    position_seq: Sequence[float],
) -> np.ndarray:
    """Subtract per-step funding from a perpetual PnL series.

    Convention: a positive ``rate`` means longs pay shorts. So for each
    funding event ``i`` we do::

        funded_pnl[i] = pnl[i] - position[i] * rate[i]

    where ``rate[i]`` is taken from ``funding_rates[i]``. The caller is
    responsible for aligning ``perp_pnl_seq`` and ``position_seq`` to the
    same funding cadence as ``funding_rates``.

    Args:
        perp_pnl_seq: per-step PnL (already includes price moves), length
            ``N``.
        funding_rates: iterable of :class:`FundingRateRecord`, length ``N``.
            Order must align with the PnL/position sequences.
        position_seq: per-step position (positive = long, negative =
            short), length ``N``.

    Returns:
        ``np.ndarray`` of length ``N`` with funding deducted.
    """
    pnl = np.asarray(perp_pnl_seq, dtype=float)
    pos = np.asarray(position_seq, dtype=float)
    rates = np.asarray([float(fr.rate) for fr in funding_rates], dtype=float)
    if pnl.shape != pos.shape:
        raise ValueError(
            f"perp_pnl_seq and position_seq must have the same shape; "
            f"got {pnl.shape} vs {pos.shape}"
        )
    if rates.shape != pnl.shape:
        raise ValueError(
            f"funding_rates length must match PnL length; got "
            f"{rates.shape[0]} vs {pnl.shape[0]}"
        )
    funding_cash_flow = pos * rates
    return pnl - funding_cash_flow


__all__ = [
    "CryptoInstrument",
    "CryptoInstrumentKind",
    "FundingRateRecord",
    "apply_funding",
]
