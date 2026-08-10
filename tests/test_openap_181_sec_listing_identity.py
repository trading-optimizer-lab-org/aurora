from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.sec_listing_identity import (
    build_current_sec_universe,
    build_sec_listing_intervals,
    calculate_sec_exch_switch_current,
    extract_sec_listing_observations,
    filter_market_bars_by_sec_identity,
    normalize_sec_notes_listing_facts,
    parse_current_sec_identity_response,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
ROOT = Path(__file__).resolve().parents[1]


def test_current_sec_universe_uses_only_direct_official_identity() -> None:
    payload = {
        "fields": ["cik", "name", "tickers", "exchanges"],
        "data": [
            [320193, "Apple Inc.", ["AAPL"], ["Nasdaq"]],
            [789019, "Microsoft Corp", ["MSFT"], ["Nasdaq"]],
            [1000045, "Dual Class Corp", ["DUAL.A", "DUAL.B"], ["NYSE", "NYSE"]],
            [1000046, "Unsupported Venue Corp", ["OTCX"], ["OTC"]],
        ],
    }

    universe, rejected = build_current_sec_universe(
        payload,
        retrieved_at="2026-08-10T12:15:00Z",
        source_url="https://www.sec.gov/files/company_tickers_exchange.json",
    )

    assert universe[
        [
            "security_id",
            "ticker",
            "cik",
            "exchange_family",
            "issuer_share_class_count",
            "identity_available_at",
            "identity_source_url",
        ]
    ].to_dict(orient="records") == [
        {
            "security_id": "US-SEC-0000320193-AAPL",
            "ticker": "AAPL",
            "cik": "0000320193",
            "exchange_family": "NASDAQ",
            "issuer_share_class_count": 1,
            "identity_available_at": "2026-08-10T12:15:00+00:00",
            "identity_source_url": (
                "https://www.sec.gov/files/company_tickers_exchange.json"
            ),
        },
        {
            "security_id": "US-SEC-0000789019-MSFT",
            "ticker": "MSFT",
            "cik": "0000789019",
            "exchange_family": "NASDAQ",
            "issuer_share_class_count": 1,
            "identity_available_at": "2026-08-10T12:15:00+00:00",
            "identity_source_url": (
                "https://www.sec.gov/files/company_tickers_exchange.json"
            ),
        },
        {
            "security_id": "US-SEC-0001000045-DUALA",
            "ticker": "DUAL.A",
            "cik": "0001000045",
            "exchange_family": "NYSE",
            "issuer_share_class_count": 2,
            "identity_available_at": "2026-08-10T12:15:00+00:00",
            "identity_source_url": (
                "https://www.sec.gov/files/company_tickers_exchange.json"
            ),
        },
        {
            "security_id": "US-SEC-0001000045-DUALB",
            "ticker": "DUAL.B",
            "cik": "0001000045",
            "exchange_family": "NYSE",
            "issuer_share_class_count": 2,
            "identity_available_at": "2026-08-10T12:15:00+00:00",
            "identity_source_url": (
                "https://www.sec.gov/files/company_tickers_exchange.json"
            ),
        },
    ]
    assert rejected.to_dict(orient="records") == [
        {
            "cik": "0001000046",
            "ticker": "OTCX",
            "exchange": "OTC",
            "reason_if_rejected": "unsupported_current_exchange",
        }
    ]


def test_current_sec_universe_rejects_unofficial_or_future_provenance() -> None:
    payload = {
        "fields": ["cik", "name", "tickers", "exchanges"],
        "data": [[320193, "Apple Inc.", ["AAPL"], ["Nasdaq"]]],
    }

    with pytest.raises(ValueError, match="official SEC"):
        build_current_sec_universe(
            payload,
            retrieved_at="2026-08-10T12:15:00Z",
            source_url="https://example.com/company_tickers_exchange.json",
        )
    with pytest.raises(ValueError, match="retrieved_at"):
        build_current_sec_universe(
            payload,
            retrieved_at="not-a-timestamp",
            source_url="https://www.sec.gov/files/company_tickers_exchange.json",
        )


def test_current_sec_identity_parser_accepts_direct_and_audited_readthrough() -> None:
    direct = (
        b'{"fields":["cik","name","tickers","exchanges"],'
        b'"data":[[320193,"Apple Inc.",["AAPL"],["Nasdaq"]]]}'
    )
    readthrough = b"\n".join(
        [
            b"Title: SEC current company tickers",
            b"Markdown Content:",
            b"```json",
            direct,
            b"```",
        ]
    )

    assert parse_current_sec_identity_response(
        direct,
        access_method="sec_official_direct",
    ) == parse_current_sec_identity_response(
        readthrough,
        access_method="sec_via_jina_readthrough",
    )

    with pytest.raises(ValueError, match="marker"):
        parse_current_sec_identity_response(
            direct,
            access_method="sec_via_jina_readthrough",
        )


def test_exchange_switch_workflow_acquires_direct_official_sec_identity() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-exchange-switch.yml"
    ).read_text(encoding="utf-8")

    assert "https://www.sec.gov/files/company_tickers_exchange.json" in workflow
    assert "recover_openap_market_security_master.py" not in workflow
    assert "--current-sec-identity-json" in workflow
    assert "--identity-retrieved-at" in workflow
    assert "--identity-transport-manifest" in workflow
    assert (
        "https://r.jina.ai/http://www.sec.gov/files/"
        "company_tickers_exchange.json"
    ) in workflow
    assert 'default: "2026-08-10T23:59:59Z"' in workflow


def _listing_facts(
    *,
    accession: str = "0000320193-25-000079",
    accepted_at: str = "2025-10-31T10:00:00Z",
    form: str = "10-K",
    context_id: str = "listing-common",
    symbol: str = "AAPL",
    exchange: str = "NASDAQ",
    security_title: str = "Common Stock, $0.00001 par value",
) -> pd.DataFrame:
    accession_path = accession.replace("-", "")
    common = {
        "cik": "0000320193",
        "accession": accession,
        "accepted_at": accepted_at,
        "form": form,
        "context_id": context_id,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            f"{accession_path}/aapl.htm"
        ),
    }
    return pd.DataFrame(
        [
            {**common, "concept": "dei:TradingSymbol", "value": symbol},
            {
                **common,
                "concept": "dei:SecurityExchangeName",
                "value": exchange,
            },
            {
                **common,
                "concept": "dei:Security12bTitle",
                "value": security_title,
            },
        ]
    )


def _current_universe(
    *,
    share_class_count: int = 1,
    exchange_family: str = "NASDAQ",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "ticker": "AAPL",
                "cik": "0000320193",
                "exchange_family": exchange_family,
                "issuer_share_class_count": share_class_count,
                "identity_available_at": "2026-08-07T20:06:32Z",
                "identity_source_url": (
                    "https://www.sec.gov/files/company_tickers_exchange.json"
                ),
            }
        ]
    )


def test_exch_switch_detects_causal_nasdaq_to_nyse_transition() -> None:
    facts = pd.concat(
        [
            _listing_facts(
                accession="0000320193-25-000100",
                accepted_at="2025-10-01T10:00:00Z",
                exchange="NASDAQ",
            ),
            _listing_facts(
                accession="0000320193-26-000010",
                accepted_at="2026-01-02T10:00:00Z",
                exchange="NYSE",
            ),
            _listing_facts(
                accession="0000320193-26-000050",
                accepted_at="2026-05-01T10:00:00Z",
                exchange="NYSE",
            ),
        ],
        ignore_index=True,
    )
    observations, rejected = extract_sec_listing_observations(
        facts,
        formation_at=FORMATION_AT,
    )
    current = _current_universe(exchange_family="NYSE")
    intervals, interval_rejections = build_sec_listing_intervals(
        observations,
        current,
        formation_at=FORMATION_AT,
    )

    result = calculate_sec_exch_switch_current(
        observations,
        intervals,
        current,
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T09:00:00Z",
    )

    assert rejected.empty
    assert not interval_rejections.empty
    assert result.loc[0, "value"] == 1.0
    assert result.loc[0, "current_usable"]
    assert result.loc[0, "transition_from"] == "NASDAQ"
    assert result.loc[0, "transition_to"] == "NYSE"
    assert result.loc[0, "formula_sha256"] == (
        "b6947fcace7abc2aa1d12f1f04bcd01a8151da7a8a4bfe15a9e56b8a294e6b5b"
    )
    assert not result.loc[0, "strict_score_eligible"]


def test_exch_switch_emits_zero_only_with_sufficient_identity_evidence() -> None:
    current_nasdaq = _current_universe(exchange_family="NASDAQ")
    empty_observations, _ = extract_sec_listing_observations(
        _listing_facts().iloc[0:0],
        formation_at=FORMATION_AT,
    )
    empty_intervals, _ = build_sec_listing_intervals(
        empty_observations,
        current_nasdaq,
        formation_at=FORMATION_AT,
    )
    nasdaq = calculate_sec_exch_switch_current(
        empty_observations,
        empty_intervals,
        current_nasdaq,
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T09:00:00Z",
    )
    assert nasdaq.loc[0, "value"] == 0.0

    current_nyse = _current_universe(exchange_family="NYSE")
    sparse_facts = _listing_facts(
        accession="0000320193-26-000070",
        accepted_at="2026-07-01T10:00:00Z",
        exchange="NYSE",
    )
    sparse_observations, _ = extract_sec_listing_observations(
        sparse_facts,
        formation_at=FORMATION_AT,
    )
    sparse_intervals, _ = build_sec_listing_intervals(
        sparse_observations,
        current_nyse,
        formation_at=FORMATION_AT,
    )
    nyse = calculate_sec_exch_switch_current(
        sparse_observations,
        sparse_intervals,
        current_nyse,
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T09:00:00Z",
    )
    assert pd.isna(nyse.loc[0, "value"])
    assert not nyse.loc[0, "current_usable"]
    assert nyse.loc[0, "reason_if_missing"] == (
        "exchange_history_not_corroborated_12_months"
    )

    covered_facts = pd.concat(
        [
            _listing_facts(
                accession="0000320193-25-000080",
                accepted_at="2025-08-01T10:00:00Z",
                exchange="NYSE",
            ),
            _listing_facts(
                accession="0000320193-25-000120",
                accepted_at="2025-12-01T10:00:00Z",
                exchange="NYSE",
            ),
            _listing_facts(
                accession="0000320193-26-000040",
                accepted_at="2026-04-01T10:00:00Z",
                exchange="NYSE",
            ),
        ],
        ignore_index=True,
    )
    covered_observations, _ = extract_sec_listing_observations(
        covered_facts,
        formation_at=FORMATION_AT,
    )
    covered_intervals, _ = build_sec_listing_intervals(
        covered_observations,
        current_nyse,
        formation_at=FORMATION_AT,
    )
    covered = calculate_sec_exch_switch_current(
        covered_observations,
        covered_intervals,
        current_nyse,
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T09:00:00Z",
    )
    assert covered.loc[0, "value"] == 0.0
    assert covered.loc[0, "current_usable"]


def test_notes_txt_normalizer_preserves_exact_context_and_bulk_provenance() -> None:
    submissions = pd.DataFrame(
        [
            {
                "adsh": "0000320193-25-000079",
                "cik": 320193,
                "form": "10-K",
                "accepted": "20251031100000",
                "instance": "aapl-20250927.htm",
            }
        ]
    )
    text_facts = pd.DataFrame(
        [
            {
                "adsh": "0000320193-25-000079",
                "tag": tag,
                "version": "dei/2025",
                "context": "listing-common",
                "iprx": 1,
                "value": value,
            }
            for tag, value in (
                ("TradingSymbol", "AAPL"),
                ("SecurityExchangeName", "NASDAQ"),
                ("Security12bTitle", "Common Stock, $0.00001 par value"),
            )
        ]
    )
    notes_url = (
        "https://www.sec.gov/files/dera/data/"
        "financial-statement-notes-data-sets/2025q4_notes.zip"
    )

    normalized = normalize_sec_notes_listing_facts(
        submissions,
        text_facts,
        dataset_source_url=notes_url,
        dataset_sha256="a" * 64,
    )
    observations, rejected = extract_sec_listing_observations(
        normalized,
        formation_at=FORMATION_AT,
    )

    assert normalized["context_id"].eq("listing-common").all()
    assert normalized["accepted_at"].astype(str).eq(
        "2025-10-31 10:00:00+00:00"
    ).all()
    assert normalized["source_url"].eq(
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000079/aapl-20250927.htm"
    ).all()
    assert normalized["transport_source_url"].eq(notes_url).all()
    assert normalized["transport_sha256"].eq("a" * 64).all()
    assert rejected.empty
    assert observations["trading_symbol"].tolist() == ["AAPL"]


def test_notes_txt_normalizer_rejects_unsafe_or_unverifiable_inputs() -> None:
    submissions = pd.DataFrame(
        [
            {
                "adsh": "0000320193-25-000079",
                "cik": 320193,
                "form": "10-K",
                "accepted": "20251031100000",
                "instance": "../unsafe.htm",
            }
        ]
    )
    text_facts = pd.DataFrame(
        [
            {
                "adsh": "0000320193-25-000079",
                "tag": "TradingSymbol",
                "version": "dei/2025",
                "context": "listing-common",
                "iprx": 1,
                "value": "AAPL",
            }
        ]
    )

    for source_url, source_hash in (
        (
            "https://example.com/2025q4_notes.zip",
            "a" * 64,
        ),
        (
            "https://www.sec.gov/files/dera/data/"
            "financial-statement-notes-data-sets/2025q4_notes.zip",
            "not-a-hash",
        ),
    ):
        with pytest.raises(ValueError, match="Notes dataset"):
            normalize_sec_notes_listing_facts(
                submissions,
                text_facts,
                dataset_source_url=source_url,
                dataset_sha256=source_hash,
            )

    with pytest.raises(ValueError, match="unsafe SEC filing instance"):
        normalize_sec_notes_listing_facts(
            submissions,
            text_facts,
            dataset_source_url=(
                "https://www.sec.gov/files/dera/data/"
                "financial-statement-notes-data-sets/2025q4_notes.zip"
            ),
            dataset_sha256="a" * 64,
        )


def test_extract_listing_observation_requires_three_facts_in_same_context() -> None:
    facts = _listing_facts()

    observations, rejected = extract_sec_listing_observations(
        facts,
        formation_at=FORMATION_AT,
    )

    assert rejected.empty
    assert observations[
        [
            "cik",
            "accession",
            "form",
            "trading_symbol",
            "ticker_key",
            "exchange_family",
            "security_title_key",
        ]
    ].to_dict(orient="records") == [
        {
            "cik": "0000320193",
            "accession": "0000320193-25-000079",
            "form": "10-K",
            "trading_symbol": "AAPL",
            "ticker_key": "AAPL",
            "exchange_family": "NASDAQ",
            "security_title_key": "COMMONSTOCK000001PARVALUE",
        }
    ]
    assert observations.loc[0, "identity_quality"] == (
        "sec_filing_context_cik_class_ticker_exchange_observation"
    )


def test_extract_listing_observation_rejects_missing_or_conflicting_facts() -> None:
    missing_title = _listing_facts().loc[
        lambda frame: ~frame["concept"].eq("dei:Security12bTitle")
    ]
    conflicting_symbol = pd.concat(
        [
            _listing_facts(),
            _listing_facts().iloc[[0]].assign(value="AAPLX"),
        ],
        ignore_index=True,
    )

    missing_observations, missing_rejected = extract_sec_listing_observations(
        missing_title,
        formation_at=FORMATION_AT,
    )
    conflict_observations, conflict_rejected = extract_sec_listing_observations(
        conflicting_symbol,
        formation_at=FORMATION_AT,
    )

    assert missing_observations.empty
    assert missing_rejected["reason_if_rejected"].tolist() == [
        "missing_listing_fact:Security12bTitle"
    ]
    assert conflict_observations.empty
    assert conflict_rejected["reason_if_rejected"].tolist() == [
        "conflicting_or_duplicate_listing_fact:TradingSymbol"
    ]


def test_extract_listing_observation_rejects_future_amended_and_unofficial_rows() -> None:
    future = _listing_facts(accepted_at="2026-08-10T00:00:00Z")
    amended = _listing_facts(form="10-Q/A")
    unofficial = _listing_facts().assign(
        source_url="https://example.com/copied-filing.html"
    )

    for facts, expected_reason in (
        (future, "accepted_after_formation"),
        (amended, "unsupported_or_amended_periodic_form"),
        (unofficial, "unofficial_sec_archive_source"),
    ):
        observations, rejected = extract_sec_listing_observations(
            facts,
            formation_at=FORMATION_AT,
        )
        assert observations.empty
        assert rejected["reason_if_rejected"].tolist() == [expected_reason]


def test_extract_listing_observation_rejects_malformed_or_missing_timestamp() -> None:
    for accepted_at in ("not-a-date", pd.NA):
        observations, rejected = extract_sec_listing_observations(
            _listing_facts().assign(accepted_at=accepted_at),
            formation_at=FORMATION_AT,
        )

        assert observations.empty
        assert rejected["reason_if_rejected"].tolist() == [
            "invalid_accepted_at"
        ]


def test_extract_listing_observation_rejects_wrong_cik_or_accession_path() -> None:
    wrong_archive_member = _listing_facts().assign(
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/789019/"
            "000078901925000079/msft.htm"
        )
    )

    observations, rejected = extract_sec_listing_observations(
        wrong_archive_member,
        formation_at=FORMATION_AT,
    )

    assert observations.empty
    assert rejected["reason_if_rejected"].tolist() == [
        "sec_archive_identity_path_mismatch"
    ]


def test_intervals_require_adjacent_matching_filings_and_single_current_class() -> None:
    facts = pd.concat(
        [
            _listing_facts(),
            _listing_facts(
                accession="0000320193-26-000006",
                accepted_at="2026-01-30T10:00:00Z",
                form="10-Q",
            ),
            _listing_facts(
                accession="0000320193-26-000042",
                accepted_at="2026-05-01T10:00:00Z",
                form="10-Q",
            ),
        ],
        ignore_index=True,
    )
    observations, rejected_facts = extract_sec_listing_observations(
        facts,
        formation_at=FORMATION_AT,
    )

    intervals, rejected = build_sec_listing_intervals(
        observations,
        _current_universe(),
        formation_at=FORMATION_AT,
    )
    multiclass_intervals, multiclass_rejected = build_sec_listing_intervals(
        observations,
        _current_universe(share_class_count=2),
        formation_at=FORMATION_AT,
    )

    assert rejected_facts.empty
    assert rejected.empty
    assert intervals[
        ["valid_from", "valid_through", "start_accession", "end_evidence"]
    ].astype(str).to_dict(orient="records") == [
        {
            "valid_from": "2025-10-31",
            "valid_through": "2026-01-29",
            "start_accession": "0000320193-25-000079",
            "end_evidence": "0000320193-26-000006",
        },
        {
            "valid_from": "2026-01-30",
            "valid_through": "2026-04-30",
            "start_accession": "0000320193-26-000006",
            "end_evidence": "0000320193-26-000042",
        },
        {
            "valid_from": "2026-05-01",
            "valid_through": "2026-08-07",
            "start_accession": "0000320193-26-000042",
            "end_evidence": "current_security_master_endpoint",
        },
    ]
    assert not intervals["historical_ticker_interval_verified"].any()
    assert not intervals["strict_score_eligible"].any()
    assert multiclass_intervals.empty
    assert multiclass_rejected["reason_if_rejected"].tolist() == [
        "current_issuer_has_multiple_share_classes"
    ]


def test_intervals_reject_non_integer_single_class_claim() -> None:
    observations, _ = extract_sec_listing_observations(
        _listing_facts(),
        formation_at=FORMATION_AT,
    )

    intervals, rejected = build_sec_listing_intervals(
        observations,
        _current_universe().assign(issuer_share_class_count=1.5),
        formation_at=FORMATION_AT,
    )

    assert intervals.empty
    assert rejected["reason_if_rejected"].tolist() == [
        "current_issuer_has_multiple_share_classes"
    ]


def test_intervals_do_not_bridge_symbol_changes_or_long_filing_gaps() -> None:
    facts = pd.concat(
        [
            _listing_facts(),
            _listing_facts(
                accession="0000320193-26-000006",
                accepted_at="2026-01-30T10:00:00Z",
                form="10-Q",
            ),
            _listing_facts(
                accession="0000320193-26-000020",
                accepted_at="2026-03-01T10:00:00Z",
                form="10-Q",
                symbol="AAPLX",
            ),
            _listing_facts(
                accession="0000320193-26-000079",
                accepted_at="2026-08-01T10:00:00Z",
                form="10-Q",
            ),
        ],
        ignore_index=True,
    )
    observations, _ = extract_sec_listing_observations(
        facts,
        formation_at=FORMATION_AT,
    )

    intervals, rejected = build_sec_listing_intervals(
        observations,
        _current_universe(),
        formation_at=FORMATION_AT,
    )

    assert intervals[["valid_from", "valid_through"]].astype(str).to_dict(
        orient="records"
    ) == [
        {"valid_from": "2025-10-31", "valid_through": "2026-01-29"},
        {"valid_from": "2026-08-01", "valid_through": "2026-08-07"},
    ]
    assert set(rejected["reason_if_rejected"]) == {
        "listing_identity_disagrees_with_current_security",
        "filing_gap_exceeds_160_days",
    }


def test_intervals_reject_future_or_unofficial_current_identity_endpoint() -> None:
    observations, _ = extract_sec_listing_observations(
        _listing_facts(),
        formation_at=FORMATION_AT,
    )
    future = _current_universe().assign(
        identity_available_at="2026-08-10T00:00:00Z"
    )
    unofficial = _current_universe().assign(
        identity_source_url="https://example.com/company_tickers_exchange.json"
    )

    future_intervals, future_rejected = build_sec_listing_intervals(
        observations,
        future,
        formation_at=FORMATION_AT,
    )
    unofficial_intervals, unofficial_rejected = build_sec_listing_intervals(
        observations,
        unofficial,
        formation_at=FORMATION_AT,
    )

    assert future_intervals.empty
    assert future_rejected["reason_if_rejected"].tolist() == [
        "current_identity_available_after_formation_or_invalid"
    ]
    assert unofficial_intervals.empty
    assert unofficial_rejected["reason_if_rejected"].tolist() == [
        "current_identity_source_is_not_official_sec"
    ]


def test_market_bars_require_exact_identity_and_a_corroborated_date() -> None:
    facts = pd.concat(
        [
            _listing_facts(),
            _listing_facts(
                accession="0000320193-26-000006",
                accepted_at="2026-01-30T10:00:00Z",
                form="10-Q",
            ),
        ],
        ignore_index=True,
    )
    observations, _ = extract_sec_listing_observations(
        facts,
        formation_at=FORMATION_AT,
    )
    intervals, _ = build_sec_listing_intervals(
        observations,
        _current_universe(),
        formation_at=FORMATION_AT,
    )
    bars = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "cik": "0000320193",
                "ticker": "AAPL",
                "exchange_family": "NASDAQ",
                "date": "2025-11-03",
                "close": 270.0,
            },
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "cik": "0000320193",
                "ticker": "AAPL",
                "exchange_family": "NASDAQ",
                "date": "2025-10-30",
                "close": 269.0,
            },
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "cik": "0000789019",
                "ticker": "MSFT",
                "exchange_family": "NASDAQ",
                "date": "2025-11-04",
                "close": 500.0,
            },
        ]
    )

    accepted, rejected = filter_market_bars_by_sec_identity(bars, intervals)

    assert accepted[["date", "historical_identity_corroborated"]].astype(
        {"date": str}
    ).to_dict(orient="records") == [
        {"date": "2025-11-03", "historical_identity_corroborated": True}
    ]
    assert accepted["identity_quality"].eq(
        "sec_filing_endpoints_corroborated_non_permno"
    ).all()
    assert not accepted["historical_ticker_interval_verified"].any()
    assert not accepted["strict_score_eligible"].any()
    assert rejected["reason_if_rejected"].tolist() == [
        "outside_sec_corroborated_identity_interval",
        "bar_identity_disagrees_with_sec_interval",
    ]
