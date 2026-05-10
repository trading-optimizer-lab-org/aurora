"""Tests for the MarketData.app limited provider (R156 deferred scaffold).

Covers env-gated construction, token enforcement, descriptor metadata,
options-chain and stock-quote paths via injected HTTP, plus credit-cost
provenance recording.
"""
from __future__ import annotations

import importlib
import sys

import pytest


MODULE_PATH = "aurora.core.data_providers.marketdata_app_limited"


def _reload_with_gate(monkeypatch, *, enabled: bool):
    if enabled:
        monkeypatch.setenv("AU_ENABLE_MARKETDATA_APP", "1")
    else:
        monkeypatch.delenv("AU_ENABLE_MARKETDATA_APP", raising=False)
    monkeypatch.delenv("AU_MARKETDATA_APP_TOKEN", raising=False)
    sys.modules.pop(MODULE_PATH, None)
    return importlib.import_module(MODULE_PATH)


def _fake_chain_body():
    return {
        "options": [
            {
                "symbol": "AAPL_240119C00150000",
                "expiration": "2024-01-19",
                "strike": 150.0,
                "option_type": "call",
                "bid": 5.10,
                "ask": 5.20,
                "last": 5.15,
                "volume": 1234,
                "open_interest": 5678,
                "implied_volatility": 0.275,
                "delayed_minutes": 15,
            },
            {
                "symbol": "AAPL_240119P00150000",
                "expiration": "2024-01-19",
                "strike": 150.0,
                "option_type": "put",
                "bid": 4.40,
                "ask": 4.50,
                "last": 4.45,
                "volume": 987,
                "open_interest": 1234,
                "implied_volatility": 0.260,
                "delayed_minutes": 15,
            },
        ]
    }


def _fake_quote_body():
    return {
        "symbol": "AAPL",
        "time_iso": "2024-01-02T20:00:00Z",
        "last": 185.50,
        "bid": 185.45,
        "ask": 185.55,
        "volume": 1_234_567,
        "delayed_minutes": 15,
    }


def test_module_construction_without_env_var_raises(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=False)
    with pytest.raises(RuntimeError, match="AU_ENABLE_MARKETDATA_APP"):
        mod.MarketDataAppClient(
            http_get=lambda url, params: {}, api_token="t",
        )


def test_with_env_var_set_constructs_successfully(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    client = mod.MarketDataAppClient(
        http_get=lambda url, params: {}, api_token="abc",
    )
    assert client is not None


def test_construction_without_token_raises(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    with pytest.raises(RuntimeError, match="AU_MARKETDATA_APP_TOKEN"):
        mod.MarketDataAppClient(http_get=lambda url, params: {})


def test_construction_with_env_token_works(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    monkeypatch.setenv("AU_MARKETDATA_APP_TOKEN", "from_env")
    client = mod.MarketDataAppClient(http_get=lambda url, params: {})
    assert client is not None


def test_fetch_options_chain_returns_entries_with_iv(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)

    captured: dict = {}

    def fake_http_get(url, params):
        captured["url"] = url
        captured["params"] = dict(params)
        return _fake_chain_body()

    client = mod.MarketDataAppClient(
        http_get=fake_http_get, api_token="tok-123",
    )
    entries, prov = client.fetch_options_chain("AAPL", expiration="2024-01-19")

    assert len(entries) == 2
    call, put = entries
    assert call.option_type == "call"
    assert put.option_type == "put"
    assert call.implied_volatility == pytest.approx(0.275)
    assert put.implied_volatility == pytest.approx(0.260)
    assert call.strike == pytest.approx(150.0)
    assert call.delayed_minutes == 15

    # URL/params bound but token is stripped from query_params provenance.
    assert captured["url"].startswith(
        "https://api.marketdata.app/v1/options/chain/AAPL/"
    )
    assert "token" not in prov.query_params
    assert prov.query_params["expiration"] == "2024-01-19"


def test_fetch_stock_quote_carries_delayed_flag(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)

    def fake_http_get(url, params):
        return _fake_quote_body()

    client = mod.MarketDataAppClient(
        http_get=fake_http_get, api_token="tok",
    )
    quote, prov = client.fetch_stock_quote("AAPL")
    assert quote.symbol == "AAPL"
    assert quote.last == pytest.approx(185.50)
    assert quote.delayed_minutes == 15
    assert prov.extra["is_delayed"] is True
    assert prov.extra["asset_class"] == "equity"


def test_descriptor_options_limited_role(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    desc = mod.descriptor()
    from aurora.core.data_providers import ProviderRole

    assert desc.role is ProviderRole.OPTIONS_LIMITED
    assert desc.name == "marketdata_app_limited"
    assert desc.auth_required is True
    assert "options" in desc.asset_classes
    assert "100 daily credits" in desc.rate_limits
    assert desc.licence_terms_url.startswith("https://www.marketdata.app")


def test_credit_consumption_recorded_in_provenance(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    client = mod.MarketDataAppClient(
        http_get=lambda url, params: _fake_chain_body(),
        api_token="tok",
    )
    _, chain_prov = client.fetch_options_chain("AAPL")
    assert chain_prov.extra["credit_cost"] == client.OPTIONS_CHAIN_CREDIT_COST
    assert chain_prov.extra["endpoint"] == "options_chain"
    assert chain_prov.extra["is_delayed"] is True
    assert chain_prov.extra["deferred_scaffold"] is True

    client2 = mod.MarketDataAppClient(
        http_get=lambda url, params: _fake_quote_body(),
        api_token="tok",
    )
    _, quote_prov = client2.fetch_stock_quote("AAPL")
    assert quote_prov.extra["credit_cost"] == client2.STOCK_QUOTE_CREDIT_COST
    assert quote_prov.extra["endpoint"] == "stocks_quote"


def test_invalid_option_type_in_payload_raises(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    bad_body = {
        "options": [
            {
                "symbol": "X", "expiration": "2024-01-19", "strike": 1.0,
                "option_type": "swap",  # invalid
                "bid": 1.0, "ask": 1.1, "last": 1.05,
                "volume": 0, "open_interest": 0,
                "implied_volatility": 0.1, "delayed_minutes": 15,
            },
        ]
    }
    client = mod.MarketDataAppClient(
        http_get=lambda url, params: bad_body, api_token="tok",
    )
    with pytest.raises(ValueError, match="option_type="):
        client.fetch_options_chain("X")
