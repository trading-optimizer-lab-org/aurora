"""Tests for the R156 SEC EDGAR companyfacts provider.

All tests use injected HTTP clients + local fixtures. No test makes a
live network call. Coverage spans the descriptor, the JSON parsers,
the bulk-archive ZIP path, the point-in-time gate and the env-var
guard for the User-Agent header.
"""
from __future__ import annotations

import io
import json
import warnings
import zipfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pytest

from aurora.core.data_providers import ProviderRole
from aurora.core.data_providers.sec_edgar_companyfacts import (
    PROVIDER_NAME,
    SEC_EDGAR_DESCRIPTOR,
    USER_AGENT_ENV_VAR,
    CIKMapping,
    CompanyFactsBundle,
    SECEdgarClient,
    Submission,
    XBRLFact,
    assert_pit_safe,
    descriptor,
    facts_to_dataframe,
    filter_pit_safe,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


_TICKER_CIK_FIXTURE: dict[str, dict[str, Any]] = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    "2": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."},
}


def _submissions_fixture() -> dict[str, Any]:
    return {
        "cik": "320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-23-000106",
                    "0000320193-22-000108",
                ],
                "filingDate": ["2023-11-03", "2022-10-28"],
                "acceptanceDateTime": [
                    "2023-11-03T18:08:42.000Z",
                    "2022-10-28T18:01:14.000Z",
                ],
                "form": ["10-K", "10-K"],
                "primaryDocument": ["aapl-20230930.htm", "aapl-20220924.htm"],
                "periodOfReport": ["2023-09-30", "2022-09-24"],
                "isXBRL": [1, 1],
            }
        },
    }


def _companyfacts_fixture() -> dict[str, Any]:
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "description": "Net revenues",
                    "units": {
                        "USD": [
                            {
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "accn": "0000320193-23-000106",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accepted": "2023-11-03T18:08:42.000Z",
                                "frame": "CY2023",
                            },
                            {
                                "start": "2021-09-26",
                                "end": "2022-09-24",
                                "val": 394328000000,
                                "accn": "0000320193-22-000108",
                                "fy": 2022,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2022-10-28",
                                "accepted": "2022-10-28T18:01:14.000Z",
                                "frame": "CY2022",
                            },
                        ],
                    },
                },
            },
        },
    }


def _companyfacts_with_unit_inconsistency() -> dict[str, Any]:
    """Same tag reports both USD and EUR -- triggers a unit warning."""
    return {
        "cik": 11111,
        "entityName": "Mixed Unit Co",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 100.0,
                                "accn": "x",
                                "form": "10-K",
                                "filed": "2024-02-01",
                                "accepted": "2024-02-01T00:00:00.000Z",
                            }
                        ],
                        "EUR": [
                            {
                                "end": "2023-12-31",
                                "val": 90.0,
                                "accn": "x",
                                "form": "10-K",
                                "filed": "2024-02-01",
                                "accepted": "2024-02-01T00:00:00.000Z",
                            }
                        ],
                    }
                }
            }
        },
    }


def _make_client(payloads: Mapping[str, Any]):
    """Build an http_get callable that maps URL prefix -> JSON payload."""

    def _client(url: str, headers: Mapping[str, str]) -> bytes:
        # Ensure required header is present.
        assert headers.get("User-Agent"), "missing User-Agent"
        for key, payload in payloads.items():
            if key in url:
                return json.dumps(payload).encode("utf-8")
        raise AssertionError(f"unexpected URL: {url}")

    return _client


@pytest.fixture
def env_user_agent(monkeypatch):
    monkeypatch.setenv(USER_AGENT_ENV_VAR, "Aurora Test test@example.com")
    return "Aurora Test test@example.com"


# ---------------------------------------------------------------------------
# 1. Descriptor.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability():
    d = SEC_EDGAR_DESCRIPTOR
    assert d.name == PROVIDER_NAME
    assert d.role is ProviderRole.FUNDAMENTALS
    assert d.reliability == "OFFICIAL"
    assert d.adjustment_posture == "RAW"
    assert d.auth_required is False
    assert "equity" in d.asset_classes
    assert "filing" in d.intervals
    # descriptor() free function returns the same singleton.
    assert descriptor() is SEC_EDGAR_DESCRIPTOR


# ---------------------------------------------------------------------------
# 2. User-Agent guard.
# ---------------------------------------------------------------------------


def test_missing_user_agent_raises(monkeypatch):
    monkeypatch.delenv(USER_AGENT_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        SECEdgarClient(http_get=lambda u, h: b"{}")
    assert USER_AGENT_ENV_VAR in str(excinfo.value)


def test_user_agent_from_env_var(monkeypatch):
    monkeypatch.setenv(USER_AGENT_ENV_VAR, "Aurora Quant ops@example.com")
    client = SECEdgarClient(http_get=lambda u, h: b"{}")
    assert client._user_agent == "Aurora Quant ops@example.com"


# ---------------------------------------------------------------------------
# 3. Ticker / CIK mapping.
# ---------------------------------------------------------------------------


def test_fetch_ticker_cik_map_parses_json_fixture(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({"company_tickers": _TICKER_CIK_FIXTURE}),
    )
    rows = client.fetch_ticker_cik_map()
    assert len(rows) == 3
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["AAPL"].cik == 320193
    assert by_ticker["MSFT"].cik == 789019
    assert by_ticker["TSLA"].name == "Tesla, Inc."
    for row in rows:
        assert isinstance(row, CIKMapping)


# ---------------------------------------------------------------------------
# 4. Submissions.
# ---------------------------------------------------------------------------


def test_fetch_submissions_returns_filed_iso(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({"submissions": _submissions_fixture()}),
    )
    subs = client.fetch_submissions(320193)
    assert len(subs) == 2
    first = subs[0]
    assert isinstance(first, Submission)
    assert first.accession_number == "0000320193-23-000106"
    assert first.filing_date_iso == "2023-11-03"
    assert first.accepted_iso.startswith("2023-11-03T18:08")
    assert first.form == "10-K"
    assert first.is_xbrl is True


# ---------------------------------------------------------------------------
# 5. Companyfacts parsing.
# ---------------------------------------------------------------------------


def test_fetch_companyfacts_extracts_us_gaap_facts(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({
            "companyfacts": _companyfacts_fixture(),
            "submissions": _submissions_fixture(),
        }),
    )
    bundle = client.fetch_companyfacts(320193)
    assert isinstance(bundle, CompanyFactsBundle)
    assert bundle.cik == 320193
    assert bundle.entity_name == "Apple Inc."
    assert len(bundle.facts) == 2
    f0 = bundle.facts[0]
    assert isinstance(f0, XBRLFact)
    assert f0.taxonomy == "us-gaap"
    assert f0.tag == "Revenues"
    assert f0.unit == "USD"
    assert f0.value > 0
    assert f0.form == "10-K"


def test_facts_carry_accepted_iso_for_pit(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({
            "companyfacts": _companyfacts_fixture(),
            "submissions": _submissions_fixture(),
        }),
    )
    bundle = client.fetch_companyfacts(320193)
    for fact in bundle.facts:
        assert fact.accepted_iso, "every fact must carry accepted_iso"
        # accepted_iso should be parseable as a Timestamp.
        ts = pd.Timestamp(fact.accepted_iso)
        assert isinstance(ts, pd.Timestamp)


# ---------------------------------------------------------------------------
# 6. Point-in-time guard.
# ---------------------------------------------------------------------------


def _make_fact(accepted_iso: str, accession: str = "x", value: float = 1.0) -> XBRLFact:
    return XBRLFact(
        cik=1,
        taxonomy="us-gaap",
        tag="Revenues",
        unit="USD",
        value=value,
        period_start_iso="2023-01-01",
        period_end_iso="2023-03-31",
        frame="CY2023Q1",
        accession_number=accession,
        filing_date_iso=accepted_iso[:10],
        accepted_iso=accepted_iso,
        form="10-Q",
        source_url="https://example.test/x.json",
    )


def test_assert_pit_safe_blocks_future_fact():
    fact = _make_fact("2023-06-01T00:00:00.000Z")
    decision = pd.Timestamp("2023-05-01")
    with pytest.raises(ValueError) as excinfo:
        assert_pit_safe(fact, decision)
    assert "cannot be used" in str(excinfo.value)


def test_assert_pit_safe_passes_when_accepted_before_decision():
    fact = _make_fact("2023-04-15T00:00:00.000Z")
    assert_pit_safe(fact, pd.Timestamp("2023-05-01")) is None


def test_filter_pit_safe_drops_future_facts():
    decision = pd.Timestamp("2023-05-01")
    facts = [
        _make_fact("2023-01-01T00:00:00.000Z", accession="a"),
        _make_fact("2023-02-15T00:00:00.000Z", accession="b"),
        _make_fact("2023-06-01T00:00:00.000Z", accession="c"),
        _make_fact("2023-07-01T00:00:00.000Z", accession="d"),
        _make_fact("2023-08-01T00:00:00.000Z", accession="e"),
    ]
    safe = filter_pit_safe(tuple(facts), decision)
    assert isinstance(safe, tuple)
    assert len(safe) == 2
    accessions = {f.accession_number for f in safe}
    assert accessions == {"a", "b"}


# ---------------------------------------------------------------------------
# 7. Bulk archive ZIP ingestion.
# ---------------------------------------------------------------------------


def _build_companyfacts_zip(tmp_path: Path) -> Path:
    """Build a minimal companyfacts ZIP with two CIK entries."""
    zp = tmp_path / "companyfacts.zip"
    body_a = _companyfacts_fixture()
    body_b = {
        "cik": 789019,
        "entityName": "Microsoft Corp",
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-06-30",
                                "val": 72361000000,
                                "accn": "0001193125-23-001234",
                                "form": "10-K",
                                "filed": "2023-07-27",
                                "accepted": "2023-07-27T16:33:11.000Z",
                                "frame": "CY2023",
                            }
                        ]
                    }
                }
            }
        },
    }
    with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CIK0000320193.json", json.dumps(body_a))
        zf.writestr("CIK0000789019.json", json.dumps(body_b))
    return zp


def test_companyfacts_zip_ingest_yields_bundles(tmp_path, env_user_agent):
    zp = _build_companyfacts_zip(tmp_path)
    client = SECEdgarClient(http_get=lambda u, h: b"{}")
    bundles = list(client.ingest_companyfacts_zip(zp))
    assert len(bundles) == 2
    ciks = sorted(b.cik for b in bundles)
    assert ciks == [320193, 789019]
    for bundle in bundles:
        assert bundle.facts, "bundle must carry parsed facts"
        for fact in bundle.facts:
            assert fact.accepted_iso  # PIT axis populated even from bulk
            assert fact.source_url.startswith("zip://")


# ---------------------------------------------------------------------------
# 8. Amendment preservation (same tag, two accession numbers).
# ---------------------------------------------------------------------------


def _companyfacts_with_amendment() -> dict[str, Any]:
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "accn": "0000320193-23-000106",  # original
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accepted": "2023-11-03T18:08:42.000Z",
                            },
                            {
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383290000000,  # restated
                                "accn": "0000320193-24-000005",  # amendment
                                "form": "10-K/A",
                                "filed": "2024-01-15",
                                "accepted": "2024-01-15T17:01:00.000Z",
                            },
                        ]
                    }
                }
            }
        },
    }


def test_amended_fact_preserved_with_distinct_accession(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({
            "companyfacts": _companyfacts_with_amendment(),
            "submissions": {"cik": "320193", "filings": {"recent": {}}},
        }),
    )
    bundle = client.fetch_companyfacts(320193)
    assert len(bundle.facts) == 2
    accns = {f.accession_number for f in bundle.facts}
    assert accns == {"0000320193-23-000106", "0000320193-24-000005"}
    forms = {f.form for f in bundle.facts}
    assert "10-K" in forms
    assert "10-K/A" in forms
    # Same period_end_iso on both -- the amendment must not erase the original.
    period_ends = {f.period_end_iso for f in bundle.facts}
    assert period_ends == {"2023-09-30"}


# ---------------------------------------------------------------------------
# 9. Unit consistency warning.
# ---------------------------------------------------------------------------


def test_unit_consistency_warning(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({
            "companyfacts": _companyfacts_with_unit_inconsistency(),
            "submissions": {"cik": "11111", "filings": {"recent": {}}},
        }),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bundle = client.fetch_companyfacts(11111)
    msgs = [str(w.message) for w in caught]
    assert any("unit_inconsistency" in m for m in msgs)
    # Provenance must record the warning text too.
    extra = bundle.provenance.extra
    unit_warnings = extra.get("unit_warnings", [])
    assert any("unit_inconsistency" in m for m in unit_warnings)
    # Both unit rows survive parsing -- we never drop facts silently.
    units = sorted({f.unit for f in bundle.facts})
    assert units == ["EUR", "USD"]


# ---------------------------------------------------------------------------
# 10. Provenance carries endpoint + retrieval timestamp.
# ---------------------------------------------------------------------------


def test_provenance_carries_endpoint_and_retrieval(env_user_agent):
    client = SECEdgarClient(
        http_get=_make_client({
            "companyfacts": _companyfacts_fixture(),
            "submissions": _submissions_fixture(),
        }),
    )
    bundle = client.fetch_companyfacts(320193)
    p = bundle.provenance
    assert p.provider_name == PROVIDER_NAME
    assert p.auth_mode == "user_agent"
    assert p.retrieved_at_iso  # non-empty ISO timestamp
    assert "endpoint" in p.extra
    assert "320193" in p.extra["endpoint"]
    assert p.extra["asset_class"] == "FUNDAMENTALS"
    assert p.extra["library"] == "fundamentals_sec"
    assert p.extra["reliability"] == "OFFICIAL"
    # query_params must record the cik argument so an auditor can replay.
    assert p.query_params.get("cik") == 320193


# ---------------------------------------------------------------------------
# 11. DataFrame conversion & registry registration.
# ---------------------------------------------------------------------------


def test_facts_to_dataframe_round_trip():
    facts = (
        _make_fact("2023-04-15T00:00:00.000Z", accession="a", value=100.0),
        _make_fact("2023-05-15T00:00:00.000Z", accession="b", value=200.0),
    )
    df = facts_to_dataframe(facts)
    assert len(df) == 2
    expected_cols = {
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_start_iso",
        "period_end_iso",
        "frame",
        "accession_number",
        "filing_date_iso",
        "accepted_iso",
        "form",
        "source_url",
    }
    assert expected_cols.issubset(set(df.columns))
    assert df["value"].iloc[0] == 100.0
    assert df["value"].iloc[1] == 200.0


def test_provider_registered_in_default_registry():
    from aurora.core.data_providers import (
        ProviderRole,
        get_default_registry,
        reset_default_registry,
    )

    reset_default_registry()
    try:
        registry = get_default_registry()
        names = registry.list_by_role(ProviderRole.FUNDAMENTALS)
        assert PROVIDER_NAME in names
        d = registry.descriptor_for(PROVIDER_NAME)
        assert d is not None
        assert d.role is ProviderRole.FUNDAMENTALS
    finally:
        reset_default_registry()
