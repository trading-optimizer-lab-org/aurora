"""Tests for R174 reliability scoring."""
from __future__ import annotations

from pathlib import Path

from aurora.research.literature import (
    PaperClaim,
    PaperRecord,
    extract_claims_from_text,
    ingest_text_fixture,
    score_paper,
)

FIXTURES = Path(__file__).parent / "fixtures" / "literature"


def _bare_record(paper_id: str = "paper-rel-test") -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        title="Reliability test",
        authors=(),
        year=2020,
        source="local_text_fixture",
        url_or_path="/tmp/x.txt",
        doi=None,
        ssrn_id=None,
        licence_note="",
        ingestion_time="2026-05-10T00:00:00Z",
        content_hash="0" * 64,
        extraction_status="claims_extracted",
        page_count=1,
    )


def _claim(
    *,
    paper_id: str = "paper-rel-test",
    suffix: str = "x",
    oos: bool = False,
    costs: bool = False,
    metrics: dict[str, float] | None = None,
    sample_period: str = "",
    replication: tuple[str, ...] = (),
    red_flags: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    text_body: str = "claim",
) -> PaperClaim:
    return PaperClaim(
        claim_id=f"{paper_id}-{suffix}",
        paper_id=paper_id,
        claim_text=text_body,
        asset_class="equity",
        sample_period=sample_period,
        universe="unspecified",
        data_frequency="daily",
        reported_metrics=metrics or {},
        transaction_costs_included=costs,
        oos_included=oos,
        assumptions=(),
        limitations=limitations,
        replication_requirements=replication,
        red_flags=red_flags,
        page_reference="",
        quote_excerpt=text_body,
    )


def test_score_is_in_unit_interval() -> None:
    rec = _bare_record()
    score = score_paper(rec, [])
    assert 0.0 <= score.score <= 1.0


def test_score_zero_when_no_positive_flags() -> None:
    rec = _bare_record()
    # An empty claims list trips none of the seven flags.
    score = score_paper(rec, [])
    assert score.score == 0.0
    assert score.reproducible_data is False
    assert score.costs_included is False
    assert score.oos_included is False
    assert score.multiple_testing_addressed is False
    assert score.survivorship_handled is False
    assert score.code_available is False
    assert score.sample_size_adequate is False


def test_score_increases_with_each_positive_flag() -> None:
    rec = _bare_record()
    base = score_paper(rec, [])
    one_flag = score_paper(rec, [
        _claim(suffix="oos", oos=True),
    ])
    two_flags = score_paper(rec, [
        _claim(suffix="oos", oos=True),
        _claim(suffix="cost", costs=True),
    ])
    assert one_flag.score > base.score
    assert two_flags.score > one_flag.score


def test_score_is_deterministic_for_same_input() -> None:
    rec = _bare_record()
    claims = [
        _claim(suffix="oos", oos=True, sample_period="2005-2020"),
        _claim(suffix="cost", costs=True),
    ]
    a = score_paper(rec, claims)
    b = score_paper(rec, claims)
    assert a == b


def test_missing_flags_treated_as_zero_not_half() -> None:
    """A paper with one positive flag must score 1/7, not 0.5."""
    rec = _bare_record()
    score = score_paper(rec, [_claim(suffix="oos", oos=True)])
    assert abs(score.score - (1.0 / 7.0)) < 1e-9


def test_red_flag_survivorship_unaddressed_blocks_handled() -> None:
    rec = _bare_record()
    claims = [
        _claim(
            suffix="surv",
            text_body="survivorship bias has been addressed",
            red_flags=("survivorship_unaddressed",),
        ),
    ]
    score = score_paper(rec, claims)
    assert score.survivorship_handled is False


def test_code_available_does_not_accept_github_text_in_unrelated_url_path() -> None:
    rec = _bare_record()
    claims = [
        _claim(
            suffix="url",
            text_body="Details: https://evil.example/github.com/fake/repository",
        ),
    ]

    assert score_paper(rec, claims).code_available is False


def test_full_fixture_produces_meaningful_score() -> None:
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    claims = extract_claims_from_text(record, text)
    score = score_paper(record, claims)
    # Sample fixture asserts costs, OOS, public universe, code available,
    # 2005-2020 (>=10 years sample). Should clear several flags.
    assert score.score > 0.4
    assert score.oos_included is True
    assert score.costs_included is True
    assert score.code_available is True
    assert score.sample_size_adequate is True
