"""R185 -- Exchange capability matrix.

Hand-curated, non-network capability registry that records which order
types, instrument kinds and time-in-force values each exchange supports.
The capability matrix is the single source of truth used by the refusal
gate :func:`assert_exchange_supports`; preflight code calls it before
any order leaves the engine.

The data here reflects publicly known capability of each exchange at the
time this module was written (operator-curated). It deliberately does
**not** make a network call.

Order-type vocabulary (frozen):

    ``market``       -- standard market order
    ``limit``        -- standard limit order
    ``stop``         -- stop-market
    ``stop_limit``   -- stop-limit
    ``post_only``    -- maker-only limit
    ``ioc``          -- immediate-or-cancel limit
    ``fok``          -- fill-or-kill limit

Time-in-force vocabulary:

    ``GTC``          -- good-til-cancelled
    ``IOC``          -- immediate-or-cancel
    ``FOK``          -- fill-or-kill
    ``DAY``          -- session order
    ``GTD``          -- good-til-date

Refer to public exchange API docs for the underlying capability claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Mapping, Optional

from aurora.markets.crypto_derivatives import CryptoInstrumentKind


# ---------------------------------------------------------------------------
# Refusal exception
# ---------------------------------------------------------------------------


class UnsupportedCapability(ValueError):
    """Raised by :func:`assert_exchange_supports` when the matrix says no.

    The exception ``args[0]`` is a plain-English reason the operator can
    paste straight into a refusal log.
    """


# ---------------------------------------------------------------------------
# Capability record + registry
# ---------------------------------------------------------------------------


_VALID_ORDER_TYPES: FrozenSet[str] = frozenset({
    "market",
    "limit",
    "stop",
    "stop_limit",
    "post_only",
    "ioc",
    "fok",
})

_VALID_TIF: FrozenSet[str] = frozenset({
    "GTC", "IOC", "FOK", "DAY", "GTD",
})


@dataclass(frozen=True)
class ExchangeCapability:
    """Frozen capability record for one exchange.

    Attributes:
        name: exchange registry key (e.g. ``binance_perpetual``).
        spot_supported: ``True`` iff the exchange handles spot.
        futures_supported: ``True`` iff it handles dated futures.
        perpetual_supported: ``True`` iff it handles perpetual swaps.
        margin_supported: ``True`` iff margin / leverage is available.
        supported_order_types: subset of :data:`_VALID_ORDER_TYPES`.
        supported_time_in_force: subset of :data:`_VALID_TIF`.
        min_size_per_kind: ``{kind_value: min_qty}`` minima keyed by
            :class:`CryptoInstrumentKind` value (e.g. ``"spot"``).
        tick_size_per_kind: optional ``{kind_value: tick_size}``.
        rate_limit_calls_per_minute: hard ceiling on API calls.
        sandbox_supported: ``True`` iff the exchange exposes a usable
            sandbox / testnet for the same kind matrix.
    """

    name: str
    spot_supported: bool = False
    futures_supported: bool = False
    perpetual_supported: bool = False
    margin_supported: bool = False
    supported_order_types: FrozenSet[str] = field(default_factory=frozenset)
    supported_time_in_force: FrozenSet[str] = field(default_factory=frozenset)
    min_size_per_kind: Mapping[str, float] = field(default_factory=dict)
    tick_size_per_kind: Mapping[str, float] = field(default_factory=dict)
    rate_limit_calls_per_minute: int = 0
    sandbox_supported: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExchangeCapability.name must be non-empty")
        if not isinstance(self.supported_order_types, frozenset):
            object.__setattr__(
                self,
                "supported_order_types",
                frozenset(self.supported_order_types),
            )
        if not isinstance(self.supported_time_in_force, frozenset):
            object.__setattr__(
                self,
                "supported_time_in_force",
                frozenset(self.supported_time_in_force),
            )
        bad_ot = self.supported_order_types - _VALID_ORDER_TYPES
        if bad_ot:
            raise ValueError(
                f"unknown order types {sorted(bad_ot)} for "
                f"exchange={self.name!r}; allowed={sorted(_VALID_ORDER_TYPES)}"
            )
        bad_tif = self.supported_time_in_force - _VALID_TIF
        if bad_tif:
            raise ValueError(
                f"unknown time-in-force {sorted(bad_tif)} for "
                f"exchange={self.name!r}; allowed={sorted(_VALID_TIF)}"
            )
        # Freeze the dict-like fields so the dataclass really is immutable.
        object.__setattr__(
            self, "min_size_per_kind", dict(self.min_size_per_kind)
        )
        object.__setattr__(
            self, "tick_size_per_kind", dict(self.tick_size_per_kind)
        )
        if self.rate_limit_calls_per_minute < 0:
            raise ValueError(
                "rate_limit_calls_per_minute must be >= 0, "
                f"got {self.rate_limit_calls_per_minute!r}"
            )

    def supports_kind(self, kind: CryptoInstrumentKind) -> bool:
        if kind == CryptoInstrumentKind.SPOT:
            return self.spot_supported
        if kind == CryptoInstrumentKind.DATED_FUTURE:
            return self.futures_supported
        if kind == CryptoInstrumentKind.PERPETUAL:
            return self.perpetual_supported
        return False  # pragma: no cover  -- enum is exhaustive

    def supports_order_type(self, order_type: str) -> bool:
        return order_type in self.supported_order_types


class ExchangeCapabilityRegistry:
    """Read-only registry of :class:`ExchangeCapability` records.

    The registry is seeded by :func:`default_registry` with the exchanges
    most relevant to Aurora today. Operators may register additional
    capabilities at runtime; collisions raise unless ``replace=True``.
    """

    def __init__(self) -> None:
        self._records: Dict[str, ExchangeCapability] = {}

    def register(
        self,
        cap: ExchangeCapability,
        *,
        replace: bool = False,
    ) -> None:
        if not replace and cap.name in self._records:
            raise ValueError(
                f"exchange {cap.name!r} already registered; "
                "pass replace=True to overwrite"
            )
        self._records[cap.name] = cap

    def get(self, name: str) -> Optional[ExchangeCapability]:
        return self._records.get(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._records

    def __len__(self) -> int:
        return len(self._records)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))

    def all(self) -> tuple[ExchangeCapability, ...]:
        return tuple(self._records[k] for k in sorted(self._records))


# ---------------------------------------------------------------------------
# Hand-curated seed data
# ---------------------------------------------------------------------------


_BINANCE_SPOT = ExchangeCapability(
    name="binance_spot",
    spot_supported=True,
    futures_supported=False,
    perpetual_supported=False,
    margin_supported=True,
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only", "ioc", "fok",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "FOK"}),
    min_size_per_kind={"spot": 0.0001},
    tick_size_per_kind={"spot": 0.01},
    rate_limit_calls_per_minute=1200,
    sandbox_supported=True,
)


_BINANCE_FUTURES = ExchangeCapability(
    name="binance_futures",
    spot_supported=False,
    futures_supported=True,
    perpetual_supported=False,
    margin_supported=True,
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only", "ioc", "fok",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "FOK", "GTD"}),
    min_size_per_kind={"dated_future": 0.001},
    tick_size_per_kind={"dated_future": 0.1},
    rate_limit_calls_per_minute=2400,
    sandbox_supported=True,
)


_BINANCE_PERPETUAL = ExchangeCapability(
    name="binance_perpetual",
    spot_supported=False,
    futures_supported=False,
    perpetual_supported=True,
    margin_supported=True,
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only", "ioc", "fok",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "FOK", "GTD"}),
    min_size_per_kind={"perpetual": 0.001},
    tick_size_per_kind={"perpetual": 0.1},
    rate_limit_calls_per_minute=2400,
    sandbox_supported=True,
)


_KRAKEN_SPOT = ExchangeCapability(
    name="kraken_spot",
    spot_supported=True,
    futures_supported=False,
    perpetual_supported=False,
    margin_supported=True,
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only", "ioc",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "GTD"}),
    min_size_per_kind={"spot": 0.0001},
    tick_size_per_kind={"spot": 0.01},
    rate_limit_calls_per_minute=900,
    sandbox_supported=True,
)


_COINBASE_SPOT = ExchangeCapability(
    name="coinbase_spot",
    spot_supported=True,
    futures_supported=False,
    perpetual_supported=False,
    margin_supported=False,  # retail spot only
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "FOK", "GTD"}),
    min_size_per_kind={"spot": 0.0001},
    tick_size_per_kind={"spot": 0.01},
    rate_limit_calls_per_minute=600,
    sandbox_supported=True,
)


_BYBIT_PERPETUAL = ExchangeCapability(
    name="bybit_perpetual",
    spot_supported=False,
    futures_supported=False,
    perpetual_supported=True,
    margin_supported=True,
    supported_order_types=frozenset({
        "market", "limit", "stop", "stop_limit", "post_only", "ioc", "fok",
    }),
    supported_time_in_force=frozenset({"GTC", "IOC", "FOK"}),
    min_size_per_kind={"perpetual": 0.001},
    tick_size_per_kind={"perpetual": 0.5},
    rate_limit_calls_per_minute=600,
    sandbox_supported=True,
)


def default_registry() -> ExchangeCapabilityRegistry:
    """Return a fresh registry seeded with the canonical exchanges."""
    reg = ExchangeCapabilityRegistry()
    for cap in (
        _BINANCE_SPOT,
        _BINANCE_FUTURES,
        _BINANCE_PERPETUAL,
        _KRAKEN_SPOT,
        _COINBASE_SPOT,
        _BYBIT_PERPETUAL,
    ):
        reg.register(cap)
    return reg


# ---------------------------------------------------------------------------
# Refusal gate
# ---------------------------------------------------------------------------


def assert_exchange_supports(
    exchange: str,
    kind: "str | CryptoInstrumentKind",
    order_type: str,
    *,
    registry: Optional[ExchangeCapabilityRegistry] = None,
) -> None:
    """Raise :class:`UnsupportedCapability` if the matrix forbids the combo.

    This is the canonical gate every order-submission path must call
    before contacting an exchange.
    """
    reg = registry or default_registry()
    cap = reg.get(exchange)
    if cap is None:
        raise UnsupportedCapability(
            f"exchange {exchange!r} is not in the capability registry; "
            f"refusing the order. Known exchanges: {list(reg.names())}"
        )

    parsed_kind = CryptoInstrumentKind.parse(kind)
    if not cap.supports_kind(parsed_kind):
        raise UnsupportedCapability(
            f"exchange {exchange!r} does not support instrument kind "
            f"{parsed_kind.value!r}; refusing the order. Capability: "
            f"spot={cap.spot_supported}, "
            f"dated_future={cap.futures_supported}, "
            f"perpetual={cap.perpetual_supported}."
        )

    if order_type not in _VALID_ORDER_TYPES:
        raise UnsupportedCapability(
            f"order_type {order_type!r} is not a known order type; "
            f"valid order types are {sorted(_VALID_ORDER_TYPES)}."
        )

    if not cap.supports_order_type(order_type):
        raise UnsupportedCapability(
            f"exchange {exchange!r} does not support order_type "
            f"{order_type!r} for kind {parsed_kind.value!r}; "
            f"supported order types are "
            f"{sorted(cap.supported_order_types)}."
        )


__all__ = [
    "ExchangeCapability",
    "ExchangeCapabilityRegistry",
    "UnsupportedCapability",
    "assert_exchange_supports",
    "default_registry",
]
