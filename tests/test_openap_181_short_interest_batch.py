from __future__ import annotations

from importlib import import_module
import json

import pandas as pd
import pytest


def _module():
    return import_module("aurora.research.openap_181.short_interest_batch")


def test_short_interest_sources_and_formulas_are_pinned():
    module = _module()

    assert module.FINRA_FILES_URL == (
        "https://www.finra.org/finra-data/browse-catalog/"
        "equity-short-interest/files"
    )
    assert module.FINRA_ABOUT_URL == (
        "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
    )
    assert module.FINRA_GLOSSARY_URL == (
        "https://www.finra.org/finra-data/browse-catalog/"
        "equity-short-interest/glossary"
    )
    assert module.FINRA_SCHEDULE_URL == (
        "https://www.finra.org/filing-reporting/regulatory-filing-systems/"
        "short-interest"
    )
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert module.OPENAP_FORMULA_SOURCES == {
        "ShortInterest": {
            "path": "Signals/pyCode/Predictors/ShortInterest.py",
            "sha256": "25baaf9fd432a4b4805e57cddfb7cb7882eddf8ea27d3cde5b502c304d932b94",
        },
        "IO_ShortInterest": {
            "path": "Signals/pyCode/Predictors/IO_ShortInterest.py",
            "sha256": "716310d258802f2a9bc5cf3f02ae012b3e59908a932c75dd5a0701833e222b26",
        },
        "Recomm_ShortInterest": {
            "path": "Signals/pyCode/Predictors/Recomm_ShortInterest.py",
            "sha256": "154a287aa7b4a16ac5af0990b7d1d7712d8bd01fe98f93e250405c470e0f772e",
        },
    }


def test_finra_file_link_extractor_accepts_only_https_finra_cdn_links():
    module = _module()
    html = """
    <a href="https://cdn.finra.org/equity/short-interest/2026-07-15.txt">latest</a>
    <a href="https://cdn.finra.org/equity/short-interest/2026-07-15.txt">duplicate</a>
    <a href="http://cdn.finra.org/equity/short-interest/insecure.txt">insecure</a>
    <a href="https://example.com/not-finra.txt">foreign</a>
    """

    assert module.extract_finra_file_links(html) == (
        "https://cdn.finra.org/equity/short-interest/2026-07-15.txt",
    )
    with pytest.raises(ValueError, match="FINRA short-interest file"):
        module.extract_finra_file_links("<html>no files</html>")

    assert module.extract_finra_file_links(
        '<a href="https://cdn.finra.org/equity/otcmarket/biweekly/'
        'shrt20260715.csv">official current pattern</a>'
    ) == (
        "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260715.csv",
    )


def test_finra_link_selection_excludes_not_yet_published_settlements():
    module = _module()
    links = (
        "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260715.csv",
        "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260731.csv",
    )
    schedule = pd.DataFrame(
        {
            "settlement_date": pd.to_datetime(
                ["2026-07-15", "2026-07-31"], utc=True
            ),
            "publication_date": pd.to_datetime(
                ["2026-07-24", "2026-08-11"], utc=True
            ),
        }
    )

    selected = module.select_latest_causal_finra_link(
        links,
        schedule,
        formation_at="2026-08-09T23:59:59Z",
    )

    assert selected == links[0]


def test_finra_document_contract_uses_visible_text_across_markup_and_entities():
    module = _module()
    html = (
        "<p>Prior to June <strong>2021</strong>, positions were OTC only and did "
        "not reflect <span>exchange&#x2D;listed</span> securities.</p>"
    )

    visible = module.extract_visible_text(html)

    assert "june 2021" in visible
    assert "otc" in visible
    assert "exchange-listed" in visible


def test_finra_publication_schedule_parser_preserves_point_in_time_dates():
    module = _module()
    html = """
    <h2>2026 Short Interest Reporting Dates</h2>
    <table>
      <thead>
        <tr><th>Settlement Date</th><th>Due Date</th><th>Publication Date</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>July 15<br>(Wednesday)</td>
          <td>July 17 - 6:00 p.m.<br>(Friday)</td>
          <td>July 24<br>(Friday)</td>
        </tr>
        <tr>
          <td>December 31<br>(Thursday)</td>
          <td>January 5 - 6:00 p.m.<br>(Monday)</td>
          <td>January 12<br>(Monday)</td>
        </tr>
      </tbody>
    </table>
    """

    schedule = module.parse_finra_publication_schedule(html)

    assert schedule["settlement_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-15",
        "2026-12-31",
    ]
    assert schedule["publication_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-24",
        "2027-01-12",
    ]
    assert str(schedule["publication_date"].dt.tz) == "UTC"


def test_finra_pipe_file_parser_and_source_summary_are_fail_closed():
    module = _module()
    text = "\n".join(
        (
            "Date|Issue Name|Symbol|Market|Current Short|Previous Short|Revision Flag",
            "2026-07-15|Issuer A|AAA|NYSE|100|90|",
            "2026-07-15|Issuer B|BBB|NASDAQ|200|180|Y",
            "2026-06-30|Issuer C|CCC|OTC|300|250|",
        )
    )

    rows = module.parse_finra_short_interest_text(text)
    summary = module.summarize_finra_short_interest_rows([rows])

    assert list(rows.columns) == [
        "settlement_date",
        "issue_name",
        "symbol",
        "market",
        "current_short",
        "previous_short",
        "revision_flag",
    ]
    assert summary == {
        "rows": 3,
        "unique_symbols": 3,
        "listed_rows": 2,
        "otc_rows": 1,
        "missing_current_short": 0,
        "revision_flagged_rows": 1,
        "first_settlement_date": "2026-06-30",
        "last_settlement_date": "2026-07-15",
        "markets": ["NASDAQ", "NYSE", "OTC"],
        "signal_coverage_measured": False,
    }

    with pytest.raises(ValueError, match="missing columns"):
        module.summarize_finra_short_interest_rows([pd.DataFrame({"Symbol": ["AAA"]})])


def test_finra_current_csv_api_headers_map_to_canonical_source_schema():
    module = _module()
    text = "\n".join(
        (
            "settlementDate,issueName,issueSymbolIdentifier,marketCategoryCode,"
            "currentShortShareNumber,previousShortShareNumber,revisionFlag",
            "2026-07-15,Issuer A,AAA,N,100,90,",
        )
    )

    rows = module.parse_finra_short_interest_text(text)

    assert list(rows.columns) == [
        "settlement_date",
        "issue_name",
        "symbol",
        "market",
        "current_short",
        "previous_short",
        "revision_flag",
    ]
    assert rows.loc[0, "symbol"] == "AAA"
    assert rows.loc[0, "market"] == "N"

    current_file = "\n".join(
        (
            "settlementDate,issueName,symbolCode,marketClassCode,"
            "issuerServicesGroupExchangeCode,currentShort,previousShort,revisionFlag",
            "2026-07-15,Issuer B,BBB,Listed,R,200,180,",
            "2026-07-15,Issuer C,CCC,OTC,S,300,250,",
        )
    )
    current_rows = module.parse_finra_short_interest_text(current_file)
    summary = module.summarize_finra_short_interest_rows([current_rows])

    assert current_rows["symbol"].tolist() == ["BBB", "CCC"]
    assert current_rows["market"].tolist() == ["R", "S"]
    assert summary["listed_rows"] == 1
    assert summary["otc_rows"] == 1


def test_finra_short_interest_current_is_causal_and_fails_closed_on_identity():
    module = _module()
    finra = pd.DataFrame(
        [
            {
                "settlement_date": "2026-07-15",
                "issue_name": "Issuer A",
                "symbol": "AAA",
                "market": "N",
                "current_short": "100",
                "previous_short": "90",
                "revision_flag": "",
            },
            {
                "settlement_date": "2026-07-15",
                "issue_name": "Issuer B",
                "symbol": "BBB",
                "market": "R",
                "current_short": "200",
                "previous_short": "180",
                "revision_flag": "",
            },
            {
                "settlement_date": "2026-07-15",
                "issue_name": "Ambiguous issuer",
                "symbol": "DUP",
                "market": "N",
                "current_short": "300",
                "previous_short": "250",
                "revision_flag": "",
            },
            {
                "settlement_date": "2026-07-31",
                "issue_name": "Future publication",
                "symbol": "FUT",
                "market": "N",
                "current_short": "400",
                "previous_short": "350",
                "revision_flag": "",
            },
            {
                "settlement_date": "2026-07-15",
                "issue_name": "OTC issuer",
                "symbol": "OTC",
                "market": "S",
                "current_short": "500",
                "previous_short": "450",
                "revision_flag": "",
            },
        ]
    )
    schedule = pd.DataFrame(
        {
            "settlement_date": pd.to_datetime(
                ["2026-07-15", "2026-07-31"], utc=True
            ),
            "publication_date": pd.to_datetime(
                ["2026-07-24", "2026-08-11"], utc=True
            ),
        }
    )
    facts: list[dict[str, object]] = []
    statuses: list[dict[str, object]] = []
    identities = ((1, "AAA", 1000.0), (2, "BBB", 4000.0), (3, "DUP", 1000.0))
    for cik, symbol, shares in identities:
        for surface in ("companyfacts", "submissions"):
            statuses.append(
                {"cik": cik, "symbol": symbol, "surface": surface, "status": "ok"}
            )
        facts.append(
            {
                "cik": cik,
                "taxonomy": "dei",
                "tag": "EntityCommonStockSharesOutstanding",
                "unit": "shares",
                "value": shares,
                "period_start": "",
                "period_end": "2026-06-30",
                "form": "10-Q",
                "filed": "2026-07-01",
                "accession_number": f"{cik}-current",
                "available_at": "2026-07-01T12:00:00Z",
            }
        )
    for cik in (4,):
        for surface in ("companyfacts", "submissions"):
            statuses.append(
                {"cik": cik, "symbol": "DUP", "surface": surface, "status": "ok"}
            )
        facts.append(
            {
                "cik": cik,
                "taxonomy": "dei",
                "tag": "EntityCommonStockSharesOutstanding",
                "unit": "shares",
                "value": 2000.0,
                "period_start": "",
                "period_end": "2026-06-30",
                "form": "10-Q",
                "filed": "2026-07-01",
                "accession_number": f"{cik}-current",
                "available_at": "2026-07-01T12:00:00Z",
            }
        )
    facts.append(
        {
            **facts[0],
            "value": 2000.0,
            "period_end": "2026-07-31",
            "filed": "2026-08-10",
            "accession_number": "1-future",
            "available_at": "2026-08-10T12:00:00Z",
        }
    )

    values = module.calculate_finra_short_interest_current(
        finra,
        pd.DataFrame(facts),
        pd.DataFrame(statuses),
        schedule,
        formation_at="2026-08-09T23:59:59Z",
        retrieved_at="2026-08-10T09:00:00Z",
        finra_source_url=(
            "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260715.csv"
        ),
    )

    assert values["ticker"].tolist() == ["AAA", "BBB"]
    assert values["value"].tolist() == pytest.approx([0.1, 0.05])
    assert values["signal"].eq("ShortInterest").all()
    assert pd.to_datetime(values["period_end"]).dt.strftime("%Y-%m-%d").eq(
        "2026-07-15"
    ).all()
    assert pd.to_datetime(values["available_at"]).dt.strftime("%Y-%m-%d").eq(
        "2026-07-24"
    ).all()
    assert values["fidelity_class"].eq("unvalidated_proxy").all()
    assert values["current_usable"].all()
    assert values["source_id"].eq("finra_equity_short_interest|sec_edgar").all()
    assert values["formula_id"].eq(
        "openap_shortinterest_finra_sec_current_proxy"
    ).all()


def _io_current_short_interest() -> pd.DataFrame:
    rows = []
    for cik, ticker, value in (
        (1, "AAA", 0.01),
        (2, "BBB", 0.02),
        (3, "CCC", 0.03),
        (4, "DDD", 0.10),
    ):
        rows.append(
            {
                "security_id": f"US-SEC-{cik:010d}-{ticker}",
                "ticker": ticker,
                "cik": f"{cik:010d}",
                "signal": "ShortInterest",
                "formation_at": "2026-08-09T23:59:59+00:00",
                "period_end": "2026-07-15T00:00:00+00:00",
                "filed_at": "2026-07-01T12:00:00+00:00",
                "available_at": "2026-07-24T00:00:00+00:00",
                "retrieved_at": "2026-08-09T20:00:00+00:00",
                "value": value,
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "finra_equity_short_interest|sec_edgar",
                "source_url": (
                    "https://cdn.finra.org/equity/otcmarket/"
                    "biweekly/shrt20260715.csv|https://data.sec.gov/api/xbrl/"
                    f"companyfacts/CIK{cik:010d}.json"
                ),
                "formula_id": "openap_shortinterest_finra_sec_current_proxy",
                "formula_sha256": "25baaf9fd432a4b4805e57cddfb7cb7882eddf8ea27d3cde5b502c304d932b94",
                "observation_count": 2,
                "reason_if_missing": "",
                "caveat": "reconstructed current short interest",
            }
        )
    return pd.DataFrame(rows)


def _io_status() -> pd.DataFrame:
    rows = []
    for cik, ticker in ((1, "AAA"), (2, "BBB"), (3, "CCC"), (4, "DDD")):
        for surface in ("companyfacts", "submissions"):
            rows.append(
                {
                    "cik": cik,
                    "symbol": ticker,
                    "surface": surface,
                    "status": "ok",
                }
            )
    return pd.DataFrame(rows)


def _io_companyfacts() -> pd.DataFrame:
    rows = []
    for cik, ticker in ((1, "AAA"), (2, "BBB"), (3, "CCC"), (4, "DDD")):
        rows.append(
            {
                "cik": cik,
                "entity_name": f"{ticker} INC",
                "taxonomy": "dei",
                "tag": "EntityCommonStockSharesOutstanding",
                "unit": "shares",
                "value": 1_000.0,
                "period_start": "",
                "period_end": "2026-03-31",
                "form": "10-Q",
                "filed": "2026-04-20",
                "accession_number": f"{cik}-shares",
                "available_at": "2026-04-20T12:00:00Z",
                "symbol": ticker,
            }
        )
    return pd.DataFrame(rows)


def test_io_short_interest_uses_full_p99_universe_and_latest_complete_13f_period():
    module = _module()
    filings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
            },
            {
                "accession_number": "q2-early-manager",
                "manager_cik": "9001",
                "filing_date": "2026-07-10",
                "report_period": "2026-06-30",
            },
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
                "cusip": "123456789",
                "shares_held": 250.0,
                "issuer_name": "DDD INC",
                "title_of_class": "COM",
            },
            {
                "accession_number": "q2-early-manager",
                "manager_cik": "9001",
                "filing_date": "2026-07-10",
                "report_period": "2026-06-30",
                "cusip": "123456789",
                "shares_held": 900.0,
                "issuer_name": "DDD INC",
                "title_of_class": "COM",
            },
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "cusip": "123456789",
                "ticker": "DDD",
                "mapping_status": "mapped_unique",
                "candidates_json": json.dumps(
                    [
                        {
                            "ticker": "DDD",
                            "marketSector": "Equity",
                            "securityType2": "Common Stock",
                            "exchCode": "US",
                            "shareClassFIGI": "BBG001DDD001",
                        }
                    ]
                ),
            }
        ]
    )

    values = module.calculate_finra_io_short_interest_current(
        _io_current_short_interest(),
        _io_companyfacts(),
        _io_status(),
        filings,
        holdings,
        mapping,
        formation_at="2026-08-09T23:59:59Z",
        retrieved_at="2026-08-09T20:00:00Z",
    )

    assert values["ticker"].tolist() == ["DDD"]
    assert values["value"].tolist() == pytest.approx([25.0])
    assert values["signal"].eq("IO_ShortInterest").all()
    assert values["fidelity_class"].eq("reconstructed").all()
    assert values["current_usable"].all()
    assert values["source_id"].eq(
        "finra_equity_short_interest|sec_edgar|sec_13f|openfigi_public"
    ).all()
    assert values["formula_id"].eq(
        "openap_io_shortinterest_finra_sec13f_current_reconstruction"
    ).all()
    assert values["formula_sha256"].eq(
        "716310d258802f2a9bc5cf3f02ae012b3e59908a932c75dd5a0701833e222b26"
    ).all()
    assert pd.to_datetime(values["available_at"], utc=True).le(
        pd.Timestamp("2026-08-09T23:59:59Z")
    ).all()


def test_io_short_interest_does_not_recompute_p99_on_only_mapped_holdings():
    module = _module()
    filings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
            }
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
                "cusip": "987654321",
                "shares_held": 300.0,
                "issuer_name": "CCC INC",
                "title_of_class": "COM",
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "cusip": "987654321",
                "ticker": "CCC",
                "mapping_status": "mapped_unique",
                "candidates_json": json.dumps(
                    [
                        {
                            "ticker": "CCC",
                            "marketSector": "Equity",
                            "securityType2": "Common Stock",
                            "exchCode": "US",
                            "shareClassFIGI": "BBG001CCC001",
                        }
                    ]
                ),
            }
        ]
    )

    values = module.calculate_finra_io_short_interest_current(
        _io_current_short_interest(),
        _io_companyfacts(),
        _io_status(),
        filings,
        holdings,
        mapping,
        formation_at="2026-08-09T23:59:59Z",
        retrieved_at="2026-08-09T20:00:00Z",
    )

    # DDD determines the full-universe 99th percentile.  It has no mapped 13F
    # ownership, so fail closed instead of selecting CCC or inventing zero.
    assert values.empty
    assert list(values.columns) == list(module._CURRENT_OUTPUT_COLUMNS)


def test_io_short_interest_rejects_ambiguous_mapping_and_future_share_denominator():
    module = _module()
    filings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
            }
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
                "cusip": "123456789",
                "shares_held": 250.0,
                "issuer_name": "DDD INC",
                "title_of_class": "COM",
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "cusip": "123456789",
                "ticker": "DDD",
                "mapping_status": "ambiguous",
                "candidates_json": "[]",
            }
        ]
    )
    facts = _io_companyfacts()
    facts.loc[facts["cik"].eq(4), "available_at"] = "2026-08-10T12:00:00Z"

    values = module.calculate_finra_io_short_interest_current(
        _io_current_short_interest(),
        facts,
        _io_status(),
        filings,
        holdings,
        mapping,
        formation_at="2026-08-09T23:59:59Z",
        retrieved_at="2026-08-09T20:00:00Z",
    )

    assert values.empty


@pytest.mark.parametrize(
    ("issuer_name", "figis", "exchange_code"),
    [
        ("UNRELATED ISSUER INC", ["BBG001DDD001"], "US"),
        ("DDD INC", ["BBG001DDD001", "BBG001DDD002"], "US"),
        ("DDD INC", ["BBG001DDD001"], "CA"),
    ],
)
def test_io_short_interest_requires_matching_issuer_and_unique_share_class_figi(
    issuer_name: str,
    figis: list[str],
    exchange_code: str,
):
    module = _module()
    filings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
            }
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "accession_number": "q1-manager",
                "manager_cik": "9001",
                "filing_date": "2026-05-15",
                "report_period": "2026-03-31",
                "cusip": "123456789",
                "shares_held": 250.0,
                "issuer_name": issuer_name,
                "title_of_class": "COM",
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "cusip": "123456789",
                "ticker": "DDD",
                "mapping_status": "mapped_unique",
                "candidates_json": json.dumps(
                    [
                        {
                            "ticker": "DDD",
                            "marketSector": "Equity",
                            "securityType2": "Common Stock",
                            "exchCode": exchange_code,
                            "shareClassFIGI": figi,
                        }
                        for figi in figis
                    ]
                ),
            }
        ]
    )

    values = module.calculate_finra_io_short_interest_current(
        _io_current_short_interest(),
        _io_companyfacts(),
        _io_status(),
        filings,
        holdings,
        mapping,
        formation_at="2026-08-09T23:59:59Z",
        retrieved_at="2026-08-09T20:00:00Z",
    )

    assert values.empty


def test_short_interest_evidence_records_three_concrete_blockers_without_promotion():
    module = _module()
    probe = {
        "formula_sources_verified": True,
        "finra_files_page_verified": True,
        "finra_about_page_verified": True,
        "finra_glossary_verified": True,
        "finra_schedule_verified": True,
        "latest_public_file_verified": True,
        "listed_history_start": "2021-06-01",
        "historical_revisions_available": False,
        "raw_redistribution_authorized": False,
        "raw_files_in_artifact": False,
    }

    evidence = module.build_short_interest_batch_evidence(
        probe,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-short-interest-source-probe-results",
        implementation_commit="1" * 40,
    ).set_index("signal")

    assert set(evidence.index) == {
        "ShortInterest",
        "IO_ShortInterest",
        "Recomm_ShortInterest",
    }
    assert evidence["formula_implemented"].all()
    assert not evidence["data_pipeline_implemented"].any()
    assert not evidence["point_in_time_verified"].any()
    assert not evidence["identity_verified"].any()
    assert not evidence["coverage_measured"].any()
    assert not evidence["fidelity_measured"].any()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["coverage_result"].eq("not_measured").all()
    assert evidence["fidelity_result"].eq("not_measured").all()
    assert "exact_monthly_crsp_shrout" in evidence.loc[
        "ShortInterest", "blocking_reason"
    ]
    assert "exact_tr_13f_instown_perc" in evidence.loc[
        "IO_ShortInterest", "blocking_reason"
    ]
    assert "exact_ibes_individual_recommendation_history" in evidence.loc[
        "Recomm_ShortInterest", "blocking_reason"
    ]


def test_short_interest_evidence_rejects_incomplete_or_promotional_probe():
    module = _module()
    base = {
        "formula_sources_verified": True,
        "finra_files_page_verified": True,
        "finra_about_page_verified": True,
        "finra_glossary_verified": True,
        "finra_schedule_verified": True,
        "latest_public_file_verified": True,
        "listed_history_start": "2021-06-01",
        "historical_revisions_available": False,
        "raw_redistribution_authorized": False,
        "raw_files_in_artifact": False,
    }
    for field in (
        "formula_sources_verified",
        "finra_files_page_verified",
        "finra_about_page_verified",
        "finra_glossary_verified",
        "finra_schedule_verified",
        "latest_public_file_verified",
    ):
        probe = dict(base, **{field: False})
        with pytest.raises(ValueError, match="short-interest probe"):
            module.build_short_interest_batch_evidence(
                probe,
                evidence_run_url="https://github.com/example/aurora/actions/runs/123",
                evidence_artifact="artifact",
                implementation_commit="1" * 40,
            )

    with pytest.raises(ValueError, match="short-interest probe"):
        module.build_short_interest_batch_evidence(
            dict(base, raw_files_in_artifact=True),
            evidence_run_url="https://github.com/example/aurora/actions/runs/123",
            evidence_artifact="artifact",
            implementation_commit="1" * 40,
        )
