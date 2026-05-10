"""Tests for R174 deterministic claim extraction."""
from __future__ import annotations

from pathlib import Path

import pytest
from aurora.research.literature import (
    MAX_QUOTE_LENGTH,
    PaperClaim,
    PaperRecord,
    extract_claims_from_text,
    ingest_text_fixture,
)

FIXTURES = Path(__file__).parent / "fixtures" / "literature"


def _record_for(text: str) -> PaperRecord:
    """Build a minimal :class:`PaperRecord` for in-memory test text."""
    return PaperRecord(
        paper_id="paper-test-fixture",
        title="Test paper",
        authors=("A",),
        year=2020,
        source="local_text_fixture",
        url_or_path="/tmp/x.txt",
        doi=None,
        ssrn_id=None,
        licence_note="",
        ingestion_time="2026-05-10T00:00:00Z",
        content_hash="0" * 64,
        extraction_status="text_extracted",
        page_count=1,
    )


def test_claims_extracted_from_sample_fixture() -> None:
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    claims = extract_claims_from_text(record, text)
    assert len(claims) >= 3, [c.claim_id for c in claims]


def test_quote_length_limit_raises() -> None:
    with pytest.raises(ValueError, match="quote_excerpt"):
        PaperClaim(
            claim_id="paper-x-claim-1",
            paper_id="paper-x",
            claim_text="x",
            asset_class="equity",
            sample_period="",
            universe="unspecified",
            data_frequency="unspecified",
            reported_metrics={},
            transaction_costs_included=False,
            oos_included=False,
            assumptions=(),
            limitations=(),
            replication_requirements=(),
            red_flags=(),
            page_reference="",
            quote_excerpt="A" * (MAX_QUOTE_LENGTH + 1),
        )


def test_quote_length_at_limit_is_accepted() -> None:
    """Exactly MAX_QUOTE_LENGTH characters must be allowed."""
    claim = PaperClaim(
        claim_id="paper-x-claim-1",
        paper_id="paper-x",
        claim_text="x",
        asset_class="equity",
        sample_period="",
        universe="unspecified",
        data_frequency="unspecified",
        reported_metrics={},
        transaction_costs_included=False,
        oos_included=False,
        assumptions=(),
        limitations=(),
        replication_requirements=(),
        red_flags=(),
        page_reference="",
        quote_excerpt="A" * MAX_QUOTE_LENGTH,
    )
    assert len(claim.quote_excerpt) == MAX_QUOTE_LENGTH


def test_missing_page_reference_still_produces_a_claim() -> None:
    text = (
        "We backtest a daily mean-reversion strategy on US equities over "
        "2010-2018. The strategy delivers a Sharpe ratio of 0.85 net of "
        "transaction costs. Out-of-sample testing covers 2017-2018. "
    )
    record = _record_for(text)
    claims = extract_claims_from_text(record, text)
    assert len(claims) >= 1
    # No "p.X" token in the source -> page_reference must be empty.
    assert all(c.page_reference == "" for c in claims)


def test_extraction_is_deterministic_for_same_input() -> None:
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    a = extract_claims_from_text(record, text)
    b = extract_claims_from_text(record, text)
    assert [c.claim_id for c in a] == [c.claim_id for c in b]
    assert a == b


def test_red_flag_guaranteed_returns_is_detected() -> None:
    record, text = ingest_text_fixture(FIXTURES / "red_flag_paper.txt")
    claims = extract_claims_from_text(record, text)
    flagged = [c for c in claims if "guaranteed_returns" in c.red_flags]
    assert flagged, [
        (c.claim_id, c.red_flags) for c in claims
    ]


def test_costs_included_is_detected_when_explicit() -> None:
    text = (
        "The strategy delivers a Sharpe ratio of 1.0 over 2010-2020 net "
        "of transaction costs. We rebalance daily."
    )
    record = _record_for(text)
    claims = extract_claims_from_text(record, text)
    assert claims, "expected at least one claim"
    assert any(c.transaction_costs_included for c in claims)


def test_oos_included_is_detected_when_walk_forward_present() -> None:
    text = (
        "We use walk-forward analysis on monthly returns and report a "
        "Sharpe ratio of 0.7 over the sample period 2005-2018."
    )
    record = _record_for(text)
    claims = extract_claims_from_text(record, text)
    assert any(c.oos_included for c in claims)


def test_metrics_extracted_from_text() -> None:
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    claims = extract_claims_from_text(record, text)
    found_metrics: dict[str, float] = {}
    for c in claims:
        found_metrics.update(c.reported_metrics)
    assert "sharpe" in found_metrics
    assert found_metrics["sharpe"] > 0


def test_empty_text_produces_no_claims() -> None:
    record = _record_for("")
    claims = extract_claims_from_text(record, "")
    assert claims == []


def test_extraction_rejects_non_string_text() -> None:
    record = _record_for("dummy")
    with pytest.raises(TypeError):
        extract_claims_from_text(record, 12345)  # type: ignore[arg-type]
