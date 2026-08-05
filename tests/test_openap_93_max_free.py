from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import json

import numpy as np
import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.research.openap_93.accounting_pipeline import (
    ACCOUNTING_IMPLEMENTED_SIGNALS,
    calculate_accounting_signals,
)
from aurora.research.openap_93.advanced_accounting_pipeline import (
    ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS,
    calculate_advanced_accounting_signals,
)
from aurora.research.openap_93.analyst_pipeline import (
    ANALYST_IMPLEMENTED_SIGNALS,
    calculate_analyst_signals,
)
from aurora.research.openap_93.current_pipeline import (
    IMPLEMENTED_SIGNALS,
    REQUIRED_SIGNAL_COLUMNS,
    SCORE_VARIANTS,
    _normalize_signal_results,
    build_coverage_report,
    build_validation_report,
)
from aurora.research.openap_93.event_pipeline import (
    EVENT_IMPLEMENTED_SIGNALS,
    calculate_event_signals,
)
from aurora.research.openap_93.external import (
    normalize_public_inputs,
    parse_ff48_sic_zip,
    parse_fred_csv,
    parse_french_zip,
    parse_openap_reference_zip,
    parse_pastor_stambaugh,
)
from aurora.research.openap_93.http import SEC_USER_AGENT, public_headers
from aurora.research.openap_93.institutional_pipeline import (
    INSTITUTIONAL_IMPLEMENTED_SIGNALS,
    calculate_institutional_signals,
    map_cusips_openfigi,
    parse_13f_archives,
)
from aurora.research.openap_93.market import (
    beta_liquidity_ps,
    beta_vix,
    compound_lags,
    coskew_acx,
    coskewness_60m,
    ff3_month_residual_moments,
    price_delay_rsq,
    residual_momentum,
    zero_trade_measure,
)
from aurora.research.openap_93.market_pipeline import (
    MARKET_IMPLEMENTED_SIGNALS,
    calculate_market_signals,
)
from aurora.research.openap_93.models import SignalObservation
from aurora.research.openap_93.quarterly_pipeline import (
    QUARTERLY_IMPLEMENTED_SIGNALS,
    calculate_quarterly_signals,
)
from aurora.research.openap_93.short_interest_pipeline import (
    SHORT_INTEREST_IMPLEMENTED_SIGNALS,
    calculate_short_interest_signals,
)
from aurora.research.openap_93.registry import REQUIRED_93, FidelityClass, load_signal_registry
from aurora.research.openap_93.sources import (
    IMPLEMENTED_SIGNAL_SOURCES,
    PUBLIC_SOURCES,
    TEST_SYMBOLS,
    implemented_signal_requirements,
    probe_symbol_coverage,
    select_sources_lexicographically,
    source_coverage_matrix,
)


CONFIG = Path("config/openap_93/signals_93.yaml")


def implemented_signals() -> frozenset[str]:
    return frozenset(
        MARKET_IMPLEMENTED_SIGNALS
        | ACCOUNTING_IMPLEMENTED_SIGNALS
        | ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS
        | ANALYST_IMPLEMENTED_SIGNALS
        | EVENT_IMPLEMENTED_SIGNALS
        | QUARTERLY_IMPLEMENTED_SIGNALS
        | SHORT_INTEREST_IMPLEMENTED_SIGNALS
        | INSTITUTIONAL_IMPLEMENTED_SIGNALS
    )


def test_current_pipeline_contract_has_three_scores_and_all_implemented_signals() -> None:
    assert set(SCORE_VARIANTS) == {
        "score_strict_current",
        "score_max_current",
        "score_research_all",
    }
    assert IMPLEMENTED_SIGNALS == implemented_signals()
    assert {
        "security_id",
        "ticker",
        "cik",
        "formation_at",
        "period_end",
        "available_at",
        "value",
        "fidelity_class",
        "source_id",
        "coverage_flag",
    } <= set(REQUIRED_SIGNAL_COLUMNS)


def test_current_only_values_do_not_promote_a_proxy_without_overlap() -> None:
    signals = pd.DataFrame(
        {
            "signal": list(REQUIRED_93),
            "value": [1.0] + [np.nan] * 92,
            "fidelity_class": [FidelityClass.UNVALIDATED_PROXY.value]
            + [FidelityClass.UNAVAILABLE.value] * 92,
        }
    )
    validation = build_validation_report(signals)
    assert len(validation) == 93
    assert not validation["validated_proxy_threshold_pass"].any()
    assert validation.loc[validation["signal"].eq(REQUIRED_93[0]), "validation_status"].iat[0] == (
        "unvalidated_proxy_no_qualifying_overlap"
    )


def test_official_reference_without_permno_crosswalk_fails_closed() -> None:
    signals = pd.DataFrame(
        {
            "signal": list(REQUIRED_93),
            "value": [1.0] + [np.nan] * 92,
            "fidelity_class": [FidelityClass.UNVALIDATED_PROXY.value]
            + [FidelityClass.UNAVAILABLE.value] * 92,
        }
    )
    reference = pd.DataFrame(
        {"permno": [10001], "yyyymm": [202412], REQUIRED_93[0]: [0.25]}
    )
    validation = build_validation_report(signals, reference)
    assert validation["reference_rows_inspected"].eq(1).all()
    assert validation["reference_identifier"].eq("permno|yyyymm").all()
    assert not validation["identity_crosswalk_available"].any()
    assert validation["reason"].str.contains("no free authorized").all()
    assert not validation["validated_proxy_threshold_pass"].any()


def test_registry_contains_exactly_the_required_93() -> None:
    registry = load_signal_registry(CONFIG)
    assert set(REQUIRED_93) == set(registry)
    assert len(registry) == 93
    assert len(set(REQUIRED_93)) == 93


def test_every_signal_has_formula_inputs_sources_and_fidelity() -> None:
    registry = load_signal_registry(CONFIG)
    for signal in registry.values():
        assert signal.openap_script.startswith("Signals/pyCode/Predictors/")
        assert signal.required_inputs
        assert signal.natural_frequency
        assert isinstance(signal.expected_best_class, FidelityClass)
        if signal.expected_best_class is not FidelityClass.UNAVAILABLE:
            assert signal.candidate_sources


def test_every_unimplemented_signal_has_a_specific_blocker() -> None:
    registry = load_signal_registry(CONFIG)
    missing = {
        name
        for name, signal in registry.items()
        if name not in implemented_signals() and not signal.notes.strip()
    }
    assert missing == set()


def test_every_candidate_source_is_registered() -> None:
    registry = load_signal_registry(CONFIG)
    source_ids = {source.source_id for source in PUBLIC_SOURCES}
    referenced = {item for signal in registry.values() for item in signal.candidate_sources}
    assert referenced <= source_ids


def test_source_selection_is_deterministic_and_reports_ablation() -> None:
    registry = load_signal_registry(CONFIG)
    probes = pd.DataFrame(
        {"source_id": [source.source_id for source in PUBLIC_SOURCES], "probe_ok": True}
    )
    matrix = source_coverage_matrix(registry, probes)
    selected_a, ablation_a = select_sources_lexicographically(matrix)
    selected_b, ablation_b = select_sources_lexicographically(matrix)
    assert {key: value for key, value in selected_a.items() if key != "created_at"} == {
        key: value for key, value in selected_b.items() if key != "created_at"
    }
    pd.testing.assert_frame_equal(ablation_a, ablation_b)
    supported = implemented_signals()
    assert selected_a["candidate_signals_covered"] == len(supported)
    assert set(selected_a["candidate_signals_uncovered"]) == (
        set(REQUIRED_93) - supported
    )
    assert selected_a["selected_source_ids"]


def test_reachable_source_is_not_mistaken_for_implemented_signal() -> None:
    registry = load_signal_registry(CONFIG)
    probes = pd.DataFrame(
        {"source_id": [source.source_id for source in PUBLIC_SOURCES], "probe_ok": True}
    )
    matrix = source_coverage_matrix(registry, probes)
    assert IMPLEMENTED_SIGNAL_SOURCES
    assert matrix["candidate_match"].any()
    implemented = matrix.loc[matrix["formula_implemented"]]
    assert set(implemented["signal"]) == implemented_signals()
    assert implemented["required_fields_verified"].all()
    assert implemented["can_produce_value"].all()
    unimplemented = matrix.loc[~matrix["formula_implemented"]]
    assert not unimplemented["can_produce_value"].any()


def test_multisource_formulas_require_the_entire_bundle() -> None:
    registry = load_signal_registry(CONFIG)
    probes = pd.DataFrame(
        {"source_id": [source.source_id for source in PUBLIC_SOURCES], "probe_ok": True}
    )
    probes.loc[probes["source_id"].eq("kenneth_french"), "probe_ok"] = False
    matrix = source_coverage_matrix(registry, probes)
    beta_vix = matrix.loc[matrix["signal"].eq("betaVIX")]
    assert not beta_vix["can_produce_value"].any()
    requirements = implemented_signal_requirements()
    assert requirements["betaVIX"] == frozenset(
        {"cboe_public", "kenneth_french", "yahoo_public"}
    )


def test_registration_sources_are_audit_only_and_never_selectable() -> None:
    requirements = implemented_signal_requirements()
    implemented_sources = {
        source_id for source_ids in requirements.values() for source_id in source_ids
    }
    for source in PUBLIC_SOURCES:
        assert source.access_mode
        if source.registration_required:
            assert source.source_id not in implemented_sources
            assert source.automation_status.startswith("not_eligible_")


def test_every_source_has_an_explicit_five_company_probe_audit() -> None:
    cusip_to_symbol = {
        "037833100": "AAPL",
        "14448C104": "CARR",
        "50060P106": "KOP",
        "30303M102": "META",
        "75734B100": "RDDT",
    }

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        content = b"{}"
        text = "{}"

        def __init__(self, payload: Any) -> None:
            self._payload = payload

        def json(self) -> Any:
            return self._payload

    class FakeSession:
        def get(self, url: str, **_kwargs: Any) -> FakeResponse:
            return FakeResponse({"url": url})

        def post(
            self, _url: str, *, json: Sequence[Mapping[str, Any]], **_kwargs: Any
        ) -> FakeResponse:
            symbol = cusip_to_symbol[str(json[0]["idValue"])]
            return FakeResponse(
                [
                    {
                        "data": [
                            {
                                "ticker": symbol,
                                "marketSector": "Equity",
                                "securityType2": "Common Stock",
                                "exchCode": "US",
                            }
                        ]
                    }
                ]
            )

    session = FakeSession()
    for source in PUBLIC_SOURCES:
        rows = probe_symbol_coverage(source, session=session, timeout=1)
        assert len(rows) == len(TEST_SYMBOLS)
        assert {row["symbol"] for row in rows} == set(TEST_SYMBOLS)
        if source.source_id in {"yahoo_public", "nasdaq_public", "openfigi_public"}:
            assert all(row["probe_applicable"] for row in rows)
            assert all(row["probe_ok"] for row in rows)
        else:
            assert all(not row["probe_applicable"] for row in rows)
            assert all("not_symbol_scoped" in row["error"] for row in rows)


def test_sec_requests_use_an_identifiable_fair_access_contact() -> None:
    headers = public_headers(sec=True)
    assert headers["User-Agent"] == SEC_USER_AGENT
    assert "@" in SEC_USER_AGENT
    assert "github.com" not in SEC_USER_AGENT
    assert headers["Accept-Encoding"] == "gzip, deflate"


def test_script_is_blocked_locally_without_explicit_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    from scripts.run_openap_93_max_free import main

    monkeypatch.setattr("sys.argv", ["run_openap_93_max_free.py", "probe-sources", "--output-dir", "unused"])
    with pytest.raises(LocalRunBlocked):
        main()


def test_offline_execution_requires_the_complete_public_cache(tmp_path: Path) -> None:
    from scripts.run_openap_93_max_free import required_cached_inputs

    required = required_cached_inputs(tmp_path / "probe", tmp_path / "inputs")
    relative = {path.relative_to(tmp_path).as_posix() for path in required}
    assert len(relative) == 21
    assert "probe/source_probe_results.csv" in relative
    assert "probe/source_symbol_probe_results.csv" in relative
    assert "probe/sources.lock.json" in relative
    assert "inputs/public_inputs_manifest.json" in relative
    assert "inputs/normalized/ff3_daily.parquet" in relative
    assert "inputs/normalized/ff48_sic_codes.parquet" in relative
    assert "inputs/normalized/signal_doc.parquet" in relative
    assert "inputs/normalized/openap_reference_sample.parquet" in relative
    assert "inputs/normalized/sec_13f_filings.parquet" in relative
    assert "inputs/normalized/sec_13f_holdings.parquet" in relative
    assert "inputs/normalized/sec_13f_exclusions.parquet" in relative
    assert "inputs/normalized/openfigi_cusip_map.parquet" in relative
    assert "inputs/normalized/openap_reference_metadata.json" in relative
    assert "inputs/normalized/normalized_summary.json" in relative


def test_run_command_reuses_complete_cache_unless_refresh_is_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import scripts.run_openap_93_max_free as command

    output = tmp_path / "run"
    for path in command.required_cached_inputs(
        output / "source_probe", output / "public_inputs"
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cached")

    calls: list[str] = []
    monkeypatch.setattr(command, "probe_sources", lambda _args: calls.append("probe"))
    monkeypatch.setattr(
        command, "fetch_public_inputs", lambda _args: calls.append("fetch")
    )
    monkeypatch.setattr(command, "build_current", lambda _args: calls.append("build"))
    common = {
        "output_dir": str(output),
        "signals_config": str(CONFIG),
        "base_db": "unused.duckdb",
        "formation_date": "today",
        "universe_file": "",
        "signals": "",
        "offline": False,
    }

    command.run_all(argparse.Namespace(**common, refresh=False))
    assert calls == ["build"]

    calls.clear()
    command.run_all(argparse.Namespace(**common, refresh=True))
    assert calls == ["probe", "fetch", "build"]


def test_signal_observation_only_marks_evidenced_classes_usable() -> None:
    observation = SignalObservation(
        formation_date="2026-07-31",
        symbol="AAPL",
        signal="Coskewness",
        value=0.25,
        fidelity=FidelityClass.RECONSTRUCTED,
        current_usable=True,
        formula_id="openap_coskewness_60m",
        source_ids=("yahoo_public", "kenneth_french"),
        data_available_at="2026-08-01T00:00:00Z",
        observation_count=60,
    )
    assert observation.to_record()["fidelity"] == "reconstructed"
    assert observation.to_record()["source_ids"] == "yahoo_public|kenneth_french"
    with pytest.raises(ValueError, match="current_usable"):
        SignalObservation(
            formation_date="2026-07-31",
            symbol="AAPL",
            signal="AOP",
            value=1.0,
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            current_usable=True,
            formula_id="proxy",
            source_ids=("yahoo_public",),
            data_available_at="2026-08-01T00:00:00Z",
            observation_count=1,
        )


def test_market_formula_helpers_match_simple_known_cases() -> None:
    values = pd.Series([0.01] * 40)
    assert compound_lags(values, [1, 2, 3, 4, 5]) == pytest.approx(1.01**5 - 1)

    market = np.linspace(-0.04, 0.05, 60)
    stock = 0.5 * market + 4.0 * market**2
    assert coskewness_60m(stock, market) > 0


def test_official_ff48_archive_parser_requires_all_industries(tmp_path: Path) -> None:
    lines: list[str] = []
    for industry in range(1, 49):
        lines.extend(
            [
                f"{industry} I{industry:02d} Industry {industry}",
                f"{industry * 100:04d}-{industry * 100 + 9:04d} Synthetic range",
            ]
        )
    archive = tmp_path / "Siccodes48.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("Siccodes48.txt", "\n".join(lines))
    parsed = parse_ff48_sic_zip(archive)
    assert set(parsed["ff48"]) == set(range(1, 49))
    assert len(parsed) == 48

    daily_market = np.linspace(-0.03, 0.03, 252)
    daily_stock = 0.6 * daily_market + 3.0 * daily_market**2
    assert coskew_acx(daily_stock, daily_market) > 0


def test_sec_13f_parser_keeps_unambiguous_filings_and_excludes_additive_amendments(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "13f.zip"
    submission = pd.DataFrame(
        [
            {
                "ACCESSION_NUMBER": "0001",
                "FILING_DATE": "2025-08-14",
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": "0000000001",
                "PERIODOFREPORT": "2025-06-30",
            },
            {
                "ACCESSION_NUMBER": "0002",
                "FILING_DATE": "2025-11-14",
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": "0000000001",
                "PERIODOFREPORT": "2025-09-30",
            },
            {
                "ACCESSION_NUMBER": "0003",
                "FILING_DATE": "2025-11-10",
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": "0000000002",
                "PERIODOFREPORT": "2025-09-30",
            },
            {
                "ACCESSION_NUMBER": "0004",
                "FILING_DATE": "2025-11-20",
                "SUBMISSIONTYPE": "13F-HR/A",
                "CIK": "0000000002",
                "PERIODOFREPORT": "2025-09-30",
            },
            {
                "ACCESSION_NUMBER": "0005",
                "FILING_DATE": "2025-11-09",
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": "0000000003",
                "PERIODOFREPORT": "2025-09-30",
            },
            {
                "ACCESSION_NUMBER": "0006",
                "FILING_DATE": "2025-11-21",
                "SUBMISSIONTYPE": "13F-HR/A",
                "CIK": "0000000003",
                "PERIODOFREPORT": "2025-09-30",
            },
        ]
    )
    cover = pd.DataFrame(
        {
            "ACCESSION_NUMBER": ["0001", "0002", "0003", "0004", "0005", "0006"],
            "ISAMENDMENT": ["N", "N", "N", "Y", "N", "Y"],
            "AMENDMENTNO": ["", "", "", "1", "", "1"],
            "AMENDMENTTYPE": ["", "", "", "ADD NEW HOLDINGS", "", "RESTATEMENT"],
        }
    )
    infotable = pd.DataFrame(
        [
            {
                "ACCESSION_NUMBER": accession,
                "NAMEOFISSUER": f"Issuer {accession}",
                "TITLEOFCLASS": "COM",
                "CUSIP": f"0000000{index:02d}",
                "VALUE": "100",
                "SSHPRNAMT": "10",
                "SSHPRNAMTTYPE": "SH",
                "PUTCALL": "",
                "INVESTMENTDISCRETION": "SOLE",
            }
            for index, accession in enumerate(
                ["0001", "0002", "0003", "0004", "0005", "0006"], start=1
            )
        ]
    )
    with ZipFile(archive, "w") as handle:
        handle.writestr("SUBMISSION.tsv", submission.to_csv(sep="\t", index=False))
        handle.writestr("COVERPAGE.tsv", cover.to_csv(sep="\t", index=False))
        handle.writestr("INFOTABLE.tsv", infotable.to_csv(sep="\t", index=False))

    filings, holdings, exclusions = parse_13f_archives([archive])

    assert set(filings["accession_number"]) == {"0001", "0002", "0006"}
    assert set(holdings["accession_number"]) == {"0001", "0002", "0006"}
    assert exclusions["accession_number"].tolist() == ["0004"]
    assert exclusions["reason"].eq("non_restatement_or_ambiguous_amendment").all()


def test_openfigi_mapping_fails_closed_on_ambiguous_or_missing_matches(
    tmp_path: Path,
) -> None:
    def fake_post(
        url: str,
        payload: Sequence[Mapping[str, Any]],
        headers: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        assert url.endswith("/mapping")
        assert headers["Content-Type"] == "application/json"
        rows = []
        for job in payload:
            cusip = job["idValue"]
            if cusip == "037833100":
                rows.append(
                    {
                        "data": [
                            {
                                "ticker": "AAPL",
                                "marketSector": "Equity",
                                "securityType2": "Common Stock",
                                "exchCode": "US",
                            }
                        ]
                    }
                )
            elif cusip == "30303M102":
                rows.append(
                    {
                        "data": [
                            {
                                "ticker": "META",
                                "marketSector": "Equity",
                                "securityType2": "Common Stock",
                                "exchCode": "US",
                            },
                            {
                                "ticker": "META.A",
                                "marketSector": "Equity",
                                "securityType2": "Common Stock",
                                "exchCode": "US",
                            },
                        ]
                    }
                )
            else:
                rows.append({"data": []})
        return rows

    result = map_cusips_openfigi(
        ["037833100", "30303M102", "999999999"],
        output_checkpoint=tmp_path / "mapping.jsonl",
        http_post=fake_post,
        sleep=lambda _seconds: None,
    ).set_index("cusip")

    assert result.loc["037833100", "mapping_status"] == "mapped_unique"
    assert result.loc["037833100", "ticker"] == "AAPL"
    assert result.loc["30303M102", "mapping_status"] == "ambiguous"
    assert pd.isna(result.loc["30303M102", "ticker"])
    assert result.loc["999999999", "mapping_status"] == "no_common_stock_match"


def test_openfigi_request_failure_remains_resumable(tmp_path: Path) -> None:
    checkpoint = tmp_path / "mapping.jsonl"

    def failing_post(
        _url: str,
        _payload: Sequence[Mapping[str, Any]],
        _headers: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        raise OSError("temporary network failure")

    failed = map_cusips_openfigi(
        ["037833100"],
        output_checkpoint=checkpoint,
        http_post=failing_post,
        sleep=lambda _seconds: None,
    )
    assert failed.loc[0, "mapping_status"] == "request_failed"
    assert checkpoint.exists()

    def successful_post(
        _url: str,
        _payload: Sequence[Mapping[str, Any]],
        _headers: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "data": [
                    {
                        "ticker": "AAPL",
                        "marketSector": "Equity",
                        "securityType2": "Common Stock",
                        "exchCode": "US",
                    }
                ]
            }
        ]

    resumed = map_cusips_openfigi(
        ["037833100"],
        output_checkpoint=checkpoint,
        http_post=successful_post,
        sleep=lambda _seconds: None,
    )
    assert resumed.loc[0, "mapping_status"] == "mapped_unique"
    assert resumed.loc[0, "ticker"] == "AAPL"


def test_institutional_signals_use_lagged_13f_and_current_characteristics() -> None:
    formation = pd.Timestamp("2026-08-04")
    symbols = [f"I{index:02d}" for index in range(10)]
    managers = [f"M{index:02d}" for index in range(6)]
    master = pd.DataFrame(
        {
            "symbol": symbols,
            "exchange_sec": ["NYSE"] * len(symbols),
            "marketCap": np.linspace(
                1_000_000_000.0, 10_000_000_000.0, len(symbols)
            ),
            "sharesOutstanding": 1_000_000.0,
            "retrieved_at": pd.Timestamp("2026-08-01"),
        }
    )
    master.loc[master["symbol"].eq(symbols[-1]), "marketCap"] = np.nan
    filing_rows = []
    holding_rows = []
    periods = (
        (pd.Timestamp("2025-12-31"), pd.Timestamp("2026-01-30")),
        (pd.Timestamp("2026-03-31"), pd.Timestamp("2026-05-15")),
    )
    cusips = {symbol: f"00000{index:04d}" for index, symbol in enumerate(symbols)}
    for period_index, (period, filed_at) in enumerate(periods):
        for manager_index, manager in enumerate(managers):
            filing_rows.append(
                {
                    "accession_number": f"{period_index}-{manager_index}",
                    "manager_cik": manager,
                    "filing_date": filed_at,
                    "report_period": period,
                }
            )
            for symbol_index, symbol in enumerate(symbols):
                holder_limit = min(len(managers), 1 + symbol_index // 2 + period_index)
                if manager_index >= holder_limit:
                    continue
                holding_rows.append(
                    {
                        "accession_number": f"{period_index}-{manager_index}",
                        "manager_cik": manager,
                        "filing_date": filed_at,
                        "report_period": period,
                        "cusip": cusips[symbol],
                        "shares_held": 10_000.0 * (manager_index + 1),
                    }
                )
    filing_rows.append(
        {
            "accession_number": "future-amendment",
            "manager_cik": "M99",
            "filing_date": pd.Timestamp("2026-09-01"),
            "report_period": pd.Timestamp("2026-03-31"),
        }
    )
    holding_rows.append(
        {
            "accession_number": "future-amendment",
            "manager_cik": "M99",
            "filing_date": pd.Timestamp("2026-09-01"),
            "report_period": pd.Timestamp("2026-03-31"),
            "cusip": cusips[symbols[0]],
            "shares_held": 999_999.0,
        }
    )
    mapping = pd.DataFrame(
        {
            "cusip": list(cusips.values()),
            "ticker": symbols,
            "mapping_status": "mapped_unique",
        }
    )
    companyfacts = pd.DataFrame(
        {
            "symbol": symbols,
            "tag": "EntityCommonStockSharesOutstanding",
            "period_end": pd.Timestamp("2025-12-31"),
            # DuckDB returns this SEC timestamp as timezone-aware in the full run.
            "available_at": pd.Timestamp("2026-01-20", tz="UTC"),
            "value": 1_000_000.0,
        }
    )
    concept_rows = []
    for index, symbol in enumerate(symbols):
        for concept, value in (
            ("equity", 100_000_000.0 + index * 10_000_000.0),
            ("deferred_tax", 1_000_000.0),
            ("preferred_stock", 0.0),
        ):
            concept_rows.append(
                {
                    "symbol": symbol,
                    "concept": concept,
                    "concept_lag": 0,
                    "value": value,
                    "period_end": pd.Timestamp("2025-12-31"),
                    "available_at": pd.Timestamp("2026-03-01"),
                }
            )
    dates = pd.bdate_range("2025-07-01", "2026-07-31")
    rng = np.random.default_rng(2026)
    price_frames = []
    for index, symbol in enumerate(symbols):
        returns = rng.normal(0.0003, 0.004 + index * 0.001, len(dates))
        price_frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": dates,
                    "adj_close": 50.0 * np.cumprod(1.0 + returns),
                    "volume": 100_000.0 * (index + 1),
                }
            )
        )
    analyst = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "dataset": "earnings_estimate",
                "retrieved_at": "2026-08-01T00:00:00+00:00",
                "payload_json": json.dumps(
                    [
                        {
                            "period": "0y",
                            "low": 1.0,
                            "high": 1.1 + index * 0.1,
                            "avg": 1.0,
                        }
                    ]
                ),
            }
            for index, symbol in enumerate(symbols)
        ]
    )

    result = calculate_institutional_signals(
        master,
        pd.concat(price_frames, ignore_index=True),
        companyfacts,
        pd.DataFrame(concept_rows),
        analyst,
        pd.DataFrame(filing_rows),
        pd.DataFrame(holding_rows),
        mapping,
        formation_at=formation,
    )

    assert set(result["signal"]) == INSTITUTIONAL_IMPLEMENTED_SIGNALS
    assert result.groupby("symbol")["signal"].nunique().eq(5).all()
    assert pd.to_datetime(result["available_at"]).dropna().le(formation).all()
    breadth = result.loc[result["signal"].eq("DelBreadth")]
    assert pd.isna(breadth.loc[breadth["symbol"].eq("I00"), "value"].iat[0])
    assert not breadth.loc[breadth["symbol"].eq("I00"), "current_usable"].iat[0]
    assert breadth.loc[
        breadth["symbol"].eq("I00"), "reason_if_missing"
    ].iat[0] == "not_applicable:official_nyse_size_filter"
    assert breadth.loc[breadth["symbol"].eq("I02"), "value"].iat[0] == pytest.approx(
        100.0 / len(managers)
    )
    assert breadth.loc[breadth["symbol"].eq("I02"), "current_usable"].iat[0]
    for signal in ("RIO_MB", "RIO_Turnover", "RIO_Volatility"):
        rows = result.loc[result["signal"].eq(signal) & result["value"].notna()]
        assert not rows.empty
        assert pd.to_datetime(rows["available_at"]).ge(
            pd.Timestamp("2026-07-30")
        ).all()
        assert rows["fidelity_class"].eq(FidelityClass.RECONSTRUCTED.value).all()
        assert rows["current_usable"].all()
        assert pd.isna(
            result.loc[
                result["signal"].eq(signal)
                & result["symbol"].eq(symbols[-1]),
                "value",
            ].iat[0]
        )
    dispersion = result.loc[
        result["signal"].eq("RIO_Disp") & result["value"].notna()
    ]
    assert not dispersion.empty
    assert dispersion["fidelity_class"].eq(
        FidelityClass.UNVALIDATED_PROXY.value
    ).all()
    assert not dispersion["current_usable"].any()


def test_factor_and_delay_formulas_are_causal_and_finite() -> None:
    rng = np.random.default_rng(7)
    n = 260
    market = rng.normal(0, 0.01, n)
    lagged = np.r_[0.0, market[:-1]]
    stock = 0.4 * market + 0.6 * lagged + rng.normal(0, 0.002, n)
    delay = price_delay_rsq(stock, market)
    assert delay is not None and delay > 0

    vix = rng.normal(0, 0.05, n)
    stock_vix = 0.3 * market - 0.8 * vix + rng.normal(0, 0.002, n)
    assert beta_vix(stock_vix, market, vix) == pytest.approx(-0.8, abs=0.15)

    smb = rng.normal(0, 0.01, n)
    hml = rng.normal(0, 0.01, n)
    idio, skew = ff3_month_residual_moments(
        stock_vix[-21:], market[-21:], smb[-21:], hml[-21:]
    )
    assert idio is not None and idio > 0
    assert skew is not None and np.isfinite(skew)


def test_long_window_formulas_and_zero_trade_measure() -> None:
    rng = np.random.default_rng(11)
    n = 90
    ps = rng.normal(0, 0.02, n)
    market = rng.normal(0, 0.03, n)
    smb = rng.normal(0, 0.02, n)
    hml = rng.normal(0, 0.02, n)
    stock = 1.7 * ps + 0.3 * market + rng.normal(0, 0.003, n)
    assert beta_liquidity_ps(stock, ps, market, smb, hml) == pytest.approx(1.7, abs=0.1)
    assert residual_momentum(stock, market, smb, hml) is not None

    volume = np.ones(21)
    volume[[1, 4, 9]] = 0
    turnover = np.full(21, 0.01)
    value = zero_trade_measure(volume, turnover, expected_days=21, deflator=480_000)
    assert value is not None and value > 2.9


def test_public_factor_parsers_use_decimal_returns_and_official_liquidity(tmp_path: Path) -> None:
    from zipfile import ZipFile

    french = tmp_path / "ff.zip"
    with ZipFile(french, "w") as archive:
        archive.writestr(
            "ff.csv",
            "metadata\n,Mkt-RF,SMB,HML,RF\n20260731,1.00,-2.00,3.00,0.10\n",
        )
    frame = parse_french_zip(french, daily=True)
    assert frame.loc[0, "mktrf"] == pytest.approx(0.01)
    assert frame.loc[0, "smb"] == pytest.approx(-0.02)

    liquidity = tmp_path / "liq.txt"
    liquidity.write_text(
        "% header\n202606  -0.10  0.025  0.03\n202607  0.05  -0.015  0.01\n",
        encoding="utf-8",
    )
    parsed = parse_pastor_stambaugh(liquidity)
    assert parsed["ps_innovation"].tolist() == [0.025, -0.015]

    fred = tmp_path / "fred.csv"
    fred.write_text("observation_date,GNPDEF\n2026-01-01,125.7\n", encoding="utf-8")
    deflator = parse_fred_csv(fred, value_column="GNPDEF")
    assert deflator.loc[0, "gnpdef"] == pytest.approx(125.7)


def test_openap_reference_parser_keeps_permno_reference_only(tmp_path: Path) -> None:
    from zipfile import ZipFile

    archive_path = tmp_path / "openap.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "signed_predictors_dl_wide.csv",
            "permno,yyyymm,MS,AbnormalAccruals\n10001,202412,2.0,0.1\n",
        )
    frame, metadata = parse_openap_reference_zip(archive_path)
    assert frame.columns.tolist() == [
        "permno",
        "yyyymm",
        "MS",
        "AbnormalAccruals",
    ]
    assert metadata["reference_only"] is True
    assert metadata["current_signal_source"] is False
    assert metadata["identifier_columns"] == ["permno", "yyyymm"]


def test_market_pipeline_emits_all_supported_signals_without_lookahead() -> None:
    rng = np.random.default_rng(29)
    dates = pd.bdate_range("2018-01-01", "2026-07-31")
    symbols = [f"S{i:02d}" for i in range(12)]
    price_rows: list[pd.DataFrame] = []
    master_rows: list[dict[str, object]] = []
    market = rng.normal(0.0003, 0.01, len(dates))
    for index, symbol in enumerate(symbols):
        returns = 0.7 * market + rng.normal(0.0001 + index / 1_000_000, 0.008, len(dates))
        close = 20.0 * np.cumprod(1.0 + returns)
        first_session = ~pd.Series(dates).dt.to_period("M").duplicated().to_numpy()
        quarterly_dividend = (
            first_session & pd.Series(dates).dt.month.isin([2, 5, 8, 11]).to_numpy()
        )
        price_rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "close": close,
                    "adj_close": close,
                    "volume": np.where(
                        np.arange(len(dates)) % (31 + index) == 0,
                        0,
                        1_000_000 + index * 10_000,
                    ),
                    "dividends": np.where(
                        quarterly_dividend,
                        0.05 * (index + 1),
                        0.0,
                    ),
                }
            )
        )
        master_rows.append(
            {
                "symbol": symbol,
                "sharesOutstanding": 100_000_000 + index * 1_000_000,
                "first_clean_price_date": dates.min(),
                "marketCap": 2_000_000_000 + index * 500_000_000,
                "industry": f"industry_{index % 3}",
            }
        )
    prices = pd.concat(price_rows, ignore_index=True)
    ff3_daily = pd.DataFrame(
        {
            "date": dates,
            "mktrf": market,
            "smb": rng.normal(0, 0.004, len(dates)),
            "hml": rng.normal(0, 0.004, len(dates)),
            "rf": np.full(len(dates), 0.0001),
        }
    )
    months = pd.date_range("2018-01-31", "2026-07-31", freq="ME")
    ff3_monthly = pd.DataFrame(
        {
            "date": months,
            "mktrf": rng.normal(0.006, 0.035, len(months)),
            "smb": rng.normal(0, 0.02, len(months)),
            "hml": rng.normal(0, 0.02, len(months)),
            "rf": np.full(len(months), 0.002),
        }
    )
    liquidity = pd.DataFrame(
        {"date": months, "ps_innovation": rng.normal(0, 0.02, len(months))}
    )
    vix = pd.DataFrame(
        {"date": dates, "vix_change": rng.normal(0, 0.04, len(dates))}
    )

    result = calculate_market_signals(
        pd.DataFrame(master_rows),
        prices,
        ff3_daily,
        ff3_monthly,
        liquidity,
        vix,
        formation_at="2026-08-01",
    )

    assert set(result["signal"]) == MARKET_IMPLEMENTED_SIGNALS
    assert (
        result.groupby("symbol")["signal"]
        .nunique()
        .eq(len(MARKET_IMPLEMENTED_SIGNALS))
        .all()
    )
    assert pd.to_datetime(result["available_at"]).le(pd.Timestamp("2026-08-01")).all()
    proxy = result["fidelity_class"].eq(FidelityClass.UNVALIDATED_PROXY.value)
    assert not result.loc[proxy, "current_usable"].any()
    assert result.loc[result["current_usable"], "value"].notna().all()
    dividend = result.loc[result["signal"].eq("DivYieldST")]
    assert dividend["fidelity_class"].eq(FidelityClass.RECONSTRUCTED.value).all()
    assert dividend["current_usable"].all()
    assert set(dividend["value"].dropna().unique()).issubset({1.0, 2.0, 3.0})


def test_accounting_pipeline_emits_registered_subset_and_fails_closed() -> None:
    symbols = [f"A{i:02d}" for i in range(12)]
    master = pd.DataFrame(
        {
            "symbol": symbols,
            "marketCap": [1_000_000_000 + index * 50_000_000 for index in range(12)],
            "industry": [f"industry_{index % 3}" for index in range(12)],
            "sic_sec": [3571] * 12,
        }
    )
    concepts = (
        "assets",
        "liabilities",
        "equity",
        "cash",
        "current_assets",
        "current_liabilities",
        "inventory",
        "receivables",
        "revenue",
        "cogs",
        "net_income",
        "operating_cash_flow",
        "financing_cash_flow",
        "investing_cash_flow",
        "repurchases",
        "share_issuance",
        "dividends",
        "capex",
        "depreciation",
        "rd",
        "sga",
        "tax",
        "debt_long",
        "operating_income",
        "shares",
        "backlog",
        "employees",
    )
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(symbols):
        for concept_index, concept in enumerate(concepts):
            base = 100.0 + symbol_index * 2 + concept_index
            for lag in (0, 1, 2):
                rows.append(
                    {
                        "symbol": symbol,
                        "concept": concept,
                        "concept_lag": lag,
                        "value": base * (1.0 - 0.03 * lag),
                        "available_at": pd.Timestamp("2026-06-15")
                        - pd.DateOffset(years=lag),
                        "period_end": pd.Timestamp("2025-12-31")
                        - pd.DateOffset(years=lag),
                    }
                )

    result = calculate_accounting_signals(
        master,
        pd.DataFrame(rows),
        formation_at="2026-07-31",
        gnp_deflator=125.0,
    )

    assert set(result["signal"]) == ACCOUNTING_IMPLEMENTED_SIGNALS
    assert result.groupby("symbol")["signal"].nunique().eq(
        len(ACCOUNTING_IMPLEMENTED_SIGNALS)
    ).all()
    assert pd.to_datetime(result["available_at"]).le(pd.Timestamp("2026-07-31")).all()
    proxy = result["fidelity_class"].eq(FidelityClass.UNVALIDATED_PROXY.value)
    assert not result.loc[proxy, "current_usable"].any()
    reconstructed = result["fidelity_class"].eq(FidelityClass.RECONSTRUCTED.value)
    assert result.loc[reconstructed & result["value"].notna(), "current_usable"].all()


def test_pct_total_accrual_reproduces_openap_formula_and_requires_every_input() -> None:
    master = pd.DataFrame(
        {
            "symbol": ["FULL", "MISSING"],
            "marketCap": [1_000_000_000.0, 1_000_000_000.0],
            "industry": ["industrial", "industrial"],
            "sic_sec": [3571, 3571],
        }
    )
    inputs = {
        "net_income": 100.0,
        "repurchases": 20.0,
        "share_issuance": 5.0,
        "dividends": 10.0,
        "operating_cash_flow": 90.0,
        "financing_cash_flow": -25.0,
        "investing_cash_flow": -30.0,
    }
    rows = []
    for symbol in ("FULL", "MISSING"):
        for concept, value in inputs.items():
            if symbol == "MISSING" and concept == "investing_cash_flow":
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "concept": concept,
                    "concept_lag": 0,
                    "value": value,
                    "available_at": pd.Timestamp("2026-03-01"),
                    "period_end": pd.Timestamp("2025-12-31"),
                }
            )

    result = calculate_accounting_signals(
        master,
        pd.DataFrame(rows),
        formation_at="2026-07-31",
        gnp_deflator=125.0,
    )
    pct = result.loc[result["signal"].eq("PctTotAcc")].set_index("symbol")

    assert pct.loc["FULL", "value"] == pytest.approx(0.40)
    assert pct.loc["FULL", "fidelity_class"] == FidelityClass.RECONSTRUCTED.value
    assert bool(pct.loc["FULL", "current_usable"])
    assert pd.isna(pct.loc["MISSING", "value"])
    assert pct.loc["MISSING", "fidelity_class"] == FidelityClass.UNAVAILABLE.value
    assert not bool(pct.loc["MISSING", "current_usable"])


def test_advanced_accounting_reconstructs_current_formulas_causally() -> None:
    symbols = [f"M{i:02d}" for i in range(15)]
    master = pd.DataFrame(
        {
            "symbol": symbols,
            "cik": np.arange(1, len(symbols) + 1),
            "first_price_date": pd.Timestamp("2018-01-02"),
        }
    )
    submissions = pd.DataFrame(
        {
            "cik": master["cik"],
            "accepted_at": pd.Timestamp("2025-03-01"),
            "sic": [3571] * len(symbols),
        }
    )
    tag_values = {
        "Assets": 1000.0,
        "AssetsCurrent": 450.0,
        "CashAndCashEquivalentsAtCarryingValue": 120.0,
        "Liabilities": 600.0,
        "LiabilitiesCurrent": 180.0,
        "LongTermDebtCurrent": 35.0,
        "LongTermDebtNoncurrent": 220.0,
        "LongTermInvestments": 50.0,
        "NetIncomeLoss": 90.0,
        "NetCashProvidedByUsedInOperatingActivities": 110.0,
        "OperatingIncomeLoss": 135.0,
        "PropertyPlantAndEquipmentNet": 300.0,
        "RevenueFromContractWithCustomerExcludingAssessedTax": 1500.0,
        "StockholdersEquity": 400.0,
        "EntityCommonStockSharesOutstanding": 20.0,
        "ResearchAndDevelopmentExpense": 80.0,
        "PaymentsToAcquirePropertyPlantAndEquipment": 70.0,
        "SellingGeneralAndAdministrativeExpense": 140.0,
        "ShortTermInvestments": 30.0,
        "AdvertisingExpense": 25.0,
        "DepreciationDepletionAndAmortization": 40.0,
        "PreferredStockValue": 5.0,
    }
    facts: list[dict[str, object]] = []
    for symbol_index, (symbol, cik) in enumerate(zip(symbols, master["cik"], strict=True)):
        for year_index, year in enumerate(range(2018, 2026)):
            period_end = pd.Timestamp(year, 12, 31)
            for tag, base in tag_values.items():
                value = base * (1.0 + 0.035 * year_index + 0.004 * symbol_index)
                if tag == "NetCashProvidedByUsedInOperatingActivities":
                    value *= 1.0 + 0.01 * symbol_index
                facts.append(
                    {
                        "symbol": symbol,
                        "cik": cik,
                        "tag": tag,
                        "value": value,
                        "period_start": pd.Timestamp(year, 1, 1),
                        "period_end": period_end,
                        "form": "10-K",
                        "filed": period_end + pd.Timedelta(days=60),
                        "available_at": period_end + pd.Timedelta(days=60),
                    }
                )
    dates = pd.bdate_range("2018-01-02", "2026-07-31")
    prices = pd.concat(
        [
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": dates,
                    "close": np.linspace(25.0 + index, 80.0 + index, len(dates)),
                    "adj_close": np.linspace(25.0 + index, 80.0 + index, len(dates)),
                }
            )
            for index, symbol in enumerate(symbols)
        ],
        ignore_index=True,
    )
    gnp = pd.DataFrame(
        {"date": pd.date_range("2018-01-01", "2026-01-01", freq="YS"), "gnpdef": 120.0}
    )

    result = calculate_advanced_accounting_signals(
        master,
        pd.DataFrame(facts),
        submissions,
        prices,
        gnp,
        pd.DataFrame(
            {
                "ff48": [35],
                "sic_start": [3570],
                "sic_end": [3579],
            }
        ),
        formation_at="2026-07-31",
    )

    assert set(result["signal"]) == ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS
    assert result.groupby("symbol")["signal"].nunique().eq(
        len(ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS)
    ).all()
    assert pd.to_datetime(result["available_at"]).dropna().le(
        pd.Timestamp("2026-07-31")
    ).all()
    for signal in (
        "AbnormalAccruals",
        "ChNNCOA",
        "EquityDuration",
        "Frontier",
        "GrLTNOA",
    ):
        assert result.loc[result["signal"].eq(signal), "value"].notna().any()
    ms = result.loc[result["signal"].eq("MS")]
    assert ms["value"].notna().any()
    computed_ms = ms["value"].notna()
    assert ms.loc[computed_ms, "fidelity_class"].eq(
        FidelityClass.UNVALIDATED_PROXY.value
    ).all()
    assert ms.loc[~computed_ms, "fidelity_class"].eq(
        FidelityClass.UNAVAILABLE.value
    ).all()
    assert not ms["current_usable"].any()


def test_analyst_pipeline_reconstructs_direct_fields_and_fails_proxies_closed() -> None:
    retrieved = "2026-08-03T12:00:00+00:00"
    payloads = {
        "recommendations": [
            {
                "period": "0m",
                "strongBuy": 4,
                "buy": 5,
                "hold": 1,
                "sell": 0,
                "strongSell": 0,
            },
            {
                "period": "-1m",
                "strongBuy": 2,
                "buy": 4,
                "hold": 3,
                "sell": 1,
                "strongSell": 0,
            },
        ],
        "earnings_estimate": [
            {
                "period": "0y",
                "avg": 5.0,
                "low": 4.5,
                "high": 5.5,
                "yearAgoEps": 4.0,
                "numberOfAnalysts": 10,
            }
        ],
        "growth_estimates": [{"period": "LTG", "stockTrend": 0.12}],
        "earnings_history": [
            {
                "quarter": "2026-03-31T00:00:00",
                "epsActual": 1.1,
                "epsEstimate": 1.0,
                "surprisePercent": 0.10,
            },
            {
                "quarter": "2026-06-30T00:00:00",
                "epsActual": 1.3,
                "epsEstimate": 1.2,
                "surprisePercent": 0.0833,
            },
        ],
    }
    analyst = pd.DataFrame(
        [
            {
                "symbol": "ANA",
                "dataset": dataset,
                "retrieved_at": retrieved,
                "payload_json": json.dumps(payload),
            }
            for dataset, payload in payloads.items()
        ]
        + [
            {
                "symbol": "ANA",
                "dataset": "earnings_estimate",
                "retrieved_at": "2026-09-01T00:00:00+00:00",
                "payload_json": json.dumps([{"period": "0y", "avg": 999999.0}]),
            }
        ]
    )
    companyfacts = pd.DataFrame(
        {
            "symbol": ["ANA"],
            "tag": ["EarningsPerShareDiluted"],
            "value": [1.2],
            "period_start": [pd.Timestamp("2026-04-01")],
            "period_end": [pd.Timestamp("2026-06-30")],
            "available_at": [pd.Timestamp("2026-07-25")],
        }
    )
    result = calculate_analyst_signals(
        pd.DataFrame({"symbol": ["ANA"]}),
        analyst,
        companyfacts,
        formation_at="2026-08-04",
    )

    assert set(result["signal"]) == ANALYST_IMPLEMENTED_SIGNALS
    assert pd.to_datetime(result["available_at"]).le(pd.Timestamp("2026-08-04")).all()
    direct = result["signal"].isin({"ChangeInRecommendation", "FEPS"})
    assert result.loc[direct, "fidelity_class"].eq(
        FidelityClass.RECONSTRUCTED.value
    ).all()
    assert result.loc[direct, "current_usable"].all()
    assert result.loc[result["signal"].eq("FEPS"), "value"].iloc[0] == 5.0
    proxies = ~direct
    assert result.loc[proxies, "fidelity_class"].eq(
        FidelityClass.UNVALIDATED_PROXY.value
    ).all()
    assert not result.loc[proxies, "current_usable"].any()


def test_short_interest_pipeline_reconstructs_ratio_and_keeps_combined_proxies_closed() -> None:
    symbols = [f"SI{index:03d}" for index in range(100)]
    master = pd.DataFrame(
        {
            "symbol": symbols,
            "sharesShort": np.arange(1, 101, dtype=float),
            "sharesOutstanding": 1_000.0,
            "dateShortInterest": 1_752_364_800,
            "retrieved_at": "2025-07-25T12:00:00+00:00",
            "heldPercentInstitutions": 0.50,
        }
    )
    analyst_rows = []
    for index, symbol in enumerate(symbols):
        if index < 20:
            recommendation = {
                "period": "0m",
                "strongBuy": 0,
                "buy": 0,
                "hold": 0,
                "sell": 0,
                "strongSell": 10,
            }
        elif index >= 80:
            recommendation = {
                "period": "0m",
                "strongBuy": 10,
                "buy": 0,
                "hold": 0,
                "sell": 0,
                "strongSell": 0,
            }
        else:
            recommendation = {
                "period": "0m",
                "strongBuy": 0,
                "buy": 0,
                "hold": 10,
                "sell": 0,
                "strongSell": 0,
            }
        analyst_rows.append(
            {
                "symbol": symbol,
                "dataset": "recommendations",
                "retrieved_at": "2025-07-25T12:00:00+00:00",
                "payload_json": json.dumps([recommendation]),
            }
        )

    result = calculate_short_interest_signals(
        master,
        pd.DataFrame(analyst_rows),
        formation_at="2025-07-31",
    )

    assert set(result["signal"]) == SHORT_INTEREST_IMPLEMENTED_SIGNALS
    direct = result.loc[result["signal"].eq("ShortInterest")]
    assert direct["fidelity_class"].eq(FidelityClass.RECONSTRUCTED.value).all()
    assert direct["current_usable"].all()
    assert direct.loc[direct["symbol"].eq("SI099"), "value"].iat[0] == pytest.approx(0.1)
    combined = result.loc[
        result["signal"].isin({"Recomm_ShortInterest", "IO_ShortInterest"})
        & result["value"].notna()
    ]
    assert combined["fidelity_class"].eq(
        FidelityClass.UNVALIDATED_PROXY.value
    ).all()
    assert not combined["current_usable"].any()
    io_values = result.loc[
        result["signal"].eq("IO_ShortInterest"), "value"
    ].dropna()
    assert len(io_values) == 1
    assert io_values.iat[0] == pytest.approx(50.0)


def test_event_pipeline_emits_four_signals_and_keeps_proxies_out_of_score() -> None:
    dates = pd.bdate_range("2022-01-03", "2026-06-30")
    prices = pd.DataFrame(
        {
            "date": dates,
            "symbol": "EVT",
            "adj_close": np.linspace(20.0, 40.0, len(dates)),
            "volume": 1_000_000,
            "dividends": np.where(
                (dates.year == 2026) & (dates.month == 4) & (dates.day < 8),
                0.25,
                0.0,
            ),
        }
    )
    master = pd.DataFrame(
        {
            "symbol": ["EVT"],
            "first_clean_price_date": [pd.Timestamp("2022-01-03")],
        }
    )
    result = calculate_event_signals(
        master, prices, formation_at="2026-07-15"
    )
    assert set(result["signal"]) == EVENT_IMPLEMENTED_SIGNALS
    assert pd.to_datetime(result["available_at"]).le(pd.Timestamp("2026-07-15")).all()
    proxy = result["fidelity_class"].eq(FidelityClass.UNVALIDATED_PROXY.value)
    assert not result.loc[proxy, "current_usable"].any()
    age = result.loc[result["signal"].eq("AgeIPO")].iloc[0]
    assert age["reason_if_missing"] == (
        "not_applicable:listing_age_outside_3_36_months"
    )


def test_not_applicable_is_distinct_from_missing_in_normalized_coverage() -> None:
    registry = load_signal_registry(CONFIG)
    master = pd.DataFrame({"symbol": ["NA1"], "cik": [1]})
    observed = pd.DataFrame(
        {
            "symbol": ["NA1"],
            "signal": ["AgeIPO"],
            "formation_at": [pd.Timestamp("2026-07-15")],
            "period_end": [pd.Timestamp("2026-06-30")],
            "available_at": [pd.Timestamp("2026-06-30")],
            "staleness_days": [15],
            "value": [np.nan],
            "fidelity_class": [FidelityClass.UNAVAILABLE.value],
            "current_usable": [False],
            "formula_id": ["openap_recent_ipo_listing_age_proxy"],
            "source_ids": ["yahoo_public"],
            "observation_count": [1],
            "reason_if_missing": [
                "not_applicable:listing_age_outside_3_36_months"
            ],
            "caveat": ["outside the official proxy scope"],
        }
    )
    normalized = _normalize_signal_results(
        [observed],
        master,
        registry,
        pd.Timestamp("2026-07-15"),
        "2026-07-15T00:00:00Z",
    )
    age = normalized.loc[normalized["signal"].eq("AgeIPO")].iloc[0]
    assert age["coverage_flag"] == "not_applicable"
    validation = build_validation_report(normalized)
    coverage = build_coverage_report(normalized, registry, validation).set_index(
        "signal"
    )
    assert coverage.at["AgeIPO", "not_applicable_count"] == 1
    assert coverage.at["AgeIPO", "applicable_count"] == 0
    assert coverage.at["AgeIPO", "missing_count"] == 0
    assert coverage.at["AgeIPO", "status"] == "not_applicable"
    assert coverage.at["AOP", "not_applicable_count"] == 0
    assert coverage.at["AOP", "applicable_count"] == 1
    assert coverage.at["AOP", "missing_count"] == 1


def test_quarterly_pipeline_uses_only_filed_facts_available_at_formation() -> None:
    quarter_ends = pd.date_range("2023-03-31", periods=13, freq="QE")
    tags = {
        "NetIncomeLoss": lambda index: 20.0 + index,
        "RevenueFromContractWithCustomerExcludingAssessedTax": lambda index: 200.0 + 5 * index,
        "WeightedAverageNumberOfDilutedSharesOutstanding": lambda index: 10.0,
        "Assets": lambda index: 500.0 + 10 * index,
    }
    rows: list[dict[str, object]] = []
    for index, period_end in enumerate(quarter_ends):
        for tag, value in tags.items():
            rows.append(
                {
                    "cik": 1,
                    "tag": tag,
                    "value": value(index),
                    "period_start": period_end - pd.Timedelta(days=89),
                    "period_end": period_end,
                    "form": "10-Q",
                    "filed": period_end + pd.Timedelta(days=35),
                    "available_at": period_end + pd.Timedelta(days=35),
                }
            )
    rows.append(
        {
            "cik": 1,
            "tag": "NetIncomeLoss",
            "value": 999999.0,
            "period_start": pd.Timestamp("2026-07-01"),
            "period_end": pd.Timestamp("2026-09-30"),
            "form": "10-Q",
            "filed": pd.Timestamp("2026-11-01"),
            "available_at": pd.Timestamp("2026-11-01"),
        }
    )
    dates = pd.bdate_range("2023-01-02", "2026-07-31")
    prices = pd.DataFrame(
        {
            "date": dates,
            "symbol": "QTR",
            "adj_close": np.linspace(50.0, 80.0, len(dates)),
        }
    )
    ff3 = pd.DataFrame(
        {"date": dates, "mktrf": 0.0002, "smb": 0.0, "hml": 0.0, "rf": 0.0001}
    )
    master = pd.DataFrame(
        {
            "symbol": ["QTR"],
            "cik": [1],
            "industry": ["Software"],
            "issuer_market_cap": [5_000_000_000.0],
        }
    )
    result = calculate_quarterly_signals(
        master,
        pd.DataFrame(rows),
        prices,
        ff3,
        formation_at="2026-07-31",
    )
    assert set(result["signal"]) == QUARTERLY_IMPLEMENTED_SIGNALS
    assert pd.to_datetime(result["available_at"]).le(pd.Timestamp("2026-07-31")).all()
    proxy = result["fidelity_class"].eq(FidelityClass.UNVALIDATED_PROXY.value)
    assert not result.loc[proxy, "current_usable"].any()
    assert not result["value"].eq(999999.0).any()
