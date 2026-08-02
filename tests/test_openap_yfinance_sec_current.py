from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from aurora.research.openap_current_score import (
    EXPECTED_PREDICTORS,
    FeatureValue,
    OpenAPDataError,
    assemble_feature_table,
    build_redundancy_groups,
    calculate_accounting_features,
    calculate_aggregate_scores,
    calculate_price_features,
    calculate_scores,
    coverage_report,
    latest_sec_concepts,
    latest_sec_concept_inputs,
    select_strict_predictors,
)
from scripts.run_openap_yfinance_sec_current import (
    _analyst_features,
    _classify_security_eligibility,
    _companyfacts_rows,
    _hashes_by_chunk,
    _json_from_jina_text,
    _sec_exchange_csv_rows,
    _select_chunk_rows,
)


def _metadata(rows: int = EXPECTED_PREDICTORS) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signalname": [f"signal_{index:03d}" for index in range(rows)],
            "Cat.Signal": "Predictor",
            "tstat": 2.5,
            "T.Stat": 2.2,
            "Sign": 1.0,
            "portperiod": 1.0,
            "Cat.Data": "Price",
            "Cat.Economic": "Test",
            "Signal.Rep.Quality": "1_good",
        }
    )


def test_strict_selection_requires_exactly_185() -> None:
    selected = select_strict_predictors(_metadata())
    assert len(selected) == 185
    with pytest.raises(OpenAPDataError):
        select_strict_predictors(_metadata(184))


def test_redundancy_groups_catch_positive_and_mirror_signals() -> None:
    metadata = _metadata(3)
    metadata.loc[:, "signalname"] = ["a", "b", "c"]
    metadata.loc[:, "Sign"] = [1.0, 1.0, -1.0]
    returns = pd.DataFrame(
        {
            "a": np.arange(100, dtype=float),
            "b": np.arange(100, dtype=float) * 2,
            "c": np.arange(100, dtype=float) * -3,
        }
    )
    groups = build_redundancy_groups(metadata, returns, threshold=0.8, minimum_overlap=60)
    assert groups["redundancy_group"].nunique() == 1
    assert set(groups["signalname"]) == {"a", "b", "c"}


def test_sec_concepts_ignore_facts_not_yet_available() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets"],
            "value": [100.0, 999.0],
            "period_end": ["2024-12-31", "2025-12-31"],
            "available_at": ["2025-02-01T12:00:00Z", "2026-02-01T12:00:00Z"],
        }
    )
    concepts = latest_sec_concepts(facts, pd.Timestamp("2025-06-01"))
    assert concepts["assets"][0] == 100.0
    assert 999.0 not in concepts["assets"]


def test_sec_concepts_prefer_comparable_annual_facts() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Revenues", "Revenues", "Revenues"],
            "value": [25.0, 100.0, 80.0],
            "period_start": ["2024-01-01", "2024-01-01", "2023-01-01"],
            "period_end": ["2024-03-31", "2024-12-31", "2023-12-31"],
            "available_at": ["2024-05-01", "2025-02-01", "2024-02-01"],
            "form": ["10-Q", "10-K", "10-K"],
            "fp": ["Q1", "FY", "FY"],
        }
    )

    concepts = latest_sec_concepts(facts, pd.Timestamp("2025-06-01"))

    assert concepts["revenue"][:2] == [100.0, 80.0]


def test_sec_concept_inputs_preserve_reconstruction_provenance() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets"],
            "taxonomy": ["us-gaap", "us-gaap"],
            "unit": ["USD", "USD"],
            "value": [100.0, 80.0],
            "period_end": ["2024-12-31", "2023-12-31"],
            "available_at": ["2025-02-01", "2024-02-01"],
            "accession_number": ["0001-25", "0001-24"],
            "form": ["10-K", "10-K"],
            "fp": ["FY", "FY"],
            "source": ["sec-a", "sec-b"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2025-06-01"))
    assets = inputs.loc[inputs["concept"].eq("assets")]

    assert assets["concept_lag"].tolist() == [0, 1]
    assert assets["accession_number"].tolist() == ["0001-25", "0001-24"]
    assert assets["available_at"].notna().all()
    assert assets["source"].tolist() == ["sec-a", "sec-b"]


def test_sec_concept_inputs_choose_latest_amendment_then_preferred_alias() -> None:
    facts = pd.DataFrame(
        {
            "tag": [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "value": [100.0, 999.0, 110.0],
            "period_end": ["2024-12-31"] * 3,
            "available_at": ["2025-02-01", "2025-02-01", "2025-03-01"],
            "accession_number": ["original", "lower-priority-alias", "amendment"],
            "form": ["10-K", "10-K", "10-K/A"],
            "fp": ["FY", "FY", "FY"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2025-06-01"))
    revenue = inputs.loc[inputs["concept"].eq("revenue")]

    assert revenue["value"].tolist() == [110.0]
    assert revenue["accession_number"].tolist() == ["amendment"]


def test_pinned_sec_mapper_fallback_filters_non_common_securities(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mappings.csv"
    path.write_text(
        "CIK,Ticker,Name,Exchange\n"
        "0000320193,AAPL,Apple Inc,Nasdaq\n"
        "0000000002,TESTW,Test Corp Warrant,Nasdaq\n"
        "0000000003,OTCX,OTC Example,OTC\n",
        encoding="utf-8",
    )
    result = _sec_exchange_csv_rows(path)
    assert result[["symbol", "cik"]].to_dict(orient="records") == [
        {"symbol": "AAPL", "cik": 320193}
    ]
    assert result["source"].iloc[0] == "sec_cik_mapper_pinned_sec_derived"


def test_chunk_rows_remain_dataframes_and_cover_input_once() -> None:
    frame = pd.DataFrame({"symbol": [f"S{i}" for i in range(11)]})
    chunks = [_select_chunk_rows(frame, index, 4) for index in range(4)]
    assert all(isinstance(chunk, pd.DataFrame) for chunk in chunks)
    assert sorted(pd.concat(chunks)["symbol"].tolist()) == sorted(frame["symbol"].tolist())
    with pytest.raises(OpenAPDataError):
        _select_chunk_rows(frame, 4, 4)


def test_jina_sec_json_wrapper_is_parsed_without_losing_payload() -> None:
    payload = _json_from_jina_text(
        'Title: SEC\n\nURL Source: https://data.sec.gov/example\n\nMarkdown Content:\n{"cik":320193,"facts":{}}'
    )
    assert payload["cik"] == 320193


def test_jina_sec_json_wrapper_accepts_control_characters_in_strings() -> None:
    payload = _json_from_jina_text(
        'Title: SEC\n\nMarkdown Content:\n{"cik":1,"entityName":"Example\u000bCorp"}'
    )

    assert payload["entityName"] == "Example\u000bCorp"


def test_companyfacts_rows_keep_only_needed_tags_and_causal_dates() -> None:
    payload = {
        "entityName": "Example",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": f"20{year:02d}-12-31", "val": year, "filed": f"20{year + 1:02d}-02-01", "form": "10-K"}
                            for year in range(10, 20)
                        ]
                    }
                },
                "UnneededTag": {"units": {"USD": [{"end": "2019-12-31", "val": 1, "filed": "2020-02-01"}]}},
            }
        },
    }
    rows = _companyfacts_rows(
        payload,
        1,
        source_url="https://data.sec.gov/example",
        source_mode="sec_official_api",
    )
    assert len(rows) == 10
    assert {row["tag"] for row in rows} == {"Assets"}
    assert all(
        pd.Timestamp(row["available_at"]) > pd.Timestamp(row["filed"], tz="UTC")
        for row in rows
    )


def test_price_features_are_real_and_trendfactor_is_disclosed_proxy() -> None:
    dates = pd.bdate_range("2004-01-01", periods=5500)
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": np.linspace(10, 100, len(dates)),
            "close": np.linspace(10, 100, len(dates)),
            "high": np.linspace(10.1, 100.1, len(dates)),
            "low": np.linspace(9.9, 99.9, len(dates)),
            "volume": 1_000_000,
        }
    )
    result = calculate_price_features(frame)
    assert result["Mom12m"].status == "exact"
    assert result["TrendFactor"].status == "proxy"
    assert result["TrendFactor"].raw_value is not None
    assert result["MomSeasonShort"].status == "exact"
    assert result["Mom12mOffSeason"].raw_value is not None


def test_accounting_features_do_not_fill_missing_with_zero() -> None:
    concepts = {
        "assets": [100.0, 80.0],
        "equity": [60.0, 50.0],
        "net_income": [10.0, 9.0],
        "operating_cash_flow": [8.0, 7.0],
        "revenue": [150.0, 130.0],
    }
    result = calculate_accounting_features(concepts, market_cap=200.0)
    assert result["BM"].raw_value == pytest.approx(0.3)
    assert result["AssetGrowth"].raw_value == pytest.approx(0.25)
    assert result["ChInv"].raw_value is None
    assert result["InvestPPEInv"].raw_value is None
    assert result["PayoutYield"].raw_value is None
    assert result["NetPayoutYield"].raw_value is None
    assert result["OPLeverage"].raw_value is None
    assert result["OperProf"].raw_value is None
    assert result["tang"].raw_value is None


def test_accounting_features_cover_direct_sec_formulas_without_invented_inputs() -> None:
    concepts = {
        "assets": [100.0, 80.0, 70.0, 60.0, 55.0, 50.0],
        "current_assets": [50.0, 40.0],
        "current_liabilities": [25.0, 20.0],
        "cash": [10.0, 8.0],
        "debt_current": [5.0, 4.0, 4.0, 3.0, 3.0, 2.0],
        "debt_long": [15.0, 14.0, 13.0, 12.0, 11.0, 10.0],
        "equity": [60.0, 50.0],
        "revenue": [150.0, 120.0, 100.0],
        "inventory": [20.0, 16.0, 14.0],
        "cogs": [90.0, 75.0],
        "sga": [20.0, 18.0],
        "interest": [3.0, 3.0],
        "rd": [12.0, 8.0],
        "share_issuance": [4.0, 3.0],
        "repurchases": [2.0, 1.0],
        "dividends": [1.0, 1.0],
        "debt_issuance": [6.0, 5.0],
        "debt_reduction": [2.0, 2.0],
    }

    result = calculate_accounting_features(concepts, market_cap=200.0)

    assert result["CashProd"].raw_value == pytest.approx(10.0)
    assert result["ChAssetTurnover"].raw_value == pytest.approx(0.0)
    assert result["CompositeDebtIssuance"].raw_value == pytest.approx(np.log(20.0) - np.log(12.0))
    assert result["NetEquityFinance"].raw_value == pytest.approx(2.0 / 90.0)
    assert result["OPLeverage"].raw_value == pytest.approx(1.1)
    assert result["OperProf"].raw_value == pytest.approx(37.0 / 60.0)
    assert result["XFIN"].raw_value == pytest.approx(5.0 / 100.0)


def test_accounting_composites_require_every_reported_component() -> None:
    concepts = {
        "assets": [100.0, 90.0],
        "ppe": [40.0, 35.0],
        "dividends": [2.0],
        "revenue": [120.0],
        "cogs": [70.0],
        "equity": [50.0],
        "cash": [10.0],
        "inventory": [20.0],
    }

    result = calculate_accounting_features(concepts, market_cap=200.0)

    assert result["InvestPPEInv"].raw_value is None
    assert result["PayoutYield"].raw_value is None
    assert result["NetPayoutYield"].raw_value is None
    assert result["OPLeverage"].raw_value is None
    assert result["OperProf"].raw_value is None
    assert result["tang"].raw_value is None


def test_analyst_revision_proxy_does_not_replace_missing_counts_with_zero() -> None:
    rows = pd.DataFrame(
        {
            "dataset": ["eps_revisions"],
            "payload_json": ['[{"upLast7days": 2, "downLast7days": null}]'],
        }
    )

    result = _analyst_features(rows)

    assert result["UpRecomm"].raw_value == 2.0
    assert result["DownRecomm"].raw_value is None
    assert result["AnalystRevision"].raw_value is None
    assert result["REV6"].raw_value is None


def test_security_eligibility_requires_verified_us_equity_and_recent_price() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["GOOD", "FOREIGN", "ETF", "UNKNOWN", "STALE"],
            "company_name_sec": ["Good Inc", "Foreign Inc", "Index ETF", "Unknown Inc", "Stale Inc"],
            "longName": ["Good Inc", "Foreign Inc", "Index ETF", "Unknown Inc", "Stale Inc"],
            "quoteType": ["EQUITY", "EQUITY", "ETF", None, "EQUITY"],
            "country_yahoo": ["United States", "Canada", "United States", None, "United States"],
            "price_rows": [100, 100, 100, 100, 100],
            "last_price_date": ["2026-08-01", "2026-08-01", "2026-08-01", "2026-08-01", "2026-06-01"],
        }
    )

    result = _classify_security_eligibility(
        frame,
        as_of=pd.Timestamp("2026-08-02"),
    ).set_index("symbol")

    assert bool(result.at["GOOD", "eligible_common_stock"])
    assert result.at["FOREIGN", "eligibility_reason"] == "yahoo_country_not_united_states"
    assert result.at["ETF", "eligibility_reason"] == "excluded_name_or_instrument"
    assert result.at["UNKNOWN", "eligibility_reason"] == "yahoo_quote_type_not_equity"
    assert result.at["STALE", "eligibility_reason"] == "latest_price_is_stale"


def test_chunk_hash_manifest_uses_three_digit_suffix(tmp_path: Path) -> None:
    path = tmp_path / "prices_007.parquet"
    path.write_bytes(b"auditable")

    result = _hashes_by_chunk([path])

    assert set(result) == {7}
    assert len(result[7]) == 64


def test_score_gives_one_vote_to_redundancy_group() -> None:
    metadata = _metadata()
    metadata.loc[0, "signalname"] = "a"
    metadata.loc[1, "signalname"] = "b"
    groups = pd.DataFrame(
        {
            "signalname": metadata["signalname"],
            "redundancy_group": ["same", "same"] + [f"g{i}" for i in range(183)],
        }
    )
    values = {
        "AAA": {
            "a": FeatureValue("a", 1.0, "exact", "test", "a"),
            "b": FeatureValue("b", 1.0, "exact", "test", "b"),
            **{
                f"signal_{index:03d}": FeatureValue(f"signal_{index:03d}", float(index), "exact", "test", "x")
                for index in range(2, 185)
            },
        },
        "BBB": {
            "a": FeatureValue("a", 0.0, "exact", "test", "a"),
            "b": FeatureValue("b", 0.0, "exact", "test", "b"),
            **{
                f"signal_{index:03d}": FeatureValue(f"signal_{index:03d}", float(index - 1), "exact", "test", "x")
                for index in range(2, 185)
            },
        },
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01", redundancy_groups=groups)
    scores = calculate_scores(features)
    assert not scores.empty
    assert scores.loc[scores["symbol"].eq("AAA"), "groups_used"].iloc[0] == 184


def test_coverage_has_one_row_for_every_strict_predictor() -> None:
    metadata = _metadata()
    values = {
        "AAA": {
            "signal_000": FeatureValue("signal_000", 1.0, "exact", "test", "formula")
        }
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")
    report = coverage_report(features, metadata)
    assert len(report) == 185
    assert report.loc[report["signalname"].eq("signal_000"), "coverage_status"].iloc[0] == "exact"


def test_coverage_does_not_call_null_exact_values_available() -> None:
    metadata = _metadata()
    values = {
        "AAA": {
            "signal_000": FeatureValue("signal_000", None, "exact", "test", "formula")
        }
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")

    report = coverage_report(features, metadata)
    row = report.loc[report["signalname"].eq("signal_000")].iloc[0]

    assert row["coverage_status"] == "unavailable"
    assert row["exact_rows"] == 0
    assert row["unavailable_rows"] == 1


def test_scores_include_all_horizons_with_horizon_specific_minimums() -> None:
    metadata = _metadata()
    metadata.loc[:4, "portperiod"] = [1, 3, 6, 12, 36]
    values = {
        symbol: {
            f"signal_{index:03d}": FeatureValue(
                f"signal_{index:03d}",
                float(value + index),
                "proxy" if index in {2, 4} else "exact",
                "test",
                "formula",
            )
            for index in range(5)
        }
        for symbol, value in (("AAA", 1), ("BBB", 0))
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")

    scores = calculate_scores(features, minimum_metrics=5)
    aaa = scores.loc[scores["symbol"].eq("AAA")]

    assert set(aaa["horizon_months"]) == {1, 3, 6, 12, 36}
    assert aaa["score"].notna().all()
    assert aaa.loc[aaa["horizon_months"].eq(6), "confidence"].iloc[0] > 0


def test_aggregate_score_uses_available_horizons_without_zero_filling() -> None:
    scores = pd.DataFrame(
        {
            "as_of": ["2026-08-01"] * 3,
            "symbol": ["AAA"] * 3,
            "horizon_months": [1, 3, 6],
            "score": [80.0, 60.0, np.nan],
            "confidence": [100.0, 50.0, 0.0],
            "metrics_used": [10, 5, 0],
            "groups_used": [10, 5, 0],
        }
    )

    result = calculate_aggregate_scores(scores).iloc[0]

    assert result["aggregate_score"] == pytest.approx((80.0 + 30.0) / 1.5)
    assert result["horizons_used"] == 2
    assert result["aggregate_confidence"] == pytest.approx(30.0)


def test_workflow_contract_is_github_only_and_complete() -> None:
    text = Path(".github/workflows/openap-yfinance-sec-current-score.yml").read_text(encoding="utf-8")
    assert "OpenAP Current Score YFinance SEC EDGAR" in text
    assert "YFINANCE_CHUNKS: \"48\"" in text
    assert "SEC_CHUNKS: \"48\"" in text
    assert "max-parallel: 16" in text
    assert "max-parallel: 8" in text
    assert "sec-chunk" in text
    assert "openap-sec-raw-${{ matrix.chunk }}" in text
    assert "openap-yfinance-sec-current-score-results" in text
    assert "locked_opened" in text
    assert "backtest_enabled" in text
    assert 'summary["companyfacts_rows"] > 0' in text
    assert 'summary["submissions_rows"] > 0' in text


def test_repair_workflow_reuses_source_run_and_replaces_only_empty_shards() -> None:
    text = Path(
        ".github/workflows/openap-yfinance-sec-repair-merge.yml"
    ).read_text(encoding="utf-8")

    assert "source_run_id" in text
    assert "chunk: [7, 23]" in text
    assert "openap-sec-repair-lake-${{ matrix.chunk }}" in text
    assert "sec_companyfacts_${chunk}.parquet" in text
    assert "score_horizons" in text
    assert "openap-yfinance-sec-current-score-results" in text
