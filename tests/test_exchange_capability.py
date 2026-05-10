"""Tests for aurora.markets.exchange_capability (R185)."""
from __future__ import annotations

import pytest

from aurora.markets.crypto_derivatives import CryptoInstrumentKind
from aurora.markets.exchange_capability import (
    ExchangeCapability,
    ExchangeCapabilityRegistry,
    UnsupportedCapability,
    assert_exchange_supports,
    default_registry,
)


# ---------------------------------------------------------------------------
# Seed registry coverage
# ---------------------------------------------------------------------------


def test_default_registry_contains_required_exchanges() -> None:
    """All six required exchanges are seeded by default_registry()."""
    reg = default_registry()
    expected = {
        "binance_spot",
        "binance_futures",
        "binance_perpetual",
        "kraken_spot",
        "coinbase_spot",
        "bybit_perpetual",
    }
    assert expected.issubset(set(reg.names()))


def test_binance_perpetual_supports_stop_limit() -> None:
    """binance_perpetual exposes stop-limit orders."""
    reg = default_registry()
    cap = reg.get("binance_perpetual")
    assert cap is not None
    assert cap.perpetual_supported
    assert cap.supports_order_type("stop_limit")
    assert cap.supports_order_type("post_only")


def test_coinbase_spot_does_not_support_perpetuals() -> None:
    """coinbase_spot is spot-only by capability matrix."""
    reg = default_registry()
    cap = reg.get("coinbase_spot")
    assert cap is not None
    assert cap.spot_supported
    assert not cap.perpetual_supported
    assert not cap.futures_supported


def test_kraken_spot_disallows_post_only_in_unsupported_kind() -> None:
    """kraken_spot supports spot-side post_only but not perpetuals."""
    reg = default_registry()
    cap = reg.get("kraken_spot")
    assert cap is not None
    assert cap.spot_supported
    assert "post_only" in cap.supported_order_types
    assert not cap.perpetual_supported


# ---------------------------------------------------------------------------
# Refusal gate
# ---------------------------------------------------------------------------


def test_assert_supports_passes_supported_combo() -> None:
    """Supported (exchange, kind, order_type) combo does not raise."""
    assert_exchange_supports(
        "binance_perpetual", CryptoInstrumentKind.PERPETUAL, "limit"
    )


def test_assert_supports_refuses_unsupported_kind() -> None:
    """coinbase_spot does not handle perpetuals -> raises with reason."""
    with pytest.raises(UnsupportedCapability, match="perpetual"):
        assert_exchange_supports(
            "coinbase_spot", CryptoInstrumentKind.PERPETUAL, "limit"
        )


def test_assert_supports_refuses_unknown_exchange() -> None:
    """An exchange not in the registry is refused with a helpful message."""
    with pytest.raises(UnsupportedCapability, match="not in the capability"):
        assert_exchange_supports(
            "nonexistent_exchange", CryptoInstrumentKind.SPOT, "market"
        )


def test_assert_supports_refuses_unknown_order_type() -> None:
    """An unknown order_type string is refused before the exchange check."""
    with pytest.raises(UnsupportedCapability, match="not a known order type"):
        assert_exchange_supports(
            "binance_spot", CryptoInstrumentKind.SPOT, "iceberg",
        )


def test_assert_supports_string_kind_accepted() -> None:
    """Refusal gate accepts the string form of the enum value."""
    # "future" is an alias for DATED_FUTURE.
    assert_exchange_supports("binance_futures", "future", "limit")


# ---------------------------------------------------------------------------
# Min size + tick size + register collisions
# ---------------------------------------------------------------------------


def test_min_size_per_kind_respected() -> None:
    """Each seeded exchange records its min_size_per_kind for its supported kind."""
    reg = default_registry()
    spot_cap = reg.get("binance_spot")
    perp_cap = reg.get("binance_perpetual")
    fut_cap = reg.get("binance_futures")
    assert spot_cap is not None and perp_cap is not None and fut_cap is not None
    assert spot_cap.min_size_per_kind["spot"] > 0
    assert perp_cap.min_size_per_kind["perpetual"] > 0
    assert fut_cap.min_size_per_kind["dated_future"] > 0


def test_register_collision_requires_replace() -> None:
    """Registering the same exchange twice without replace=True raises."""
    reg = ExchangeCapabilityRegistry()
    cap = ExchangeCapability(
        name="my_exchange",
        spot_supported=True,
        supported_order_types=frozenset({"market"}),
        supported_time_in_force=frozenset({"GTC"}),
    )
    reg.register(cap)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(cap)
    reg.register(cap, replace=True)  # should succeed


def test_invalid_order_type_in_capability_raises() -> None:
    """Constructing a capability with a bogus order type fails fast."""
    with pytest.raises(ValueError, match="unknown order types"):
        ExchangeCapability(
            name="bad_exchange",
            supported_order_types=frozenset({"market", "iceberg"}),
        )
