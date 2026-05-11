"""Tests for the R156 ecb_data_portal provider.

All tests use injected ``http_get`` callables; no network is touched.
Fixtures mirror the public ECB SDMX-JSON shape.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

import pytest

from aurora.core.data_providers import ProviderRole, ProviderUnavailable
from aurora.core.data_providers.ecb_data_portal import (
    ACCEPT_HEADER,
    API_BASE,
    ECB_DESCRIPTOR,
    ECBClient,
    ECBSeries,
    ECBSeriesKey,
    descriptor,
)


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


def _build_sdmx_json_response(
    *,
    periods: list[str],
    values: list[float],
    statuses: Optional[list[str]] = None,
) -> str:
    """Build a minimal SDMX-JSON response for the EXR dataflow."""
    if statuses is None:
        statuses = ["A"] * len(periods)
    # Map every distinct status to an index.
    distinct_statuses = list(dict.fromkeys(statuses))
    status_idx = {s: i for i, s in enumerate(distinct_statuses)}
    obs_payload: dict[str, list[Any]] = {}
    for i, value in enumerate(values):
        obs_payload[str(i)] = [value, status_idx[statuses[i]]]
    payload = {
        "header": {"id": "ecb-fixture"},
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {"observations": obs_payload}
                }
            }
        ],
        "structure": {
            "name": "EUR FX reference rates",
            "dimensions": {
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "name": "Time period",
                        "values": [{"id": p} for p in periods],
                    }
                ],
            },
            "attributes": {
                "series": [
                    {
                        "id": "UNIT",
                        "values": [{"id": "EUR", "name": "Euro"}],
                    }
                ],
                "observation": [
                    {
                        "id": "OBS_STATUS",
                        "values": [{"id": s} for s in distinct_statuses],
                    }
                ],
            },
        },
    }
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability():
    d = descriptor()
    assert d is ECB_DESCRIPTOR
    assert d.role is ProviderRole.FX_REFERENCE
    assert d.reliability == "OFFICIAL"
    assert d.auth_required is False
    assert d.adjustment_posture == "RAW"
    assert "fx" in d.asset_classes
    assert "macro" in d.asset_classes
    assert "daily" in d.intervals


def test_fetch_eur_fx_reference_rate_parses_fixture():
    seen: dict[str, Any] = {}

    def http_get(
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        seen["url"] = url
        seen["params"] = dict(params or {})
        seen["headers"] = dict(headers or {})
        return _build_sdmx_json_response(
            periods=["2024-01-02", "2024-01-03", "2024-01-04"],
            values=[1.0956, 1.0921, 1.0945],
        )

    client = ECBClient(http_get=http_get)
    series = client.fetch_eur_fx_reference_rate("USD")

    assert seen["url"] == f"{API_BASE}/EXR/D.USD.EUR.SP00.A"
    assert seen["headers"]["Accept"] == ACCEPT_HEADER
    assert isinstance(series, ECBSeries)
    assert series.key.dataflow == "EXR"
    assert series.key.key == "D.USD.EUR.SP00.A"
    assert len(series.observations) == 3
    assert series.observations[0].period_iso == "2024-01-02"
    assert series.observations[0].value == pytest.approx(1.0956)
    assert series.observations[0].obs_status == "A"
    assert series.unit == "EUR"


def test_fetch_series_with_date_range_filters():
    seen: dict[str, Any] = {}

    def http_get(
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        seen["params"] = dict(params or {})
        return _build_sdmx_json_response(
            periods=["2024-02-01", "2024-02-02"],
            values=[1.10, 1.11],
        )

    key = ECBSeriesKey(dataflow="EXR", key="D.GBP.EUR.SP00.A")
    client = ECBClient(http_get=http_get)
    series = client.fetch_series(key, start="2024-02-01", end="2024-02-02")

    assert seen["params"]["startPeriod"] == "2024-02-01"
    assert seen["params"]["endPeriod"] == "2024-02-02"
    assert len(series.observations) == 2
    # Provenance must echo the date filter so an auditor can replay.
    qp = series.provenance.query_params
    assert qp["startPeriod"] == "2024-02-01"
    assert qp["endPeriod"] == "2024-02-02"
    assert qp["dataflow"] == "EXR"
    assert qp["key"] == "D.GBP.EUR.SP00.A"


def test_fx_reference_rate_marked_macro_not_tradeable():
    """ECB FX reference rate is macro context, not a tradeable instrument."""

    def http_get(
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        return _build_sdmx_json_response(
            periods=["2024-01-02"], values=[1.0956]
        )

    client = ECBClient(http_get=http_get)
    series = client.fetch_eur_fx_reference_rate("USD")

    extra = series.provenance.extra
    assert extra["asset_class"] == "MACRO"
    assert extra["asset_class"] != "EQUITY"
    assert extra["tradeable"] is False
    assert extra["library"] == "macro_multisource"


def test_provenance_carries_dataflow_and_key():
    def http_get(
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        return _build_sdmx_json_response(
            periods=["2024-01-02"], values=[1.0956]
        )

    key = ECBSeriesKey(dataflow="EXR", key="D.USD.EUR.SP00.A")
    client = ECBClient(http_get=http_get)
    series = client.fetch_series(key)

    extra = series.provenance.extra
    assert extra["dataflow"] == "EXR"
    assert extra["series_key"] == "D.USD.EUR.SP00.A"
    assert extra["sdmx_format"] == "json"
    assert series.provenance.provider_name == "ecb_data_portal"


def test_currency_pair_normalisation_accepts_common_forms():
    captured_urls: list[str] = []

    def http_get(
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        captured_urls.append(url)
        return _build_sdmx_json_response(
            periods=["2024-01-02"], values=[1.0]
        )

    client = ECBClient(http_get=http_get)
    for pair in ("USD", "USD/EUR", "EUR/USD", "USDEUR", "EURUSD"):
        client.fetch_eur_fx_reference_rate(pair)
    expected = f"{API_BASE}/EXR/D.USD.EUR.SP00.A"
    assert all(u == expected for u in captured_urls), captured_urls


def test_default_client_refuses_to_call_out():
    client = ECBClient()  # no http_get injected
    with pytest.raises(ProviderUnavailable, match="no http_get"):
        client.fetch_eur_fx_reference_rate("USD")


def test_invalid_series_key_raises():
    with pytest.raises(ValueError):
        ECBSeriesKey(dataflow="", key="D.USD.EUR.SP00.A")
    with pytest.raises(ValueError):
        ECBSeriesKey(dataflow="EXR", key="")


def test_fetch_series_rejects_non_dataclass_key():
    client = ECBClient(
        http_get=lambda u, p=None, h=None: _build_sdmx_json_response(
            periods=["2024-01-02"], values=[1.0]
        )
    )
    with pytest.raises(TypeError, match="ECBSeriesKey"):
        client.fetch_series("EXR/D.USD.EUR.SP00.A")


def test_invalid_json_response_raises():
    client = ECBClient(http_get=lambda u, p=None, h=None: "<xml>not-json</xml>")
    with pytest.raises(ProviderUnavailable, match="not JSON"):
        client.fetch_eur_fx_reference_rate("USD")
