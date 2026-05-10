"""Tests for the Dukascopy FX history provider (R156 deferred scaffold).

Covers the env-gated construction, descriptor metadata, and the
fetch_bars path with an injected HTTP client.
"""
from __future__ import annotations

import importlib
import sys

import pytest


MODULE_PATH = "aurora.core.data_providers.dukascopy_fx_history"


def _reload_with_gate(monkeypatch, *, enabled: bool):
    """Force re-import the module with the gate env var set or unset."""
    if enabled:
        monkeypatch.setenv("AU_ENABLE_DUKASCOPY", "1")
    else:
        monkeypatch.delenv("AU_ENABLE_DUKASCOPY", raising=False)
    sys.modules.pop(MODULE_PATH, None)
    return importlib.import_module(MODULE_PATH)


def _fake_bar_rows():
    return (
        ("2024-01-02T00:00:00.000Z", 1.1010, 1.1050, 1.0995, 1.1030, 1234.5),
        ("2024-01-03T00:00:00.000Z", 1.1030, 1.1080, 1.1020, 1.1075, 2345.0),
        ("2024-01-04T00:00:00.000Z", 1.1075, 1.1100, 1.1050, 1.1090, 3456.7),
    )


def test_module_import_without_env_var_raises_at_construction(monkeypatch):
    """Module import is cheap; gate fires when DukascopyClient() is called."""
    mod = _reload_with_gate(monkeypatch, enabled=False)
    with pytest.raises(RuntimeError, match="AU_ENABLE_DUKASCOPY"):
        mod.DukascopyClient(http_get=lambda url, params: ())


def test_with_env_var_set_constructs_successfully(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    client = mod.DukascopyClient(http_get=lambda url, params: ())
    assert client is not None


def test_fetch_bars_returns_fx_series_with_provenance(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)

    captured: dict = {}

    def fake_http_get(url, params):
        captured["url"] = url
        captured["params"] = dict(params)
        return _fake_bar_rows()

    client = mod.DukascopyClient(http_get=fake_http_get)
    series = client.fetch_bars(
        "EURUSD", start="2024-01-02", end="2024-01-04", interval="D1"
    )
    assert series.instrument == "EURUSD"
    assert len(series.bars) == 3
    assert all(b.interval == "D1" for b in series.bars)
    # First bar values land in the typed dataclass.
    assert series.bars[0].open == pytest.approx(1.1010)
    assert series.bars[0].close == pytest.approx(1.1030)
    # Provenance carries the right provider name and query params.
    prov = series.provenance
    assert prov.provider_name == "dukascopy_fx_history"
    assert prov.row_count == 3
    assert prov.query_params["instrument"] == "EURUSD"
    assert prov.query_params["interval"] == "D1"
    assert prov.extra["asset_class"] == "fx"
    assert prov.extra["adjustment_posture"] == "RAW"
    assert prov.extra["deferred_scaffold"] is True
    # URL was built using the documented endpoint base.
    assert captured["url"].startswith(
        "https://datafeed.dukascopy.com/datafeed/EURUSD/bars/D1"
    )


def test_descriptor_role_fx_tick_research(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    desc = mod.descriptor()
    from aurora.core.data_providers import ProviderRole

    assert desc.role is ProviderRole.FX_TICK_RESEARCH
    assert desc.name == "dukascopy_fx_history"
    assert desc.auth_required is False
    assert "fx" in desc.asset_classes
    assert desc.adjustment_posture == "RAW"
    assert desc.reliability == "COMMUNITY"
    assert desc.licence_terms_url.startswith("https://www.dukascopy.com")


def test_intraday_intervals_supported(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)

    def fake_http_get(url, params):
        return (("2024-01-02T09:00:00.000Z", 1.1, 1.2, 1.05, 1.15, 100.0),)

    client = mod.DukascopyClient(http_get=fake_http_get)
    for interval in ("M1", "M5", "H1", "D1"):
        series = client.fetch_bars(
            "EURUSD", start="2024-01-02", end="2024-01-02", interval=interval
        )
        assert series.bars[0].interval == interval

    # Bad interval is rejected before HTTP is invoked.
    with pytest.raises(ValueError, match="interval="):
        client.fetch_bars(
            "EURUSD", start="2024-01-02", end="2024-01-02",
            interval="W1",
        )


def test_empty_bars_series_yields_empty_date_range(monkeypatch):
    mod = _reload_with_gate(monkeypatch, enabled=True)
    client = mod.DukascopyClient(http_get=lambda url, params: ())
    series = client.fetch_bars(
        "GBPUSD", start="2024-01-02", end="2024-01-02", interval="H1"
    )
    assert series.bars == ()
    assert series.provenance.row_count == 0
    assert series.provenance.date_range == ("", "")
