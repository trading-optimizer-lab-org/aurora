from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.research.openap_93.external import (
    normalize_public_inputs,
    parse_fred_csv,
    parse_french_zip,
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
from aurora.research.openap_93.registry import REQUIRED_93, FidelityClass, load_signal_registry
from aurora.research.openap_93.sources import (
    IMPLEMENTED_SIGNAL_SOURCES,
    PUBLIC_SOURCES,
    select_sources_lexicographically,
    source_coverage_matrix,
)


CONFIG = Path("config/openap_93/signals_93.yaml")


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
    assert selected_a["candidate_signals_covered"] == len(MARKET_IMPLEMENTED_SIGNALS)
    assert set(selected_a["candidate_signals_uncovered"]) == (
        set(REQUIRED_93) - MARKET_IMPLEMENTED_SIGNALS
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
    assert set(implemented["signal"]) == MARKET_IMPLEMENTED_SIGNALS
    assert implemented["required_fields_verified"].all()
    assert implemented["can_produce_value"].all()
    unimplemented = matrix.loc[~matrix["formula_implemented"]]
    assert not unimplemented["can_produce_value"].any()


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
