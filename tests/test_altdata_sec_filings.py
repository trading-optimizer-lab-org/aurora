"""Tests for aurora.altdata.sec_filings."""
from __future__ import annotations

import pytest

from aurora.altdata.sec_filings import SECConfig, SECFilingsAdapter


@pytest.fixture
def adapter() -> SECFilingsAdapter:
    return SECFilingsAdapter()


def test_pad_cik():
    assert SECFilingsAdapter._pad_cik("320193") == "0000320193"
    assert SECFilingsAdapter._pad_cik("0000320193") == "0000320193"


def test_pad_cik_strips_non_digits():
    assert SECFilingsAdapter._pad_cik("CIK-320193") == "0000320193"


def test_pad_cik_rejects_empty():
    with pytest.raises(ValueError):
        SECFilingsAdapter._pad_cik("abc")


def test_mock_returns_requested_forms(adapter: SECFilingsAdapter):
    df = adapter.get_filings(
        cik="320193", ticker="AAPL",
        forms=("10-K", "10-Q"), mock=True,
    )
    assert list(df.columns) == [
        "cik", "ticker", "form_type", "filing_date",
        "accession_number", "primary_doc", "filing_url",
    ]
    assert set(df["form_type"]) == {"10-K", "10-Q"}
    assert (df["ticker"] == "AAPL").all()
    assert df["filing_url"].str.startswith("https://www.sec.gov/").all()


def test_invalid_form_rejected(adapter: SECFilingsAdapter):
    with pytest.raises(ValueError, match="unsupported"):
        adapter.get_filings(cik="320193", forms=("S-1",), mock=True)


def test_build_filing_url_format():
    url = SECFilingsAdapter.build_filing_url(
        "0000320193", "0001234567-24-000010", "doc.htm",
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000123456724000010/doc.htm"
    )
