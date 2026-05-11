"""Tests for the R156 dbnomics_macro provider.

All tests use injected ``http_get`` callables so the network is never
touched. Fixtures mirror the public DBnomics REST shape (v22).
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

import pytest

from aurora.core.data_providers import ProviderRole, ProviderUnavailable
from aurora.core.data_providers.dbnomics_macro import (
    API_BASE,
    DBNOMICS_DESCRIPTOR,
    DBnomicsClient,
    DBnomicsSeries,
    DBnomicsSeriesId,
    descriptor,
)


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


def _build_series_response() -> str:
    """Mimic ``GET /v22/series/ECB/EXR/D.USD.EUR.SP00.A?observations=1``."""
    payload = {
        "dataset": {
            "code": "EXR",
            "name": "Exchange rates",
            "attribution": "ECB Statistical Data Warehouse, CC BY 4.0",
            "licence": "CC BY 4.0",
        },
        "series": {
            "docs": [
                {
                    "provider_code": "ECB",
                    "dataset_code": "EXR",
                    "series_code": "D.USD.EUR.SP00.A",
                    "name": "USD vs EUR daily reference rate",
                    "@frequency": "daily",
                    "unit": "EUR",
                    "period": [
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-04",
                        "2024-01-05",
                    ],
                    "value": [1.0956, 1.0921, 1.0945, 1.0951],
                    "observations_attributes": [
                        ["OBS_STATUS", "A"],
                        ["OBS_STATUS", "A"],
                        ["OBS_STATUS", "A"],
                        ["OBS_STATUS", "A"],
                    ],
                }
            ]
        },
    }
    return json.dumps(payload)


def _build_search_response() -> str:
    payload = {
        "results": {
            "docs": [
                {
                    "provider_code": "ECB",
                    "dataset_code": "EXR",
                    "series_code": "D.USD.EUR.SP00.A",
                    "name": "USD vs EUR daily reference rate",
                },
                {
                    "provider_code": "OECD",
                    "dataset_code": "MEI_PRICES",
                    "series_code": "CPALTT01.OECD.M",
                    "name": "OECD CPI all items",
                },
            ]
        }
    }
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability():
    d = descriptor()
    assert d is DBNOMICS_DESCRIPTOR
    assert d.role is ProviderRole.MACRO_MULTI_SOURCE
    assert d.reliability == "OFFICIAL"
    assert d.auth_required is False
    assert d.adjustment_posture == "RAW"
    assert "macro" in d.asset_classes
    assert "daily" in d.intervals


def test_search_parses_fixture_response():
    seen: dict[str, Any] = {}

    def http_get(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
        seen["url"] = url
        seen["params"] = dict(params or {})
        return _build_search_response()

    client = DBnomicsClient(http_get=http_get)
    rows = client.search("inflation", max_results=10)

    assert seen["url"] == f"{API_BASE}/search"
    assert seen["params"]["q"] == "inflation"
    assert seen["params"]["limit"] == 10
    assert len(rows) == 2
    assert rows[0] == (
        "ECB",
        "EXR",
        "D.USD.EUR.SP00.A",
        "USD vs EUR daily reference rate",
    )
    assert rows[1][0] == "OECD"


def test_fetch_series_returns_observations_with_period():
    seen: dict[str, Any] = {}

    def http_get(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
        seen["url"] = url
        seen["params"] = dict(params or {})
        return _build_series_response()

    sid = DBnomicsSeriesId(
        provider_code="ECB",
        dataset_code="EXR",
        series_code="D.USD.EUR.SP00.A",
    )
    client = DBnomicsClient(http_get=http_get)
    series = client.fetch_series(sid)

    assert seen["url"] == f"{API_BASE}/series/ECB/EXR/D.USD.EUR.SP00.A"
    assert seen["params"]["observations"] == "1"
    assert isinstance(series, DBnomicsSeries)
    assert len(series.observations) == 4
    assert series.observations[0].period_iso == "2024-01-02"
    assert series.observations[0].value == pytest.approx(1.0956)
    assert series.observations[0].attributes == {"OBS_STATUS": "A"}
    assert series.frequency == "daily"


def test_provenance_preserves_upstream_provider_and_licence():
    def http_get(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
        return _build_series_response()

    sid = DBnomicsSeriesId(
        provider_code="ECB",
        dataset_code="EXR",
        series_code="D.USD.EUR.SP00.A",
    )
    client = DBnomicsClient(http_get=http_get)
    series = client.fetch_series(sid)

    extra = series.provenance.extra
    assert extra["upstream_provider"] == "ECB"
    assert extra["upstream_dataset"] == "EXR"
    assert extra["upstream_series"] == "D.USD.EUR.SP00.A"
    # Upstream licence string must be preserved verbatim from the dataset
    # block, not replaced by a generic fallback.
    assert "CC BY 4.0" in series.provenance.extra["upstream_licence"]
    assert series.upstream_licence == extra["upstream_licence"]
    assert series.provenance.provider_name == "dbnomics_macro"


def test_macro_asset_class_label():
    """Series gets ``asset_class="MACRO"``, never ``EQUITY``."""

    def http_get(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
        return _build_series_response()

    sid = DBnomicsSeriesId(
        provider_code="ECB",
        dataset_code="EXR",
        series_code="D.USD.EUR.SP00.A",
    )
    client = DBnomicsClient(http_get=http_get)
    series = client.fetch_series(sid)

    assert series.provenance.extra["asset_class"] == "MACRO"
    assert series.provenance.extra["asset_class"] != "EQUITY"
    assert series.provenance.extra["library"] == "macro_multisource"


def test_missing_http_client_raises(monkeypatch):
    """Default client must refuse to call out unless AU_DBNOMICS_HTTP=1."""
    monkeypatch.delenv("AU_DBNOMICS_HTTP", raising=False)
    client = DBnomicsClient()  # no http_get injected
    sid = DBnomicsSeriesId(
        provider_code="ECB",
        dataset_code="EXR",
        series_code="D.USD.EUR.SP00.A",
    )
    with pytest.raises(ProviderUnavailable, match="AU_DBNOMICS_HTTP"):
        client.fetch_series(sid)


def test_invalid_series_id_format_raises():
    """Series id triple must be non-empty + alnum / [_-./] only."""
    with pytest.raises(ValueError):
        DBnomicsSeriesId(provider_code="", dataset_code="EXR", series_code="X")
    with pytest.raises(ValueError):
        DBnomicsSeriesId(
            provider_code="ECB",
            dataset_code="EXR",
            series_code="bad code with spaces",
        )
    with pytest.raises(ValueError):
        DBnomicsSeriesId(
            provider_code="ECB",
            dataset_code="EXR;DROP TABLE",
            series_code="X",
        )


def test_fetch_series_rejects_non_dataclass_id():
    """``fetch_series`` rejects raw tuples / strings."""
    client = DBnomicsClient(http_get=lambda u, p=None: _build_series_response())
    with pytest.raises(TypeError, match="DBnomicsSeriesId"):
        client.fetch_series(("ECB", "EXR", "D.USD.EUR.SP00.A"))


def test_search_rejects_blank_query():
    client = DBnomicsClient(http_get=lambda u, p=None: _build_search_response())
    with pytest.raises(ValueError):
        client.search("   ")
    with pytest.raises(ValueError):
        client.search("inflation", max_results=0)


def test_invalid_json_response_raises():
    client = DBnomicsClient(http_get=lambda u, p=None: "not-json")
    sid = DBnomicsSeriesId(
        provider_code="ECB",
        dataset_code="EXR",
        series_code="D.USD.EUR.SP00.A",
    )
    with pytest.raises(ProviderUnavailable, match="non-JSON"):
        client.fetch_series(sid)
