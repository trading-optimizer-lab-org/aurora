"""Tests for the R156 OpenFIGI identifier-mapping provider.

All tests use injected ``http_post`` callables. No test touches the
network. Covers descriptor metadata, single mapping, no-match, ambiguity
preservation, exchange filter, bulk map, missing client guard, security
master integration, and rate-limit metadata.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from aurora.core.data_providers import ProviderDescriptor, ProviderRole
from aurora.core.data_providers.openfigi_mapper import (
    OPENFIGI_DESCRIPTOR,
    PROVIDER_NAME,
    PROVIDER_URL,
    RATE_LIMIT_DESCRIPTION,
    FIGIMapping,
    FIGIQueryResult,
    OpenFIGIClient,
    descriptor as openfigi_descriptor,
)
from aurora.data_contracts.security_master import (
    SecurityMasterRecord,
    from_openfigi_mapping,
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _aapl_response_row(
    figi: str = "BBG000B9XRY4",
    ticker: str = "AAPL",
    exch: str = "UW",
    market_sector: str = "Equity",
    security_type: str = "Common Stock",
    composite: str = "BBG000B9Y5X2",
    share_class: str = "BBG001S5N8V8",
    currency: str = "USD",
    name: str = "APPLE INC",
    unique_id: str | None = None,
    unique_id_type: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "figi": figi,
        "name": name,
        "ticker": ticker,
        "exchCode": exch,
        "marketSector": market_sector,
        "securityType": security_type,
        "compositeFIGI": composite,
        "shareClassFIGI": share_class,
        "currency": currency,
    }
    if unique_id is not None:
        row["uniqueID"] = unique_id
    if unique_id_type is not None:
        row["uniqueIdType"] = unique_id_type
    return row


def _expect_one(rows: list[dict[str, Any]]) -> Sequence[Mapping[str, Any]]:
    """Helper for stub responses returning a single 'data' result."""
    return [{"data": rows}]


# ---------------------------------------------------------------------------
# 1. Descriptor.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability():
    assert isinstance(OPENFIGI_DESCRIPTOR, ProviderDescriptor)
    assert OPENFIGI_DESCRIPTOR.role is ProviderRole.IDENTITY_MAPPING
    assert OPENFIGI_DESCRIPTOR.reliability == "OFFICIAL"
    assert OPENFIGI_DESCRIPTOR.auth_required is False
    assert OPENFIGI_DESCRIPTOR.intervals == ()
    # Function alias matches singleton.
    assert openfigi_descriptor() is OPENFIGI_DESCRIPTOR
    assert PROVIDER_NAME == "openfigi_mapper"
    assert PROVIDER_URL == "https://api.openfigi.com/v3/mapping"


def test_rate_limit_metadata_in_descriptor():
    # The descriptor records the published free-tier limits so an
    # operator inspecting `aurora data provider-status` can see the
    # ceiling without having to dig into the source.
    assert "25 req/min" in OPENFIGI_DESCRIPTOR.rate_limits
    assert "250 req/min" in OPENFIGI_DESCRIPTOR.rate_limits
    assert "free tier" in OPENFIGI_DESCRIPTOR.rate_limits.lower()
    assert RATE_LIMIT_DESCRIPTION == OPENFIGI_DESCRIPTOR.rate_limits


# ---------------------------------------------------------------------------
# 2. map_symbol -- single mapping with provenance.
# ---------------------------------------------------------------------------


def test_map_symbol_returns_result_with_provenance():
    captured: dict[str, Any] = {}

    def http_post(url, payload, headers):
        captured["url"] = url
        captured["payload"] = list(payload)
        captured["headers"] = dict(headers)
        return _expect_one([_aapl_response_row()])

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("AAPL", exchange="US")

    assert isinstance(result, FIGIQueryResult)
    assert len(result.mappings) == 1
    primary = result.mappings[0]
    assert primary.figi == "BBG000B9XRY4"
    assert primary.ticker == "AAPL"
    assert primary.exchange_code == "UW"
    assert primary.composite_figi == "BBG000B9Y5X2"
    assert primary.share_class_figi == "BBG001S5N8V8"
    assert primary.currency == "USD"
    assert result.is_ambiguous is False
    assert result.warning is None

    # Provenance carries provider name, URL, query params, lineage hash.
    prov = result.provenance
    assert prov.provider_name == "openfigi_mapper"
    assert prov.provider_url == "https://api.openfigi.com/v3/mapping"
    assert prov.symbol_count == 1
    assert prov.row_count == 1
    assert prov.lineage.snapshot_hash != ""
    assert prov.lineage.contract_hash != ""
    assert prov.auth_mode == "none"

    # Captured wire payload: idType=TICKER, idValue=AAPL, exchCode=US.
    assert captured["url"] == PROVIDER_URL
    job = captured["payload"][0]
    assert job["idType"] == "TICKER"
    assert job["idValue"] == "AAPL"
    assert job["exchCode"] == "US"
    assert "X-OPENFIGI-APIKEY" not in captured["headers"]


# ---------------------------------------------------------------------------
# 3. No-match response preserves warning, returns empty mappings.
# ---------------------------------------------------------------------------


def test_no_match_returns_empty_mappings_with_warning():
    def http_post(url, payload, headers):
        return [{"warning": "No identifier found."}]

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("ZZZZ", exchange="US")

    assert result.mappings == ()
    assert result.is_ambiguous is False
    assert result.warning == "No identifier found."
    # Provenance still constructed for audit trail.
    assert result.provenance.row_count == 0
    assert result.provenance.symbol_count == 0


# ---------------------------------------------------------------------------
# 4. Ambiguous response preserves all candidates.
# ---------------------------------------------------------------------------


def test_ambiguous_response_preserves_all_candidates():
    rows = [
        _aapl_response_row(figi="BBG000A", exch="UW"),
        _aapl_response_row(figi="BBG000B", exch="UN"),
        _aapl_response_row(figi="BBG000C", exch="UA"),
    ]

    def http_post(url, payload, headers):
        return _expect_one(rows)

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("AAPL")  # no exchange filter

    # Every candidate must be preserved -- no silent first-match.
    assert len(result.mappings) == 3
    assert tuple(m.figi for m in result.mappings) == (
        "BBG000A", "BBG000B", "BBG000C",
    )
    assert tuple(m.exchange_code for m in result.mappings) == (
        "UW", "UN", "UA",
    )
    assert result.is_ambiguous is True
    assert result.warning is None


# ---------------------------------------------------------------------------
# 5. Explicit exchange filter narrows the result.
# ---------------------------------------------------------------------------


def test_explicit_exchange_filter_disambiguates():
    seen_jobs: list[Mapping[str, Any]] = []

    def http_post(url, payload, headers):
        seen_jobs.extend(payload)
        # Simulate OpenFIGI: when exchange=US is passed, only one
        # candidate is returned.
        return _expect_one([_aapl_response_row(figi="BBG000US", exch="US")])

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("AAPL", exchange="US")

    assert len(result.mappings) == 1
    assert result.mappings[0].figi == "BBG000US"
    assert result.is_ambiguous is False
    # Confirm the wire payload actually carried the filter.
    assert seen_jobs[0]["exchCode"] == "US"


# ---------------------------------------------------------------------------
# 6. Bulk map preserves per-query results in order.
# ---------------------------------------------------------------------------


def test_bulk_map_preserves_per_query_results():
    inputs = [
        {"ticker": "AAPL", "exchange": "US"},
        {"ticker": "MSFT", "exchange": "US"},
        {"ticker": "ZZZZ", "exchange": "US"},  # no match
        {"ticker": "TSLA"},                     # ambiguous (3 venues)
        {"id_type": "ISIN", "id_value": "US0378331005"},
    ]

    def http_post(url, payload, headers):
        # Sanity-check: provider sent one job per input, in order.
        assert len(payload) == 5
        assert payload[0]["idValue"] == "AAPL"
        assert payload[1]["idValue"] == "MSFT"
        assert payload[2]["idValue"] == "ZZZZ"
        assert payload[3]["idValue"] == "TSLA"
        assert payload[4]["idType"] == "ID_ISIN"
        assert payload[4]["idValue"] == "US0378331005"
        return [
            {"data": [_aapl_response_row(figi="AAPL_FIGI", ticker="AAPL")]},
            {"data": [_aapl_response_row(figi="MSFT_FIGI", ticker="MSFT")]},
            {"warning": "No identifier found."},
            {
                "data": [
                    _aapl_response_row(figi="TSLA_A", ticker="TSLA", exch="UW"),
                    _aapl_response_row(figi="TSLA_B", ticker="TSLA", exch="UN"),
                    _aapl_response_row(figi="TSLA_C", ticker="TSLA", exch="UA"),
                ],
            },
            {
                "data": [
                    _aapl_response_row(
                        figi="ISIN_AAPL",
                        unique_id="US0378331005",
                        unique_id_type="ID_ISIN",
                    ),
                ],
            },
        ]

    client = OpenFIGIClient(http_post=http_post)
    results = client.bulk_map(inputs)

    assert len(results) == 5
    assert results[0].mappings[0].figi == "AAPL_FIGI"
    assert results[1].mappings[0].figi == "MSFT_FIGI"
    assert results[2].mappings == ()
    assert results[2].warning == "No identifier found."
    assert results[3].is_ambiguous is True
    assert tuple(m.figi for m in results[3].mappings) == (
        "TSLA_A", "TSLA_B", "TSLA_C",
    )
    assert results[4].mappings[0].unique_id == "US0378331005"
    assert results[4].mappings[0].unique_id_type == "ID_ISIN"


# ---------------------------------------------------------------------------
# 7. Missing http client raises with operator-facing message.
# ---------------------------------------------------------------------------


def test_missing_http_client_raises():
    client = OpenFIGIClient()  # no http_post
    with pytest.raises(RuntimeError) as exc:
        client.map_symbol("AAPL")
    msg = str(exc.value)
    assert "OpenFIGI" in msg
    assert "injected HTTP client" in msg
    assert "operator credentials" in msg


# ---------------------------------------------------------------------------
# 8. Security Master integration.
# ---------------------------------------------------------------------------


def test_security_master_from_openfigi_mapping():
    def http_post(url, payload, headers):
        return _expect_one(
            [
                _aapl_response_row(
                    figi="BBG000B9XRY4",
                    ticker="AAPL",
                    exch="UW",
                    composite="BBG000B9Y5X2",
                    share_class="BBG001S5N8V8",
                    currency="USD",
                    unique_id="037833100",
                    unique_id_type="ID_CUSIP",
                ),
                _aapl_response_row(
                    figi="BBG000B9Y5W3",
                    ticker="AAPL",
                    exch="UN",
                ),
            ]
        )

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("AAPL", exchange="US")
    record = from_openfigi_mapping(result)

    assert isinstance(record, SecurityMasterRecord)
    assert record.symbol == "AAPL"
    assert record.figi == "BBG000B9XRY4"
    assert record.composite_figi == "BBG000B9Y5X2"
    assert record.share_class_figi == "BBG001S5N8V8"
    assert record.exchange == "UW"
    assert record.currency == "USD"
    assert record.cusip == "037833100"
    assert record.isin is None  # unique_id_type was CUSIP, not ISIN
    # Both candidates preserved on figi_mappings.
    assert len(record.figi_mappings) == 2
    assert record.figi_mappings[0]["figi"] == "BBG000B9XRY4"
    assert record.figi_mappings[1]["figi"] == "BBG000B9Y5W3"


def test_security_master_from_openfigi_isin_routing():
    """ISIN unique_id_type lands on the isin field, not cusip/sedol."""
    def http_post(url, payload, headers):
        return _expect_one(
            [
                _aapl_response_row(
                    unique_id="US0378331005",
                    unique_id_type="ID_ISIN",
                ),
            ]
        )

    client = OpenFIGIClient(http_post=http_post)
    result = client.map_symbol("AAPL", exchange="US")
    record = from_openfigi_mapping(result)
    assert record.isin == "US0378331005"
    assert record.cusip is None
    assert record.sedol is None


# ---------------------------------------------------------------------------
# 9. API key plumbing -- header set when env var present.
# ---------------------------------------------------------------------------


def test_api_key_sets_header_and_lifts_rate_limit(monkeypatch):
    captured: dict[str, Any] = {}

    def http_post(url, payload, headers):
        captured["headers"] = dict(headers)
        return _expect_one([_aapl_response_row()])

    monkeypatch.setenv("AU_OPENFIGI_API_KEY", "test-token-do-not-log")
    client = OpenFIGIClient(http_post=http_post)
    client.map_symbol("AAPL")
    assert captured["headers"].get("X-OPENFIGI-APIKEY") == "test-token-do-not-log"
    assert client.auth_mode == "api_key"
    # Authenticated ceiling per public docs.
    assert client._rate_limit_ceiling() == 250


def test_unauthenticated_rate_limit_ceiling():
    client = OpenFIGIClient(http_post=lambda u, p, h: [])
    assert client._rate_limit_ceiling() == 25
    assert client.auth_mode == "none"
