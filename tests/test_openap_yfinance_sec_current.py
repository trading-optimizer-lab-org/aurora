# mypy: disable-error-code="index"

from __future__ import annotations

import zipfile

import numpy as np
import pandas as pd
import pytest
import requests
import yaml
from pathlib import Path
from urllib.parse import urlsplit

import scripts.run_openap_yfinance_sec_current as current_runner

from aurora.research.openap_current_score import (
    EXPECTED_PREDICTORS,
    FeatureValue,
    OpenAPDataError,
    apply_accounting_input_freshness,
    assemble_feature_table,
    build_redundancy_groups,
    calculate_accounting_features,
    calculate_aggregate_scores,
    calculate_price_features,
    calculate_scores,
    clean_price_history,
    coverage_report,
    exclude_incomplete_us_session,
    latest_completed_us_session_date,
    latest_sec_concepts,
    latest_sec_concept_inputs,
    official_filter_mask,
    refine_current_redundancy_groups,
    select_strict_predictors,
)
from scripts.run_openap_yfinance_sec_current import (
    YFINANCE_METADATA_FIELDS,
    _analyst_features,
    _add_issuer_market_cap_context,
    _classify_security_eligibility,
    _companyfacts_rows,
    _download_sec_archive,
    _hashes_by_chunk,
    _json_from_jina_text,
    _options_features,
    _request_sec_json,
    _scorable_feature_counts,
    _sec_headers,
    _sec_exchange_csv_rows,
    _sec_issuer_flags,
    _sec_surface_availability,
    _select_chunk_rows,
    _submission_rows,
    create_options_quality_tables,
    finalize_database_contract,
)


def test_yfinance_metadata_contract_includes_current_short_interest_fields() -> None:
    required = {
        "sharesShort",
        "sharesShortPriorMonth",
        "shortRatio",
        "shortPercentOfFloat",
        "dateShortInterest",
        "sharesPercentSharesOut",
        "heldPercentInstitutions",
    }

    assert required <= set(YFINANCE_METADATA_FIELDS)


def test_sec_bulk_headers_identify_contact_and_official_host() -> None:
    headers = _sec_headers(
        "Aurora Research research@example.com",
        url="https://data.sec.gov/Archives/example.zip",
    )

    assert headers["User-Agent"] == "Aurora Research research@example.com"
    assert headers["From"] == "research@example.com"
    assert headers["Host"] == "data.sec.gov"
    assert headers["Referer"] == "https://www.sec.gov/"


def test_sec_bulk_archive_uses_next_official_hostname(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_download(
        url: str,
        destination: Path,
        *,
        headers: dict[str, str],
        retries: int,
    ) -> None:
        calls.append((url, headers))
        assert retries == 7
        if urlsplit(url).hostname == "www.sec.gov":
            raise requests.HTTPError("403")
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("CIK0000000001.json", "{}")

    monkeypatch.setattr(current_runner, "_download", fake_download)
    destination = tmp_path / "companyfacts.zip"
    selected = _download_sec_archive(
        [
            "https://www.sec.gov/Archives/companyfacts.zip",
            "https://data.sec.gov/Archives/companyfacts.zip",
        ],
        destination,
        user_agent="Aurora Research research@example.com",
    )

    assert selected == "https://data.sec.gov/Archives/companyfacts.zip"
    assert zipfile.is_zipfile(destination)
    assert [url for url, _ in calls] == [
        "https://www.sec.gov/Archives/companyfacts.zip",
        "https://data.sec.gov/Archives/companyfacts.zip",
    ]
    assert calls[0][1]["Host"] == "www.sec.gov"
    assert calls[1][1]["Host"] == "data.sec.gov"


def test_sec_direct_403_opens_process_circuit_and_uses_audited_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Response:
        def __init__(self, status_code: int, text: str = "") -> None:
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")

        def json(self) -> dict[str, bool]:
            return {"official": True}

    def fake_get(url: str, **_: object) -> Response:
        calls.append(url)
        if urlsplit(url).hostname == "data.sec.gov":
            return Response(403)
        return Response(200, 'Markdown Content:\n```json\n{"fallback": true}\n```')

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(current_runner, "_SEC_DIRECT_API_BLOCKED", False)

    first = _request_sec_json(
        "https://data.sec.gov/one.json",
        "https://r.jina.ai/http://data.sec.gov/one.json",
        headers={"User-Agent": "test@example.com"},
    )
    second = _request_sec_json(
        "https://data.sec.gov/two.json",
        "https://r.jina.ai/http://data.sec.gov/two.json",
        headers={"User-Agent": "test@example.com"},
    )

    assert first[1] == "sec_via_jina_readthrough"
    assert second[1] == "sec_via_jina_readthrough"
    assert first[0] == {"fallback": True}
    assert second[0] == {"fallback": True}
    assert sum(urlsplit(url).hostname == "data.sec.gov" for url in calls) == 1


def test_sec_readthrough_failure_is_bounded_per_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[int, int]]] = []
    sleeps: list[int] = []

    def fake_get(url: str, **kwargs: object) -> object:
        calls.append((url, kwargs["timeout"]))
        raise requests.Timeout("read-through unavailable")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(current_runner.time, "sleep", sleeps.append)
    monkeypatch.setattr(current_runner, "_SEC_DIRECT_API_BLOCKED", True)

    with pytest.raises(OpenAPDataError, match="SEC JSON unavailable"):
        _request_sec_json(
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            "https://r.jina.ai/http://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            headers={"User-Agent": "test@example.com"},
        )

    assert len(calls) == 2
    assert all(url.startswith("https://r.jina.ai/") for url, _ in calls)
    assert all(timeout == current_runner.SEC_API_FALLBACK_TIMEOUT for _, timeout in calls)
    assert sleeps == [1]


def test_sec_surface_availability_fails_closed_per_issuer() -> None:
    status = pd.DataFrame(
        [
            {"cik": 1, "surface": "companyfacts", "status": "ok"},
            {"cik": 1, "surface": "submissions", "status": "ok"},
            {"cik": 2, "surface": "companyfacts", "status": "error"},
            {"cik": 2, "surface": "submissions", "status": "ok"},
            {"cik": 3, "surface": "companyfacts", "status": "repaired_bulk"},
        ]
    )

    result = _sec_surface_availability(status).set_index("cik")

    assert bool(result.loc[1, "sec_companyfacts_available"])
    assert bool(result.loc[1, "sec_submissions_available"])
    assert not bool(result.loc[2, "sec_companyfacts_available"])
    assert bool(result.loc[2, "sec_submissions_available"])
    assert bool(result.loc[3, "sec_companyfacts_available"])
    assert not bool(result.loc[3, "sec_submissions_available"])


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
            "Cat.Form": "continuous",
            "q_cut": 0.2,
            "q_filt": pd.Series([None] * rows, dtype="object"),
            "filterstr": pd.Series([None] * rows, dtype="object"),
            "sweight": "EW",
            "startmonth": 6.0,
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


def test_redundancy_groups_do_not_chain_or_mix_economic_families() -> None:
    metadata = _metadata(4)
    metadata.loc[:, "signalname"] = ["a", "b", "c", "d"]
    metadata.loc[:, "Cat.Economic"] = ["price", "price", "price", "quality"]
    rng = np.random.default_rng(7)
    basis, _ = np.linalg.qr(rng.normal(size=(200, 3)))
    a = basis[:, 0]
    b = 0.9 * basis[:, 0] + np.sqrt(1 - 0.9**2) * basis[:, 1]
    residual = basis[:, 2] - np.dot(basis[:, 2], b) * b
    residual = residual / np.linalg.norm(residual)
    c = 0.9 * b + np.sqrt(1 - 0.9**2) * residual
    d = a.copy()
    returns = pd.DataFrame({"a": a, "b": b, "c": c, "d": d})

    groups = build_redundancy_groups(metadata, returns, threshold=0.85, minimum_overlap=60)
    mapping = groups.set_index("signalname")["redundancy_group"]

    assert mapping["a"] == mapping["b"]
    assert mapping["c"] != mapping["a"]
    assert mapping["d"] != mapping["a"]


def test_current_redundancy_merges_identical_cross_sectional_signals() -> None:
    features = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"] * 2,
            "signalname": ["a"] * 3 + ["b"] * 3,
            "formula_id": ["formula_a"] * 3 + ["formula_b"] * 3,
            "horizon_months": [1] * 6,
            "percentile": [20.0, 50.0, 90.0] * 2,
            "redundancy_group": ["historical_a"] * 3 + ["historical_b"] * 3,
        }
    )

    refined, audit = refine_current_redundancy_groups(
        features, threshold=0.995, minimum_overlap=3
    )

    assert refined["redundancy_group"].nunique() == 1
    assert audit["current_merge_applied"].all()


def test_current_redundancy_collapses_known_duplicate_openap_implementations() -> None:
    duplicate_sets = [
        ("Accruals", "TotalAccruals"),
        ("CF", "cfp"),
        ("AnalystRevision", "REV6"),
        ("CPVolSpread", "SmileSlope", "skew1"),
    ]
    rows = []
    for set_index, names in enumerate(duplicate_sets):
        for signal_index, signalname in enumerate(names):
            for symbol_index in range(120):
                rows.append(
                    {
                        "symbol": f"S{symbol_index:03d}",
                        "signalname": signalname,
                        "formula_id": f"formula_{signalname}",
                        "horizon_months": 12 if set_index < 2 else 1,
                        "percentile": float(symbol_index),
                        "redundancy_group": f"historical_{signal_index}_{signalname}",
                    }
                )
    features = pd.DataFrame(rows)

    refined, _ = refine_current_redundancy_groups(
        features, threshold=0.995, minimum_overlap=100
    )
    mapping = refined.drop_duplicates("signalname").set_index("signalname")[
        "redundancy_group"
    ]

    for names in duplicate_sets:
        assert mapping.loc[list(names)].nunique() == 1


def test_official_filter_mapping_fails_closed_and_applies_known_rules() -> None:
    context = pd.DataFrame(
        {
            "current_price": [10.0, 4.0, 10.0],
            "exchange_code": [1, 1, 3],
            "eligible_common_stock": [True, True, True],
            "market_cap": [100.0, 100.0, 100.0],
            "nyse_market_cap_p20": [50.0, 50.0, 50.0],
        },
        index=["A", "B", "C"],
    )
    mask, status = official_filter_mask(
        {"filterstr": "abs(prc)>5, exchcd==1"}, context
    )
    assert status == "applied"
    assert mask.to_dict() == {"A": True, "B": False, "C": False}

    listed, status = official_filter_mask(
        {"filterstr": "exchcd %in% c(1,2), shrcd <= 11"}, context
    )
    assert status == "applied"
    assert listed.to_dict() == {"A": True, "B": True, "C": False}

    all_primary, status = official_filter_mask(
        {"filterstr": "exchcd%in%c(1,2,3),shrcd<=11"}, context
    )
    assert status == "applied"
    assert all_primary.to_dict() == {"A": True, "B": True, "C": True}

    unsupported, status = official_filter_mask(
        {"filterstr": "siccd > 0"}, context
    )
    assert not unsupported.any()
    assert status.startswith("unsupported:")

    malformed, status = official_filter_mask(
        {"filterstr": "exchcd%in%c(1,2"}, context
    )
    assert not malformed.any()
    assert status == "unsupported:unbalanced_parentheses"


def test_assemble_uses_nyse_breakpoints_and_neutralises_middle_bucket() -> None:
    metadata = _metadata()
    metadata.loc[0, ["signalname", "q_filt", "q_cut"]] = ["test_signal", "NYSE", 0.2]
    values = {
        "NYSE_LOW": {"test_signal": FeatureValue("test_signal", 1.0, "exact", "test", "f")},
        "NYSE_HIGH": {"test_signal": FeatureValue("test_signal", 9.0, "exact", "test", "f")},
        "NASDAQ_MID": {"test_signal": FeatureValue("test_signal", 5.0, "exact", "test", "f")},
    }
    context = pd.DataFrame(
        {
            "symbol": list(values),
            "exchange_sec": ["NYSE", "NYSE", "Nasdaq"],
            "marketCap": [100.0, 100.0, 100.0],
            "current_price": [10.0, 10.0, 10.0],
            "eligible_common_stock": True,
        }
    )

    features = assemble_feature_table(
        metadata,
        values,
        as_of="2026-08-01",
        security_context=context,
        minimum_cross_sectional_observations=2,
    )
    rows = features.loc[features["signalname"].eq("test_signal")].set_index("symbol")

    assert rows.at["NYSE_LOW", "official_portfolio_bucket"] == "short"
    assert rows.at["NYSE_HIGH", "official_portfolio_bucket"] == "long"
    assert rows.at["NASDAQ_MID", "official_portfolio_bucket"] == "neutral"
    assert rows.at["NASDAQ_MID", "score_percentile"] == 50.0


def test_equal_cross_sectional_values_are_rejected_as_uninformative() -> None:
    metadata = _metadata()
    metadata.loc[0, "signalname"] = "constant_signal"
    values = {
        symbol: {
            "constant_signal": FeatureValue(
                "constant_signal", 7.0, "exact", "test", "constant_formula"
            )
        }
        for symbol in ("AAA", "BBB", "CCC")
    }

    features = assemble_feature_table(metadata, values, as_of="2026-08-01")
    rows = features.loc[features["signalname"].eq("constant_signal")]

    assert rows["status"].eq("unavailable").all()
    assert rows["value_status"].eq("uninformative_cross_section").all()
    assert rows["evidence_weight"].eq(0.0).all()
    assert rows["score_percentile"].isna().all()


def test_sparse_cross_sectional_signal_is_excluded_from_score() -> None:
    metadata = _metadata()
    metadata.loc[0, "signalname"] = "sparse_signal"
    values = {
        "AAA": {"sparse_signal": FeatureValue("sparse_signal", 1.0, "exact", "test", "f")},
        "BBB": {"sparse_signal": FeatureValue("sparse_signal", 2.0, "exact", "test", "f")},
        "CCC": {"sparse_signal": FeatureValue("sparse_signal", None, "exact", "test", "f")},
        "DDD": {"sparse_signal": FeatureValue("sparse_signal", None, "exact", "test", "f")},
    }

    features = assemble_feature_table(
        metadata,
        values,
        as_of="2026-08-01",
        minimum_cross_sectional_observations=3,
    )
    rows = features.loc[features["signalname"].eq("sparse_signal")]

    assert rows.loc[rows["raw_value"].notna(), "value_status"].eq(
        "insufficient_cross_sectional_coverage"
    ).all()
    assert rows["evidence_weight"].eq(0.0).all()
    assert rows["score_percentile"].isna().all()


def test_sec_concepts_ignore_facts_not_yet_available() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets"],
            "value": [100.0, 999.0],
            "period_end": ["2024-12-31", "2025-12-31"],
            "available_at": ["2025-02-01T12:00:00Z", "2026-02-01T12:00:00Z"],
            "unit": ["USD", "USD"],
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
            "unit": ["USD", "USD", "USD"],
        }
    )

    concepts = latest_sec_concepts(facts, pd.Timestamp("2025-06-01"))

    assert concepts["revenue"][:2] == [100.0, 80.0]


def test_sec_shares_use_latest_instant_observation_not_stale_annual_filing() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["CommonStockSharesOutstanding", "CommonStockSharesOutstanding"],
            "value": [100.0, 200_000_000.0],
            "period_end": ["2024-12-31", "2025-06-30"],
            "available_at": ["2025-02-01", "2025-08-01"],
            "accession_number": ["annual", "quarterly"],
            "form": ["10-K", "10-Q"],
            "fp": ["FY", "Q2"],
            "unit": ["shares", "shares"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2025-09-01"))
    shares = inputs.loc[inputs["concept"].eq("shares")]

    assert shares.iloc[0]["value"] == 200_000_000.0
    assert shares.iloc[0]["accession_number"] == "quarterly"


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
            "unit": ["USD", "USD", "USD"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2025-06-01"))
    revenue = inputs.loc[inputs["concept"].eq("revenue")]

    assert revenue["value"].tolist() == [110.0]
    assert revenue["accession_number"].tolist() == ["amendment"]


def test_sec_concept_inputs_reject_future_periods_and_wrong_units() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets", "EntityCommonStockSharesOutstanding"],
            "value": [999.0, 100.0, 25.0],
            "period_end": ["2030-12-31", "2025-12-31", "2025-12-31"],
            "available_at": ["2026-01-01", "2026-01-01", "2026-01-01"],
            "form": ["10-K", "10-K", "10-K"],
            "fp": ["FY", "FY", "FY"],
            "unit": ["USD", "CAD", "USD"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2026-08-01"))

    assert inputs.empty


def test_sec_concept_inputs_reject_impossible_availability_dates() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets"],
            "value": [999.0, 100.0],
            "period_end": ["2025-12-31", "2024-12-31"],
            "filed": ["2025-02-01", "2025-02-01"],
            "available_at": ["2025-02-02", "2025-02-02"],
            "form": ["10-K", "10-K"],
            "fp": ["FY", "FY"],
            "unit": ["USD", "USD"],
        }
    )

    inputs = latest_sec_concept_inputs(facts, pd.Timestamp("2026-08-01"))

    assert inputs["value"].tolist() == [100.0]


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


def test_companyfacts_retains_annual_history_beyond_recent_quarters() -> None:
    annual = [
        {
            "start": f"{year}-01-01",
            "end": f"{year}-12-31",
            "val": year,
            "filed": f"{year + 1}-02-15",
            "form": "10-K",
            "fp": "FY",
        }
        for year in range(2018, 2024)
    ]
    quarters = []
    for index in range(30):
        period_end = pd.Timestamp("2023-01-31") + pd.offsets.MonthEnd(index)
        quarters.append(
            {
                "start": "2023-01-01",
                "end": period_end.date().isoformat(),
                "val": index,
                "filed": (period_end + pd.Timedelta(days=30)).date().isoformat(),
                "form": "10-Q",
                "fp": "Q1",
            }
        )
    payload = {
        "facts": {
            "us-gaap": {"Assets": {"units": {"USD": annual + quarters}}}
        }
    }

    rows = _companyfacts_rows(
        payload,
        1,
        source_url="https://data.sec.gov/example",
        source_mode="sec_official_bulk_archive",
        observations_per_tag=4,
        annual_observations_per_tag=6,
    )

    annual_rows = [row for row in rows if row["form"] == "10-K"]
    assert len(annual_rows) == 6
    assert {row["period_end"] for row in annual_rows} == {
        f"{year}-12-31" for year in range(2018, 2024)
    }


def test_companyfacts_use_real_sec_acceptance_timestamp_when_available() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [{
                            "end": "2025-12-31", "val": 10, "filed": "2026-02-01",
                            "accn": "0001", "form": "10-K",
                        }]
                    }
                }
            }
        }
    }
    rows = _companyfacts_rows(
        payload,
        1,
        source_url="https://data.sec.gov/example",
        source_mode="sec_official_api",
        accepted_at_by_accession={"0001": "2026-02-01T16:42:00Z"},
    )

    assert rows[0]["available_at_quality"] == "sec_acceptance_timestamp"
    assert pd.Timestamp(rows[0]["available_at"]) == pd.Timestamp("2026-02-01T16:42:00Z")


def test_companyfacts_clamp_acceptance_timestamp_before_filing_date() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [{
                            "end": "2025-12-31", "val": 10, "filed": "2026-02-05",
                            "accn": "0001", "form": "10-K",
                        }]
                    }
                }
            }
        }
    }
    rows = _companyfacts_rows(
        payload,
        1,
        source_url="https://data.sec.gov/example",
        source_mode="sec_official_api",
        accepted_at_by_accession={"0001": "2026-02-01T16:42:00Z"},
    )

    assert rows[0]["available_at_quality"] == "sec_acceptance_before_filing_clamped_plus_one_day"
    assert pd.Timestamp(rows[0]["available_at"]) == pd.Timestamp("2026-02-06T00:00:00Z")


def test_price_features_are_real_and_trendfactor_is_fail_closed() -> None:
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
    assert result["TrendFactor"].status == "unavailable"
    assert result["TrendFactor"].raw_value is None
    assert result["TrendFactor"].formula_id == (
        "openap_11ma_cross_sectional_regression_12m_lagged_betas"
    )
    assert result["MomSeasonShort"].status == "exact"
    assert result["MomSeasonShort"].formula_id == "openap_ret_lag_11"
    assert result["Mom12mOffSeason"].raw_value is not None


def test_price_features_match_official_reversal_and_liquidity_windows() -> None:
    dates = pd.bdate_range("2018-01-01", "2026-08-01")
    sequence = np.arange(len(dates), dtype=float)
    price = 20.0 * np.exp(sequence / 5000.0 + np.sin(sequence / 37.0) / 20.0)
    volume = 500_000.0 + (sequence % 101) * 10_000.0
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": price,
            "close": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "volume": volume,
        }
    )
    result = calculate_price_features(frame)
    monthly = frame.set_index("date")["adj_close"].resample("ME").last().dropna()
    daily_returns = frame["adj_close"].pct_change()
    dollar_volume = frame["adj_close"] * frame["volume"]
    monthly_volume = frame.set_index("date")["volume"].resample("ME").sum().dropna()

    assert result["MRreversal"].formula_id == "return_month_18_to_13"
    assert result["MRreversal"].raw_value == pytest.approx(
        monthly.iloc[-14] / monthly.iloc[-19] - 1.0
    )
    assert result["LRreversal"].formula_id == "return_month_36_to_13"
    assert result["LRreversal"].raw_value == pytest.approx(
        monthly.iloc[-14] / monthly.iloc[-37] - 1.0
    )
    assert result["Illiquidity"].formula_id == "amihud_252d"
    assert result["Illiquidity"].raw_value == pytest.approx(
        (daily_returns.abs() / dollar_volume).iloc[-252:].mean()
    )
    assert result["DolVol"].formula_id == "log_monthly_dollar_volume_lag_2"
    assert result["DolVol"].raw_value == pytest.approx(
        np.log(monthly.iloc[-3] * monthly_volume.iloc[-3])
    )
    assert result["RealizedVol"].status == "proxy"
    assert result["ShareVol"].raw_value is None


def test_monthly_price_features_exclude_the_current_partial_month() -> None:
    dates = pd.bdate_range("2024-01-02", "2026-08-10")
    price = np.linspace(50.0, 150.0, len(dates))
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": price,
            "close": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "volume": 1_000_000.0,
        }
    )

    result = calculate_price_features(
        frame, as_of=pd.Timestamp("2026-08-10")
    )
    completed = (
        frame.loc[frame["date"].dt.to_period("M").lt(pd.Period("2026-08"))]
        .set_index("date")["adj_close"]
        .resample("ME")
        .last()
    )

    assert result["STreversal"].raw_value == pytest.approx(
        completed.pct_change().iloc[-1]
    )


def test_official_volume_and_realized_volatility_windows() -> None:
    dates = pd.bdate_range("2019-01-01", "2026-08-10")
    sequence = np.arange(len(dates), dtype=float)
    price = 75.0 * np.exp(sequence / 6000.0 + np.sin(sequence / 13.0) / 50.0)
    volume = 500_000.0 + sequence * 250.0 + (sequence % 17) * 2_000.0
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": price,
            "close": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "volume": volume,
        }
    )

    result = calculate_price_features(frame, as_of=pd.Timestamp("2026-08-10"))
    completed = frame.loc[frame["date"].dt.to_period("M") < pd.Period("2026-08")]
    periods = completed["date"].dt.to_period("M")
    returns = completed["adj_close"].pct_change()
    expected_realized = returns.loc[periods.eq(periods.max())].dropna().std(ddof=1)
    monthly_volume = completed.set_index("date")["volume"].resample("ME").sum()
    expected_vol_sd = monthly_volume.tail(36).std(ddof=1)
    trend_window = monthly_volume.tail(60)
    x = trend_window.index.year * 12.0 + trend_window.index.month - 1.0
    expected_volume_trend = np.polyfit(x, trend_window.to_numpy(), 1)[0] / trend_window.mean()

    assert result["RealizedVol"].formula_id == (
        "openap_daily_return_std_completed_month_min15"
    )
    assert result["RealizedVol"].raw_value == pytest.approx(expected_realized)
    assert result["VolSD"].formula_id == (
        "openap_monthly_volume_rolling_std_36m_min24"
    )
    assert result["VolSD"].raw_value == pytest.approx(expected_vol_sd)
    assert result["VolumeTrend"].formula_id == (
        "openap_monthly_volume_ols_trend_60m_min30_over_mean"
    )
    assert result["VolumeTrend"].raw_value == pytest.approx(expected_volume_trend)


def test_volume_trend_cross_sectional_trim_matches_openap_contract() -> None:
    values = {
        f"S{index:03d}": {
            "VolumeTrend": FeatureValue(
                "VolumeTrend",
                float(index),
                "proxy",
                "yfinance",
                "openap_monthly_volume_ols_trend_60m_min30_over_mean",
            )
        }
        for index in range(101)
    }

    audit = current_runner._trim_cross_sectional_feature(values, "VolumeTrend")

    assert audit == {"observed": 101, "trimmed": 2, "lower": 1.0, "upper": 99.0}
    assert values["S000"]["VolumeTrend"].raw_value is None
    assert values["S100"]["VolumeTrend"].raw_value is None
    assert values["S050"]["VolumeTrend"].raw_value == 50.0


def test_daily_price_features_exclude_an_open_us_session() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-31", "2026-08-03"]),
            "adj_close": [100.0, 250.0],
            "close": [100.0, 250.0],
            "high": [101.0, 251.0],
            "low": [99.0, 249.0],
            "volume": [1_000_000.0, 10_000.0],
        }
    )

    filtered, excluded, cutoff = exclude_incomplete_us_session(
        frame,
        as_of=pd.Timestamp("2026-08-03 19:00:00", tz="UTC"),
    )
    features = calculate_price_features(
        frame,
        as_of=pd.Timestamp("2026-08-03 19:00:00", tz="UTC"),
    )

    assert cutoff == pd.Timestamp("2026-07-31")
    assert excluded == 1
    assert filtered["date"].max() == pd.Timestamp("2026-07-31")
    assert features["Price"].raw_value == pytest.approx(100.0)


def test_daily_price_features_keep_a_closed_us_session() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-31", "2026-08-03"]),
            "adj_close": [100.0, 110.0],
            "close": [100.0, 110.0],
            "high": [101.0, 111.0],
            "low": [99.0, 109.0],
            "volume": [1_000_000.0, 1_200_000.0],
        }
    )

    assert latest_completed_us_session_date(
        pd.Timestamp("2026-08-03 21:00:00", tz="UTC")
    ) == pd.Timestamp("2026-08-03")
    features = calculate_price_features(
        frame,
        as_of=pd.Timestamp("2026-08-03 21:00:00", tz="UTC"),
    )
    assert features["Price"].raw_value == pytest.approx(110.0)


def test_scorable_feature_counts_exclude_filtered_stale_and_uninformative_rows() -> None:
    features = pd.DataFrame(
        [
            {"symbol": "AAA", "status": "exact", "evidence_weight": 1.0, "score_percentile": 80.0},
            {"symbol": "AAA", "status": "proxy", "evidence_weight": 0.5, "score_percentile": 70.0},
            {"symbol": "AAA", "status": "unavailable", "evidence_weight": 0.0, "score_percentile": np.nan},
            {"symbol": "AAA", "status": "proxy", "evidence_weight": 0.0, "score_percentile": 99.0},
            {"symbol": "BBB", "status": "exact", "evidence_weight": 1.0, "score_percentile": np.nan},
        ]
    )

    counts = _scorable_feature_counts(features).set_index("symbol")

    assert counts.loc["AAA", "computed_features"] == 2
    assert counts.loc["AAA", "exact_features"] == 1
    assert counts.loc["AAA", "proxy_features"] == 1
    assert counts.loc["BBB", "computed_features"] == 0


def test_issuer_market_cap_does_not_double_repeated_dual_class_values() -> None:
    securities = pd.DataFrame(
        {
            "symbol": ["AAA", "AAB", "CCC", "CCD"],
            "cik": [1, 1, 2, 2],
            "eligible_common_stock": [True, True, True, True],
            "marketCap": [100.0, 102.0, 60.0, 40.0],
        }
    )

    result = _add_issuer_market_cap_context(securities).set_index("symbol")

    assert result.loc["AAA", "issuer_market_cap"] == pytest.approx(102.0)
    assert result.loc["AAB", "issuer_market_cap"] == pytest.approx(102.0)
    assert result.loc["AAA", "issuer_market_cap_source"] == (
        "yfinance_repeated_consolidated_market_cap"
    )
    assert result.loc["CCC", "issuer_market_cap"] == pytest.approx(100.0)
    assert result.loc["CCD", "issuer_market_cap"] == pytest.approx(100.0)
    assert result.loc["CCC", "issuer_market_cap_source"] == (
        "yfinance_summed_share_class_market_caps"
    )


def test_share_count_resolution_rejects_stale_or_wrong_sec_values() -> None:
    resolved = current_runner._resolve_current_shares_outstanding(
        sec_shares=100.0,
        yahoo_shares=232_945_978.0,
    )

    assert resolved.raw_value == 232_945_978.0
    assert resolved.status == "proxy"
    assert resolved.source == "yfinance_current_shares"
    assert "SEC/Yahoo mismatch" in resolved.note


def test_share_turnover_never_falls_back_to_raw_volume_units() -> None:
    dates = pd.bdate_range("2023-01-01", periods=800)
    prices = pd.DataFrame(
        {
            "date": dates,
            "adj_close": np.linspace(10.0, 20.0, len(dates)),
            "volume": np.linspace(1_000_000.0, 2_000_000.0, len(dates)),
        }
    )

    missing = current_runner._share_turnover_features(prices, None)
    assert missing["ShareVol"].raw_value is None
    assert missing["std_turn"].raw_value is None
    assert missing["ShareVol"].status == "unavailable"

    resolved = FeatureValue(
        "shares_outstanding",
        100_000_000.0,
        "exact",
        "sec_edgar_cross_validated",
        "latest_instant_shares",
    )
    available = current_runner._share_turnover_features(prices, resolved)
    assert available["ShareVol"].formula_id == "openap_sharevol_binary_3m_turnover"
    assert available["ShareVol"].raw_value in {0.0, 1.0, None}
    assert available["std_turn"].formula_id == "monthly_turnover_std_36m"


def test_seasonality_does_not_replace_missing_month_with_zero() -> None:
    dates = pd.date_range("2023-01-31", periods=30, freq="ME").delete(18)
    price = np.linspace(100.0, 140.0, len(dates))
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": price,
            "close": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "volume": 1_000_000,
        }
    )

    result = calculate_price_features(frame)

    assert result["MomSeasonShort"].raw_value is None


def test_price_cleaner_quarantines_nonpositive_invalid_and_extreme_history() -> None:
    dates = pd.bdate_range("2024-01-01", periods=400)
    price = np.linspace(10.0, 20.0, len(dates))
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": price,
            "high": price + 0.2,
            "low": price - 0.2,
            "close": price,
            "adj_close": price,
            "volume": 100_000,
        }
    )
    frame.loc[50, "adj_close"] = 0.0
    frame.loc[100, "high"] = 1.0
    frame.loc[120, ["open", "high", "low", "close", "adj_close"]] = 1000.0

    clean, quality = clean_price_history(frame)

    assert quality["nonpositive_price_rows"] == 1
    assert quality["invalid_ohlc_rows"] >= 1
    assert quality["extreme_return_rows"] >= 1
    assert clean["date"].min() > frame.loc[120, "date"]
    assert quality["first_clean_price_date"] == clean["date"].min()
    assert quality["last_clean_price_date"] == clean["date"].max()


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
    assert result["Accruals"].status == "proxy"
    assert result["TotalAccruals"].status == "proxy"
    assert result["Accruals"].formula_id == result["TotalAccruals"].formula_id
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


def test_materially_incomplete_accounting_formulas_are_never_labelled_exact() -> None:
    concepts = {
        name: [100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
        for name in (
            "assets", "liabilities", "equity", "cash", "revenue", "net_income",
            "operating_cash_flow", "inventory", "tax", "capex", "debt_current",
            "debt_long", "preferred_stock", "dividends", "repurchases",
            "share_issuance", "rd", "employees", "cogs", "sga", "interest",
            "depreciation",
        )
    }
    result = calculate_accounting_features(concepts, market_cap=1_000.0)
    materially_incomplete = {
        "AM", "BM", "EP", "CF", "cfp", "SP", "GP", "Cash", "CashProd",
        "BookLeverage", "Leverage", "ChAssetTurnover", "ChTax", "InvGrowth",
        "DelCOA", "DelCOL", "DelEqu", "DelFINL", "DelLTI", "DelNetFin",
        "RD", "AdExp", "SurpriseRD", "Investment", "GrSaleToGrInv",
        "PayoutYield", "NetPayoutYield", "NetEquityFinance",
        "CompositeDebtIssuance", "DebtIssuance", "NetDebtFinance",
        "NetDebtPrice", "OPLeverage", "OperProf", "XFIN", "ShareIss1Y",
        "ShareIss5Y", "tang",
    }

    assert all(result[name].status != "exact" for name in materially_incomplete)
    assert result["CF"].formula_id == "net_income_plus_depreciation_over_market_cap"
    assert result["Leverage"].formula_id == "liabilities_over_market_cap"
    assert result["grcapx"].formula_id == "capex_growth_vs_two_years_ago"
    assert result["grcapx3y"].formula_id == "capex_over_prior_three_year_capex"
    assert result["hire"].formula_id == "employee_change_over_two_year_average"
    assert result["RDS"].status == "unavailable"
    assert result["RDS"].raw_value is None


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


def test_accounting_freshness_is_attached_per_feature_and_stale_input_fails_closed() -> None:
    concepts = {
        "assets": [100.0, 90.0],
        "equity": [60.0],
    }
    inputs = pd.DataFrame(
        {
            "concept": ["assets", "assets", "equity"],
            "concept_lag": [0, 1, 0],
            "available_at": ["2024-01-01", "2023-01-01", "2026-07-01"],
        }
    )
    calculated = calculate_accounting_features(concepts, market_cap=200.0)

    result = apply_accounting_input_freshness(
        calculated,
        inputs,
        as_of=pd.Timestamp("2026-08-03"),
        maximum_age_days=550,
    )

    assert result["AssetGrowth"].status == "unavailable"
    assert result["AssetGrowth"].raw_value is None
    assert result["AssetGrowth"].source == "stale_sec_accounting_input"
    assert result["BM"].raw_value == pytest.approx(0.3)
    assert result["BM"].available_at.startswith("2026-07-01")


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


def test_options_use_fresh_near_money_contracts_and_annualized_realized_vol() -> None:
    as_of = pd.Timestamp("2026-08-01")
    rows = pd.DataFrame(
        {
            "option_type": ["call", "put", "call", "put"],
            "expiration": ["2026-08-28"] * 4,
            "lastTradeDate": ["2026-07-31", "2026-07-31", "2025-01-01", "2026-07-31"],
            "strike": [100.0, 100.0, 100.0, 300.0],
            "impliedVolatility": [0.30, 0.40, 9.0, 0.50],
            "volume": [10, 20, 999, 999],
            "openInterest": [100, 200, 999, 999],
            "bid": [1.0, 1.0, 1.0, 2.0],
            "ask": [1.2, 1.2, 1.2, 1.0],
        }
    )

    result = _options_features(
        rows,
        1_000.0,
        0.01,
        stock_price=100.0,
        as_of=as_of,
        config={"yfinance": {}},
    )

    assert result["CPVolSpread"].raw_value == pytest.approx(-0.10)
    assert result["OptionVolume1"].raw_value == pytest.approx(0.03)
    assert result["RIVolSpread"].raw_value == pytest.approx(0.01 * np.sqrt(252) - 0.35)


def test_options_fail_closed_when_chain_is_too_shallow_or_open_interest_is_zero() -> None:
    as_of = pd.Timestamp("2026-08-01")
    rows = pd.DataFrame(
        {
            "option_type": ["call", "put"],
            "expiration": ["2026-08-28", "2026-08-28"],
            "lastTradeDate": ["2026-07-31", "2026-07-31"],
            "strike": [100.0, 100.0],
            "impliedVolatility": [0.30, 0.40],
            "volume": [10.0, 20.0],
            "openInterest": [0.0, 0.0],
            "bid": [1.0, 1.0],
            "ask": [1.2, 1.2],
        }
    )

    result = _options_features(
        rows,
        1_000.0,
        0.01,
        stock_price=100.0,
        as_of=as_of,
        config={"yfinance": {"minimum_option_contracts_per_side": 2}},
    )

    assert result == {}


def test_sec_issuer_flags_detect_foreign_and_investment_company_forms() -> None:
    submissions = pd.DataFrame(
        {
            "cik": [1, 1, 2, 3],
            "form": ["10-K", "20-F", "N-CSR", "10-Q"],
            "state_of_incorporation": ["DE", "DE", "", "CA"],
            "business_state_or_country": ["NY", "NY", "", "CA"],
        }
    )

    flags = _sec_issuer_flags(submissions).set_index("cik")

    assert bool(flags.at[1, "sec_foreign_filer"])
    assert bool(flags.at[2, "sec_investment_company"])
    assert not bool(flags.at[3, "sec_foreign_filer"])
    assert bool(flags.at[3, "sec_us_domicile_evidence"])


def test_submission_rows_preserve_sec_domicile_evidence() -> None:
    rows = _submission_rows(
        {
            "entityType": "operating",
            "stateOfIncorporation": "DE",
            "addresses": {"business": {"stateOrCountry": "CA"}},
            "filings": {
                "recent": {
                    "accessionNumber": ["0001"],
                    "filingDate": ["2026-01-01"],
                    "form": ["10-K"],
                }
            },
        },
        1,
    )

    assert rows[0]["state_of_incorporation"] == "DE"
    assert rows[0]["business_state_or_country"] == "CA"


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


def test_security_eligibility_accepts_missing_yahoo_country_with_sec_us_evidence() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["DOMESTIC", "UNKNOWN"],
            "cik": [1, 2],
            "company_name_sec": ["Domestic Inc", "Unknown Inc"],
            "longName": ["Domestic Inc", "Unknown Inc"],
            "quoteType": ["EQUITY", "EQUITY"],
            "country_yahoo": [None, None],
            "sec_us_domicile_evidence": [True, False],
            "price_rows": [100, 100],
            "last_price_date": ["2026-08-01", "2026-08-01"],
            "marketCap": [1_000, 1_000],
        }
    )

    result = _classify_security_eligibility(
        frame, as_of=pd.Timestamp("2026-08-02")
    ).set_index("symbol")

    assert bool(result.at["DOMESTIC", "eligible_common_stock"])
    assert result.at["UNKNOWN", "eligibility_reason"] == (
        "country_unavailable_without_sec_us_evidence"
    )


def test_security_eligibility_excludes_suffixes_and_foreign_filers() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["GOOD", "GOOD-PB", "UNIT-UN", "FOREIGN"],
            "cik": [1, 1, 2, 3],
            "company_name_sec": ["Good Inc", "Good Preferred", "Unit Corp", "Foreign Inc"],
            "longName": ["Good Inc", "Good Preferred", "Unit Corp", "Foreign Inc"],
            "quoteType": ["EQUITY"] * 4,
            "country_yahoo": ["United States"] * 4,
            "price_rows": [300] * 4,
            "last_price_date": ["2026-08-01"] * 4,
            "marketCap": [1_000, 500, 500, 500],
            "sec_foreign_filer": [False, False, False, True],
            "sec_investment_company": [False] * 4,
        }
    )

    result = _classify_security_eligibility(frame, as_of=pd.Timestamp("2026-08-02")).set_index("symbol")

    assert bool(result.at["GOOD", "eligible_common_stock"])
    assert result.at["GOOD-PB", "eligibility_reason"] == "excluded_name_or_instrument"
    assert result.at["UNIT-UN", "eligibility_reason"] == "excluded_name_or_instrument"
    assert result.at["FOREIGN", "eligibility_reason"] == "excluded_foreign_sec_filer"


def test_security_eligibility_keeps_valid_common_share_classes_for_same_cik() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["GOOG", "GOOGL"],
            "cik": [1, 1],
            "company_name_sec": ["Alphabet Inc", "Alphabet Inc"],
            "longName": ["Alphabet Inc Class C", "Alphabet Inc Class A"],
            "quoteType": ["EQUITY", "EQUITY"],
            "country_yahoo": ["United States", "United States"],
            "price_rows": [300, 300],
            "last_price_date": ["2026-08-01", "2026-08-01"],
            "marketCap": [2_000, 2_100],
            "sec_foreign_filer": [False, False],
            "sec_investment_company": [False, False],
        }
    )

    result = _classify_security_eligibility(
        frame, as_of=pd.Timestamp("2026-08-02")
    ).set_index("symbol")

    assert result["eligible_common_stock"].all()
    assert result["issuer_share_class_count"].eq(2).all()
    assert result["issuer_primary_security"].sum() == 1


def test_chunk_hash_manifest_uses_three_digit_suffix(tmp_path: Path) -> None:
    path = tmp_path / "prices_007.parquet"
    path.write_bytes(b"auditable")

    result = _hashes_by_chunk([path])

    assert set(result) == {7}
    assert len(result[7]) == 64


def test_database_contract_covers_every_object_and_creates_unique_index(
    tmp_path: Path,
) -> None:
    import duckdb

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE prices_daily_raw(symbol VARCHAR, date DATE, adj_close DOUBLE)"
    )
    connection.execute("CREATE VIEW prices_daily AS SELECT * FROM prices_daily_raw")

    contract_rows, index_rows, violations = finalize_database_contract(
        connection,
        tmp_path,
        required_tables={"prices_daily_raw"},
    )
    contract = pd.read_csv(tmp_path / "schema_contract.csv")
    checks = pd.read_csv(tmp_path / "database_contract_checks.csv")
    table_info = connection.execute("PRAGMA table_info('prices_daily_raw')").df()

    assert contract_rows == 5
    assert index_rows == 1
    assert violations == 0
    assert set(contract["table_name"]) == {
        "database_contract_checks", "index_contract", "prices_daily",
        "prices_daily_raw", "schema_contract",
    }
    assert set(table_info.loc[table_info["notnull"], "name"]) == {
        "symbol", "date", "adj_close",
    }
    physical = checks.loc[
        (checks["table_name"] == "prices_daily_raw")
        & (checks["check_type"] == "physical_not_null_constraint")
    ]
    assert len(physical) == 1
    assert bool(physical.iloc[0]["passed"])
    with pytest.raises(duckdb.ConstraintException):
        connection.execute(
            "INSERT INTO prices_daily_raw(symbol, date, adj_close) "
            "VALUES (NULL, DATE '2026-08-01', 1.0)"
        )


def test_database_contract_uses_true_quality_keys_and_preserves_raw_options() -> None:
    assert current_runner.DATABASE_UNIQUE_KEYS["price_quality_current"] == ("symbol",)
    assert current_runner.DATABASE_UNIQUE_KEYS["data_quality_current"] == ("symbol",)
    assert "yahoo_options_raw" not in current_runner.DATABASE_UNIQUE_KEYS
    assert current_runner.DATABASE_UNIQUE_KEYS["yahoo_options_usable"] == (
        "contractSymbol",
    )


def test_options_quality_quarantines_yahoo_identity_mismatches() -> None:
    import duckdb

    connection = duckdb.connect()
    connection.execute("CREATE TABLE security_master(symbol VARCHAR, current_price DOUBLE)")
    connection.execute("INSERT INTO security_master VALUES ('AAA', 10.0)")
    rows = pd.DataFrame(
        [
            {
                "contractSymbol": "AAA260918C00010000",
                "symbol": "AAA",
                "option_type": "call",
                "expiration": "2026-09-18",
            },
            {
                "contractSymbol": "AAA260918C00010000",
                "symbol": "AAA",
                "option_type": "call",
                "expiration": "2026-08-21",
            },
            {
                "contractSymbol": "BBB260918C00010000",
                "symbol": "AAA",
                "option_type": "call",
                "expiration": "2026-09-18",
            },
        ]
    )
    rows["lastTradeDate"] = pd.Timestamp("2026-08-01", tz="UTC")
    rows["strike"] = 10.0
    rows["bid"] = 1.0
    rows["ask"] = 1.1
    rows["impliedVolatility"] = 0.25
    rows["retrieved_at"] = "2026-08-03T12:00:00+00:00"
    connection.register("option_rows", rows)
    connection.execute(
        "CREATE TABLE yahoo_options_raw AS SELECT * FROM option_rows"
    )
    connection.unregister("option_rows")
    config = {
        "yfinance": {
            "minimum_option_days": 1,
            "maximum_option_days": 120,
            "minimum_implied_volatility": 0.001,
            "maximum_implied_volatility": 5.0,
            "maximum_option_staleness_days": 30,
            "minimum_option_moneyness": 0.5,
            "maximum_option_moneyness": 1.5,
        }
    }

    create_options_quality_tables(
        connection,
        as_of=pd.Timestamp("2026-08-03", tz="UTC"),
        config=config,
    )

    statuses = connection.execute(
        "SELECT quality_status, COUNT(*) n FROM yahoo_options_quality "
        "GROUP BY quality_status ORDER BY quality_status"
    ).fetchall()
    assert statuses == [
        ("contract_expiration_mismatch", 1),
        ("contract_underlying_mismatch", 1),
        ("usable_candidate", 1),
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM yahoo_options_usable"
    ).fetchone()[0] == 1


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


def test_score_family_cap_is_applied_after_normalisation() -> None:
    metadata = _metadata(rows=12)
    metadata["Cat.Economic"] = ["dominant"] * 5 + [f"family_{i}" for i in range(7)]
    groups = pd.DataFrame(
        {
            "signalname": metadata["signalname"],
            "redundancy_group": [f"group_{i}" for i in range(12)],
        }
    )
    values = {
        f"S{symbol_index:03d}": {
            signal: FeatureValue(
                signal,
                float(symbol_index + signal_index / 100.0),
                "exact",
                "test",
                f"formula_{signal_index}",
            )
            for signal_index, signal in enumerate(metadata["signalname"])
        }
        for symbol_index in range(20)
    }

    features = assemble_feature_table(
        metadata,
        values,
        as_of="2026-08-01",
        redundancy_groups=groups,
    )
    scores = calculate_scores(features, minimum_metrics=5, maximum_family_weight=0.15)
    horizon = scores.loc[scores["horizon_months"].eq(1)]

    assert horizon["maximum_family_weight_actual"].le(0.15 + 1e-12).all()


def test_redundancy_group_uses_one_dominant_economic_family() -> None:
    metadata = _metadata(rows=8)
    metadata["Cat.Economic"] = ["dominant", "other"] + [
        f"family_{index}" for index in range(6)
    ]
    metadata.loc[0, "tstat"] = 8.0
    metadata.loc[1, "tstat"] = 2.0
    groups = pd.DataFrame(
        {
            "signalname": metadata["signalname"],
            "redundancy_group": ["mixed", "mixed"]
            + [f"group_{index}" for index in range(6)],
        }
    )
    values = {
        f"S{symbol_index:03d}": {
            signal: FeatureValue(
                signal,
                float(symbol_index + signal_index / 100.0),
                "exact",
                "test",
                f"formula_{signal_index}",
            )
            for signal_index, signal in enumerate(metadata["signalname"])
        }
        for symbol_index in range(20)
    }

    features = assemble_feature_table(
        metadata,
        values,
        as_of="2026-08-01",
        redundancy_groups=groups,
    )
    scores = calculate_scores(features, minimum_metrics=5)
    contributions = scores.attrs["score_contributions"]
    mixed = contributions.loc[contributions["redundancy_group"].eq("mixed")]

    assert set(mixed["group_economic_family"]) == {"dominant"}


def test_score_exposes_raw_value_but_primary_score_is_cross_sectional_percentile() -> None:
    metadata = _metadata(5)
    values = {
        f"S{symbol_index:03d}": {
            signal: FeatureValue(signal, float(symbol_index), "exact", "test", signal)
            for signal in metadata["signalname"]
        }
        for symbol_index in range(11)
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")

    scores = calculate_scores(features, minimum_metrics=5)
    horizon = scores.loc[scores["horizon_months"].eq(1)].sort_values("symbol")

    assert "raw_score" in horizon.columns
    assert horizon["score"].min() == pytest.approx(0.0)
    assert horizon["score"].max() == pytest.approx(100.0)
    assert horizon["score"].is_monotonic_increasing
    contributions = scores.attrs["score_contributions"]
    contribution_totals = (
        contributions.loc[contributions["horizon_months"].eq(1)]
        .groupby("symbol")["raw_score_contribution"]
        .sum()
    )
    raw_scores = horizon.set_index("symbol")["raw_score"]
    pd.testing.assert_series_equal(
        contribution_totals.sort_index(),
        raw_scores.sort_index(),
        check_names=False,
    )


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
    feature = features.loc[features["signalname"].eq("signal_000")].iloc[0]
    assert feature["implementation_status"] == "exact"
    assert feature["value_status"] == "missing"
    assert feature["status"] == "unavailable"


def test_coverage_marks_mixed_exact_and_proxy_rows_explicitly() -> None:
    metadata = _metadata()
    values = {
        "AAA": {"signal_000": FeatureValue("signal_000", 1.0, "exact", "sec", "f")},
        "BBB": {"signal_000": FeatureValue("signal_000", 2.0, "proxy", "yahoo", "f")},
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")

    report = coverage_report(features, metadata)

    assert report.loc[report["signalname"].eq("signal_000"), "coverage_status"].iloc[0] == "mixed"


def test_scores_include_all_buckets_but_do_not_lower_minimum_silently() -> None:
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
    assert aaa["score"].isna().all()
    assert aaa["confidence"].eq(0).all()
    assert not aaa["horizon_evidence_sufficient"].any()


def test_scores_use_fixed_denominator_when_one_symbol_lacks_a_metric() -> None:
    metadata = _metadata(5)
    values = {
        "AAA": {
            f"signal_{index:03d}": FeatureValue(
                f"signal_{index:03d}", float(index + 1), "exact", "test", f"f{index}"
            )
            for index in range(5)
        },
        "BBB": {
            f"signal_{index:03d}": FeatureValue(
                f"signal_{index:03d}", float(index), "exact", "test", f"f{index}"
            )
            for index in range(4)
        },
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")

    scores = calculate_scores(features, minimum_metrics=1)
    rows = scores.loc[scores["horizon_months"].eq(1)].set_index("symbol")

    assert rows.at["AAA", "metrics_expected"] == rows.at["BBB", "metrics_expected"] == 5
    assert rows.at["AAA", "groups_expected"] == rows.at["BBB", "groups_expected"] == 5
    assert rows.at["BBB", "confidence"] < rows.at["AAA", "confidence"]


def test_aggregate_score_keeps_partial_research_score_but_rejects_ranking() -> None:
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

    result = calculate_aggregate_scores(scores, required_horizons=[1, 3]).iloc[0]

    assert result["aggregate_score"] == pytest.approx((80.0 + 30.0) / 1.5)
    assert result["horizons_used"] == 2
    assert result["aggregate_confidence"] == pytest.approx(75.0)
    assert bool(result["ranking_eligible"])
    assert result["ranking_rejection_reason"] == ""
    assert result["score_validation_status"] == "unvalidated_current_snapshot_only"


def test_aggregate_score_requires_all_horizons_and_minimum_confidence() -> None:
    scores = pd.DataFrame(
        {
            "as_of": ["2026-08-01"] * 5,
            "symbol": ["AAA"] * 5,
            "horizon_months": [1, 3, 6, 12, 36],
            "score": [70.0] * 5,
            "confidence": [80.0] * 5,
        }
    )

    result = calculate_aggregate_scores(
        scores,
        minimum_horizons=2,
        required_horizons=[1, 12],
        minimum_confidence=30,
    ).iloc[0]

    assert bool(result["all_horizons_present"])
    assert bool(result["ranking_eligible"])


def test_workflow_contract_is_github_only_and_complete() -> None:
    text = Path(".github/workflows/openap-yfinance-sec-current-score.yml").read_text(encoding="utf-8")
    config = yaml.safe_load(
        Path("config/openap_yfinance_sec_current.yaml").read_text(encoding="utf-8")
    )
    assert "OpenAP Current Score YFinance SEC EDGAR" in text
    assert "YFINANCE_CHUNKS: \"48\"" in text
    assert "max-parallel: 16" in text
    assert "sec-bulk" in text
    assert "source_layout\"] == \"official_bulk_archive\"" in text
    assert "openap-sec-lake-0" in text
    assert "openap-sec-raw-0" in text
    assert "matrix:\n        chunk:" not in text[text.index("  sec:"):text.index("  merge:")]
    assert "openap-yfinance-sec-current-score-results" in text
    assert config["dataset_id"] == "openap_yfinance_sec_current_v2"
    assert config["universe"]["one_primary_security_per_cik"] is False
    assert config["execution"]["sec_chunks"] == 1
    assert config["execution"]["sec_max_parallel"] == 1
    assert "overall_redundancy_groups.csv" in text
    assert "locked_opened" in text
    assert "backtest_enabled" in text
    assert 'summary["companyfacts_rows"] > 0' in text
    assert 'summary["submissions_rows"] > 0' in text
    assert "sec_cik_universe.parquet" in text


def test_config_enforces_quality_and_score_evidence_thresholds() -> None:
    text = Path("config/openap_yfinance_sec_current.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    for requirement in (
        "minimum_market_cap_usd",
        "minimum_average_dollar_volume_21d",
        "minimum_clean_price_rows",
        "maximum_price_age_days",
        "minimum_horizons_for_ranking",
        "required_ranking_horizons",
        "ranking_score_mode",
        "horizon_semantics",
        "minimum_aggregate_confidence",
        "maximum_family_weight",
        "minimum_computed_features_for_ranking",
        "maximum_missing_features_for_ranking",
        "maximum_sec_age_days_for_ranking",
        "maximum_accounting_input_age_days_for_ranking",
        "minimum_option_contracts_per_side",
        "minimum_cross_sectional_nonmodal_fraction",
        "minimum_cross_sectional_observations",
        "minimum_cross_sectional_coverage_fraction",
    ):
        assert requirement in text
    assert config["score"]["minimum_aggregate_confidence"] >= 50
    assert config["score"]["minimum_computed_features_for_ranking"] >= 60
    assert config["score"]["maximum_missing_features_for_ranking"] <= 125
    assert config["score"]["maximum_sec_age_days_for_ranking"] <= 183
    assert config["score"]["maximum_accounting_input_age_days_for_ranking"] <= 550
    assert config["yfinance"]["minimum_option_contracts_per_side"] >= 2
    assert config["score"]["minimum_cross_sectional_observations"] >= 100
    assert config["score"]["minimum_cross_sectional_coverage_fraction"] >= 0.05
    assert config["execution"]["artifact_retention_days"] == 90


def test_repair_workflow_reuses_v2_source_and_refreshes_48_audited_api_shards() -> None:
    text = Path(
        ".github/workflows/openap-yfinance-sec-repair-merge.yml"
    ).read_text(encoding="utf-8")

    assert "source_run_id" in text
    assert "sec_artifact_run_id" in text
    assert 'SEC_CHUNKS: "48"' in text
    assert "matrix.chunk" in text
    assert "sec-chunk" in text
    assert "openap-sec-repair-lake-${{ matrix.chunk }}" in text
    assert "sec_source_layout" in text
    assert 'summary["sec_source_manifest_rows"] == 48' in text
    assert 'summary["sec_jina_fallback_downloads"] > 0' in text
    assert "Wait for all source YFinance artifacts" in text
    assert 'test "$yfinance_artifacts" -eq 48' in text
    assert 'test("^openap-yfinance-[0-9]+$")' in text
    assert "openap-yfinance-lake-" not in text
    assert "run-id: ${{ inputs.sec_artifact_run_id }}" in text
    assert 'test "$sec_artifacts" -eq 48' in text
    assert "score_horizons" in text
    assert "openap-yfinance-sec-current-score-results" in text
    assert "overall_redundancy_groups.csv" in text


def test_current_workflow_requires_short_interest_metadata_in_final_master() -> None:
    text = Path(".github/workflows/openap-yfinance-sec-current-score.yml").read_text(
        encoding="utf-8"
    )

    for field in (
        "sharesShort",
        "sharesShortPriorMonth",
        "shortRatio",
        "shortPercentOfFloat",
        "dateShortInterest",
        "sharesPercentSharesOut",
        "heldPercentInstitutions",
    ):
        assert field in text


def test_merge_uses_the_resolved_latest_completed_session_name() -> None:
    text = Path("scripts/run_openap_yfinance_sec_current.py").read_text(
        encoding="utf-8"
    )
    assert "latest_completed_us_session.date()" not in text
    assert "latest_completed_session.date().isoformat()" in text
