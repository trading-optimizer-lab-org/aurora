from __future__ import annotations

from pathlib import Path

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
from aurora.research.openap_93.current_pipeline import (
    IMPLEMENTED_SIGNALS,
    REQUIRED_SIGNAL_COLUMNS,
    SCORE_VARIANTS,
    build_validation_report,
)
from aurora.research.openap_93.event_pipeline import (
    EVENT_IMPLEMENTED_SIGNALS,
    calculate_event_signals,
)
from aurora.research.openap_93.external import (
    normalize_public_inputs,
    parse_fred_csv,
    parse_french_zip,
    parse_openap_reference_zip,
    parse_pastor_stambaugh,
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
from aurora.research.openap_93.registry import REQUIRED_93, FidelityClass, load_signal_registry
from aurora.research.openap_93.sources import (
    IMPLEMENTED_SIGNAL_SOURCES,
    PUBLIC_SOURCES,
    implemented_signal_requirements,
    select_sources_lexicographically,
    source_coverage_matrix,
)


CONFIG = Path("config/openap_93/signals_93.yaml")


def implemented_signals() -> frozenset[str]:
    return frozenset(
        MARKET_IMPLEMENTED_SIGNALS
        | ACCOUNTING_IMPLEMENTED_SIGNALS
        | ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS
        | EVENT_IMPLEMENTED_SIGNALS
        | QUARTERLY_IMPLEMENTED_SIGNALS
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


def test_no_source_requires_registration_or_payment() -> None:
    assert all(not source.registration_required for source in PUBLIC_SOURCES)
    assert all(source.access_mode for source in PUBLIC_SOURCES)


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
    assert len(relative) == 16
    assert "probe/source_probe_results.csv" in relative
    assert "probe/source_symbol_probe_results.csv" in relative
    assert "probe/sources.lock.json" in relative
    assert "inputs/public_inputs_manifest.json" in relative
    assert "inputs/normalized/ff3_daily.parquet" in relative
    assert "inputs/normalized/signal_doc.parquet" in relative
    assert "inputs/normalized/openap_reference_sample.parquet" in relative
    assert "inputs/normalized/openap_reference_metadata.json" in relative
    assert "inputs/normalized/normalized_summary.json" in relative


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

    daily_market = np.linspace(-0.03, 0.03, 252)
    daily_stock = 0.6 * daily_market + 3.0 * daily_market**2
    assert coskew_acx(daily_stock, daily_market) > 0


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
        price_rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "adj_close": 20.0 * np.cumprod(1.0 + returns),
                    "volume": np.where(
                        np.arange(len(dates)) % (31 + index) == 0,
                        0,
                        1_000_000 + index * 10_000,
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
