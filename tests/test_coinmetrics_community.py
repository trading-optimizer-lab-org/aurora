"""Tests for the R156 coinmetrics_community provider.

All tests use injected ``http_get`` callables backed by in-memory
fixtures; no test touches the network. Coverage spans descriptor
metadata, the asset catalog, asset metric series, market trade
records, and the community-licence warning surfaced on every
provenance envelope (with operator-override behaviour).
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

import pytest

from aurora.core.data_providers import ProviderRole
from aurora.core.data_providers.coinmetrics_community import (
    COINMETRICS_DESCRIPTOR,
    LICENCE_WARNING,
    OPERATOR_OVERRIDE_ENV,
    CMAsset,
    CMMarketData,
    CMMetricObservation,
    CoinMetricsClient,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _assets_payload() -> Mapping[str, Any]:
    return {
        "data": [
            {
                "asset": "btc",
                "full_name": "Bitcoin",
                "symbol": "BTC",
                "category": "Native",
                "is_active": True,
            },
            {
                "asset": "eth",
                "full_name": "Ether",
                "symbol": "ETH",
                "category": "Native",
                "is_active": True,
            },
        ]
    }


def _metric_payload() -> Mapping[str, Any]:
    return {
        "data": [
            {
                "asset": "btc",
                "time": "2024-01-01T00:00:00.000000000Z",
                "AdrActCnt": "950000",
            },
            {
                "asset": "btc",
                "time": "2024-01-02T00:00:00.000000000Z",
                "AdrActCnt": "1010000.5",
            },
            {
                "asset": "btc",
                "time": "2024-01-03T00:00:00.000000000Z",
                "AdrActCnt": None,  # Missing samples must be filtered.
            },
        ]
    }


def _market_payload() -> Mapping[str, Any]:
    return {
        "data": [
            {
                "market": "binance-btc-usdt-spot",
                "time": "2024-01-01T00:00:00.000000000Z",
                "price": "42000.50",
                "amount": "1.25",
            },
            {
                "market": "binance-btc-usdt-spot",
                "time": "2024-01-01T00:01:00.000000000Z",
                "price": "42010.75",
                "amount": "0.75",
            },
        ]
    }


def _make_router(routes: Dict[str, Mapping[str, Any]]):
    """Build an http_get stub that routes by URL prefix."""
    def http_get(url: str) -> Mapping[str, Any]:
        for prefix, payload in routes.items():
            if prefix in url:
                return payload
        raise AssertionError(f"unexpected url: {url}")
    return http_get


# ---------------------------------------------------------------------------
# 1. Descriptor.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability() -> None:
    assert COINMETRICS_DESCRIPTOR.name == "coinmetrics_community"
    assert COINMETRICS_DESCRIPTOR.role is ProviderRole.CRYPTO_METRICS
    assert COINMETRICS_DESCRIPTOR.reliability == "COMMUNITY"
    assert COINMETRICS_DESCRIPTOR.auth_required is False
    assert "crypto" in COINMETRICS_DESCRIPTOR.asset_classes


# ---------------------------------------------------------------------------
# 2. Asset catalog.
# ---------------------------------------------------------------------------


def test_list_assets_parses_fixture() -> None:
    client = CoinMetricsClient(
        http_get=_make_router({"/catalog/assets": _assets_payload()}),
    )
    assets = client.list_assets()
    assert len(assets) == 2
    assert all(isinstance(a, CMAsset) for a in assets)
    assert assets[0].asset == "btc"
    assert assets[0].symbol == "BTC"
    assert assets[0].is_active is True


# ---------------------------------------------------------------------------
# 3. Metric timeseries.
# ---------------------------------------------------------------------------


def test_fetch_metric_returns_observations() -> None:
    client = CoinMetricsClient(
        http_get=_make_router({"/timeseries/asset-metrics": _metric_payload()}),
    )
    obs = client.fetch_metric("btc", "AdrActCnt")
    # The third sample with null value must be dropped.
    assert len(obs) == 2
    assert all(isinstance(o, CMMetricObservation) for o in obs)
    assert obs[0].asset == "btc"
    assert obs[0].metric_name == "AdrActCnt"
    assert obs[0].value == pytest.approx(950000.0)
    assert obs[1].value == pytest.approx(1010000.5)


# ---------------------------------------------------------------------------
# 4. Market data.
# ---------------------------------------------------------------------------


def test_fetch_market_data_returns_market_records() -> None:
    client = CoinMetricsClient(
        http_get=_make_router({
            "/timeseries/market-trades": _market_payload(),
        }),
    )
    rows = client.fetch_market_data("binance-btc-usdt-spot")
    assert len(rows) == 2
    assert all(isinstance(r, CMMarketData) for r in rows)
    assert rows[0].market == "binance-btc-usdt-spot"
    assert rows[0].price_usd == pytest.approx(42000.50)
    assert rows[0].volume_usd == pytest.approx(1.25)
    # Provenance must be wired on every record.
    assert rows[0].provenance is not None
    assert rows[0].provenance.provider_name == "coinmetrics_community"


# ---------------------------------------------------------------------------
# 5. Community licence warning.
# ---------------------------------------------------------------------------


def test_community_licence_warning_in_provenance(monkeypatch) -> None:
    # Ensure no stale operator override is leaking from another test.
    monkeypatch.delenv(OPERATOR_OVERRIDE_ENV, raising=False)

    routes = {
        "/catalog/assets": _assets_payload(),
        "/timeseries/asset-metrics": _metric_payload(),
        "/timeseries/market-trades": _market_payload(),
    }
    client = CoinMetricsClient(http_get=_make_router(routes))

    assets = client.list_assets()
    obs = client.fetch_metric("btc", "AdrActCnt")
    market = client.fetch_market_data("binance-btc-usdt-spot")

    # Every output's provenance must carry the licence warning.
    assert assets[0].provenance is not None
    assert LICENCE_WARNING in assets[0].provenance.warnings
    assert obs[0].provenance is not None
    assert LICENCE_WARNING in obs[0].provenance.warnings
    assert LICENCE_WARNING in market[0].provenance.warnings


# ---------------------------------------------------------------------------
# 6. Operator override drops the warning.
# ---------------------------------------------------------------------------


def test_operator_override_drops_warning(monkeypatch) -> None:
    monkeypatch.setenv(OPERATOR_OVERRIDE_ENV, "1")

    routes = {
        "/catalog/assets": _assets_payload(),
        "/timeseries/asset-metrics": _metric_payload(),
        "/timeseries/market-trades": _market_payload(),
    }
    client = CoinMetricsClient(http_get=_make_router(routes))

    assets = client.list_assets()
    obs = client.fetch_metric("btc", "AdrActCnt")
    market = client.fetch_market_data("binance-btc-usdt-spot")

    # When override is explicitly set, the warning must not appear.
    assert assets[0].provenance is not None
    assert LICENCE_WARNING not in assets[0].provenance.warnings
    assert obs[0].provenance is not None
    assert LICENCE_WARNING not in obs[0].provenance.warnings
    assert LICENCE_WARNING not in market[0].provenance.warnings


# ---------------------------------------------------------------------------
# 7. Missing http client is refused.
# ---------------------------------------------------------------------------


def test_missing_http_client_raises() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        CoinMetricsClient()
    msg = str(excinfo.value).lower()
    assert "http_get" in msg


# ---------------------------------------------------------------------------
# 8. Bad inputs.
# ---------------------------------------------------------------------------


def test_fetch_metric_rejects_empty_asset() -> None:
    client = CoinMetricsClient(http_get=lambda url: {"data": []})
    with pytest.raises(ValueError):
        client.fetch_metric("", "AdrActCnt")


def test_fetch_market_data_rejects_empty_market() -> None:
    client = CoinMetricsClient(http_get=lambda url: {"data": []})
    with pytest.raises(ValueError):
        client.fetch_market_data("")
