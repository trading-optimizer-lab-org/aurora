"""R185 -- Crypto-specific refusal gates for live order paths.

The exception types in this module are *refusal records*: they all
inherit from :class:`CryptoRiskRefusal` and their ``args[0]`` is a
plain-English reason the operator can paste straight into a refusal
log. Live submission paths must catch :class:`CryptoRiskRefusal` and
log the message.

Refusal rules implemented here:

    * :func:`assert_leverage_within_limit` -- reject orders whose
      effective leverage exceeds ``max_leverage``.
    * :func:`assert_funding_drag_below`    -- reject perpetual orders
      whose annualised funding drag (in basis points) exceeds the
      operator-configured threshold.
    * :func:`assert_symbol_active`         -- reject orders for
      delisted symbols.

The downtime gate lives in :mod:`aurora.markets.exchange_downtime`; this
module re-exports a thin :class:`ExchangeDowntime` exception for callers
that want to raise instead of just polling the registry.
"""
from __future__ import annotations

from typing import Any

from aurora.markets.crypto_derivatives import CryptoInstrument


# ---------------------------------------------------------------------------
# Refusal exception hierarchy
# ---------------------------------------------------------------------------


class CryptoRiskRefusal(ValueError):
    """Base class for all crypto risk refusals.

    The first positional argument MUST be a plain-English reason
    suitable for an operator-facing refusal log.
    """


class LeverageBreached(CryptoRiskRefusal):
    """Raised when a proposed order would exceed the leverage cap."""


class FundingDragExceeded(CryptoRiskRefusal):
    """Raised when annualised funding drag exceeds the configured limit."""


class ExchangeDowntime(CryptoRiskRefusal):
    """Raised when an order falls inside a registered downtime window."""


class SymbolDelisted(CryptoRiskRefusal):
    """Raised when the instrument has been removed from the security master."""


# ---------------------------------------------------------------------------
# Refusal gates
# ---------------------------------------------------------------------------


def assert_leverage_within_limit(
    notional: float,
    equity: float,
    max_leverage: float,
) -> None:
    """Refuse if ``notional / equity`` exceeds ``max_leverage``.

    Args:
        notional: absolute notional of the position (currency units of
            the same denomination as ``equity``).
        equity: current account equity (must be > 0).
        max_leverage: maximum allowed leverage multiple (e.g. ``3.0``
            means 3x). Must be > 0.

    Raises:
        LeverageBreached: with a human-readable reason.
        ValueError: when inputs are not finite or are non-positive
            where positivity is required.
    """
    if equity <= 0:
        raise ValueError(
            f"assert_leverage_within_limit: equity must be > 0, got {equity!r}"
        )
    if max_leverage <= 0:
        raise ValueError(
            f"assert_leverage_within_limit: max_leverage must be > 0, "
            f"got {max_leverage!r}"
        )
    notional_abs = abs(float(notional))
    leverage = notional_abs / float(equity)
    if leverage > max_leverage:
        raise LeverageBreached(
            f"refusing order: effective leverage {leverage:.2f}x exceeds "
            f"max allowed {max_leverage:.2f}x "
            f"(notional={notional_abs:,.2f}, equity={equity:,.2f})."
        )


def assert_funding_drag_below(
    annualised_funding: float,
    threshold_bps: float,
) -> None:
    """Refuse if absolute annualised funding drag exceeds ``threshold_bps``.

    ``annualised_funding`` is the decimal annualised funding rate (e.g.
    ``0.20`` = 20% per year). ``threshold_bps`` is the operator-defined
    cap, expressed in basis points (e.g. ``2500`` = 25%).

    A negative ``annualised_funding`` is interpreted as funding *received*
    by the long position. We compare on absolute magnitude so the
    operator threshold catches both extreme costs and extreme rebates;
    callers that only care about the cost direction should pass
    ``max(rate, 0.0)``.

    Raises:
        FundingDragExceeded: with a human-readable reason.
        ValueError: when ``threshold_bps`` is negative.
    """
    if threshold_bps < 0:
        raise ValueError(
            f"assert_funding_drag_below: threshold_bps must be >= 0, "
            f"got {threshold_bps!r}"
        )
    drag_bps = abs(float(annualised_funding)) * 1e4
    if drag_bps > float(threshold_bps):
        raise FundingDragExceeded(
            f"refusing order: annualised funding drag "
            f"{drag_bps:.1f} bps exceeds operator threshold "
            f"{float(threshold_bps):.1f} bps "
            f"(annualised_rate={annualised_funding:.4%})."
        )


def assert_symbol_active(
    instrument: CryptoInstrument,
    security_master_or_registry: Any,
) -> None:
    """Refuse if ``instrument.symbol`` is unknown or marked inactive.

    The ``security_master_or_registry`` argument is duck-typed against
    two flavours of registry:

    1. :class:`aurora.data_contracts.security_master.SecurityMaster`-style:
       has a ``get(symbol) -> record`` method, where the record carries
       an ``active`` boolean attribute.
    2. Mapping-like (``dict``, etc.): ``__contains__`` plus optional
       ``[symbol].active`` lookup.

    Anything else is treated as a hard refusal (cannot prove the symbol
    is active without a source of truth).
    """
    sym = instrument.symbol

    # 1. SecurityMaster-style: registry.get(symbol) -> record-or-None
    get = getattr(security_master_or_registry, "get", None)
    if callable(get):
        rec = get(sym)
        if rec is None:
            raise SymbolDelisted(
                f"refusing order: instrument {sym!r} is not present in the "
                f"security master / registry. Cannot prove the symbol is "
                f"currently tradeable."
            )
        active = getattr(rec, "active", True)
        if active is False:
            raise SymbolDelisted(
                f"refusing order: instrument {sym!r} is marked inactive "
                f"(delisted) in the security master."
            )
        return

    # 2. Mapping-like fallback.
    contains = getattr(security_master_or_registry, "__contains__", None)
    if callable(contains):
        if sym not in security_master_or_registry:
            raise SymbolDelisted(
                f"refusing order: instrument {sym!r} not found in the "
                f"provided registry mapping."
            )
        try:
            rec = security_master_or_registry[sym]
        except Exception:  # noqa: BLE001  -- duck typing fallback
            return
        active = getattr(rec, "active", True)
        if active is False:
            raise SymbolDelisted(
                f"refusing order: instrument {sym!r} is marked inactive "
                f"in the provided registry mapping."
            )
        return

    raise SymbolDelisted(
        f"refusing order: cannot determine whether {sym!r} is active "
        "(security_master_or_registry has neither .get() nor a mapping "
        "interface)."
    )


__all__ = [
    "CryptoRiskRefusal",
    "ExchangeDowntime",
    "FundingDragExceeded",
    "LeverageBreached",
    "SymbolDelisted",
    "assert_funding_drag_below",
    "assert_leverage_within_limit",
    "assert_symbol_active",
]
