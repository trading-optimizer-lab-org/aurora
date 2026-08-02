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
    calculate_price_features,
    calculate_scores,
    coverage_report,
    latest_sec_concepts,
    select_strict_predictors,
)
from scripts.run_openap_yfinance_sec_current import (
    _companyfacts_rows,
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
    assert len(rows) == 6
    assert {row["tag"] for row in rows} == {"Assets"}
    assert all(
        pd.Timestamp(row["available_at"]) > pd.Timestamp(row["filed"], tz="UTC")
        for row in rows
    )


def test_price_features_are_real_and_trendfactor_is_disclosed_proxy() -> None:
    dates = pd.bdate_range("2021-01-01", periods=1100)
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
