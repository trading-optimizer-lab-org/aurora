from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import aurora.research.stock_protocol.opportunity_audit as audit_module
from aurora.research.stock_protocol.exact_oos import exact_strategy_spec
from aurora.research.stock_protocol.opportunity_audit import (
    AUDIT_ROLE,
    CUTOFF,
    benchmark_comparison,
    causal_fx_merge,
    component_audit_frames,
    event_study_statistics,
    frequency_metric_rows,
    fx_adjust_opportunities,
    sequence_dependence,
    simulate_opportunity_portfolio,
)


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=12, freq="B")
    rows = []
    for offset, symbol in enumerate(("AAA", "BBB", "CCC")):
        for index, date in enumerate(dates):
            price = 10.0 + offset + index * (0.1 + offset * 0.01)
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price * 1.005,
                    "adj_close": price * 1.005,
                    "volume": 1_000_000.0,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _opportunities() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=12, freq="B")
    rows = []
    for trade_id, symbol in enumerate(("AAA", "BBB", "CCC")):
        entry = dates[1]
        exit_date = dates[8 + trade_id]
        entry_price = float(_panel().loc[lambda x: x["symbol"].eq(symbol) & x["date"].eq(entry), "open"].iloc[0])
        exit_price = float(_panel().loc[lambda x: x["symbol"].eq(symbol) & x["date"].eq(exit_date), "open"].iloc[0])
        rows.append(
            {
                "opportunity_id": f"o{trade_id}",
                "symbol": symbol,
                "entry_date": entry,
                "entry_price": entry_price,
                "exit_date": exit_date,
                "exit_price": exit_price,
                "score": 1.0 - trade_id * 0.1,
                "weight": 1 / 3,
                "trade_id": trade_id,
                "gross_return": exit_price / entry_price - 1,
                "reached_50pct": False,
                "time_exit": True,
                "holding_sessions": 8,
                "maximum_adverse_excursion": -0.02,
                "maximum_favourable_excursion": 0.10,
            }
        )
    return pd.DataFrame(rows)


def test_frozen_components_are_complete_and_reduced_without_losing_weight() -> None:
    full, reduced = component_audit_frames(exact_strategy_spec())
    assert len(full) == 10
    assert len(reduced) < 10
    assert math.isclose(float(reduced["effective_weight"].sum()), 1.0)
    assert full["functionally_duplicated"].any()


def test_event_study_contains_every_opportunity_and_never_reports_cagr() -> None:
    summary, bootstrap = event_study_statistics(_opportunities(), bootstrap_samples=50)
    assert int(summary.iloc[0]["opportunities"]) == 3
    assert "cagr" not in summary.columns
    assert len(bootstrap) == 50


def test_fixed_portfolio_obeys_position_weight_cash_and_symbol_constraints() -> None:
    curve, ledger = simulate_opportunity_portfolio(
        _opportunities(),
        _panel(),
        max_positions=2,
        max_initial_weight=0.5,
        order_mode="score",
    )
    assert int(curve["positions"].max()) <= 2
    assert float(curve["gross_exposure"].max()) <= 1.0000001
    assert float(curve["cash"].min()) >= -1e-7
    funded = ledger.loc[ledger["status"].eq("closed")]
    assert (funded["simulation_entry_notional"] <= 50_000.01).all()
    assert funded["symbol"].nunique() == len(funded)
    assert len(ledger) == len(_opportunities())


def test_sequence_requires_at_least_one_thousand_permutations() -> None:
    with pytest.raises(ValueError, match="at least 1000"):
        sequence_dependence(_opportunities(), _panel(), simulations=999)


def test_sequence_reuses_one_static_price_context_for_all_permutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = audit_module._price_lookup

    def counted_price_lookup(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(audit_module, "_price_lookup", counted_price_lookup)
    sequence_dependence(_opportunities(), _panel(), simulations=1000)
    assert calls == 1


def test_parallel_sequence_matches_single_worker_exactly() -> None:
    single_summary, single_distribution = sequence_dependence(
        _opportunities(), _panel(), simulations=1000, workers=1
    )
    parallel_summary, parallel_distribution = sequence_dependence(
        _opportunities(), _panel(), simulations=1000, workers=2
    )
    pd.testing.assert_frame_equal(single_summary, parallel_summary)
    pd.testing.assert_frame_equal(single_distribution, parallel_distribution)


def test_fx_merge_is_causal_and_does_not_use_future_rate() -> None:
    rows = pd.DataFrame(
        {"currency": ["EUR", "EUR"], "entry_date": ["2020-01-02", "2020-01-06"]}
    )
    fx = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-03", "2020-01-07"],
            "currency": ["EUR", "EUR", "EUR"],
            "usd_per_local": [1.10, 1.11, 1.12],
        }
    )
    merged = causal_fx_merge(rows, fx, date_column="entry_date")
    assert merged["fx_date"].tolist() == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-03")]
    assert (merged["fx_date"] <= merged["entry_date"]).all()


def test_fx_source_after_cutoff_is_rejected() -> None:
    rows = pd.DataFrame({"currency": ["EUR"], "entry_date": [CUTOFF]})
    fx = pd.DataFrame(
        {"date": [CUTOFF + pd.Timedelta(days=1)], "currency": ["EUR"], "usd_per_local": [1.1]}
    )
    with pytest.raises(ValueError, match="after the frozen cutoff"):
        causal_fx_merge(rows, fx, date_column="entry_date")


def test_causal_fx_merge_normalizes_mixed_datetime_resolutions() -> None:
    rows = pd.DataFrame(
        {
            "currency": ["EUR", "EUR"],
            "entry_date": np.array(
                ["2020-01-02", "2020-01-06"], dtype="datetime64[s]"
            ),
        }
    )
    fx = pd.DataFrame(
        {
            "date": np.array(
                ["2020-01-01", "2020-01-03"], dtype="datetime64[us]"
            ),
            "currency": ["EUR", "EUR"],
            "usd_per_local": [1.10, 1.12],
        }
    )

    merged = causal_fx_merge(rows, fx, date_column="entry_date")

    assert merged["fx_date"].tolist() == [
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2020-01-03"),
    ]
    assert (merged["fx_date"] <= merged["entry_date"]).all()


def test_fx_adjustment_uses_entry_and_exit_dates_separately() -> None:
    opportunities = pd.DataFrame(
        {
            "opportunity_id": ["x"],
            "currency": ["EUR"],
            "currency_unknown": [False],
            "price_scale_to_currency_unit": [1.0],
            "entry_date": ["2020-01-02"],
            "exit_date": ["2020-01-06"],
            "entry_price": [100.0],
            "exit_price": [110.0],
            "dividends_local": [0.0],
        }
    )
    fx = pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-06"],
            "currency": ["EUR", "EUR"],
            "usd_per_local": [1.0, 2.0],
        }
    )
    adjusted = fx_adjust_opportunities(opportunities, fx)
    assert adjusted.iloc[0]["fx_entry_date"] == pd.Timestamp("2020-01-02")
    assert adjusted.iloc[0]["fx_exit_date"] == pd.Timestamp("2020-01-06")
    assert "dividend_value_usd_per_share" in adjusted.columns
    assert math.isclose(float(adjusted.iloc[0]["dividend_value_usd_per_share"]), 0.0)
    assert math.isclose(float(adjusted.iloc[0]["return_usd"]), 1.2)


def test_calendar_metrics_include_original_weekly_monthly_and_quarterly() -> None:
    curve = pd.DataFrame(
        {"date": pd.date_range("2019-01-01", periods=500, freq="D"), "equity": np.linspace(100, 150, 500)}
    )
    rows = frequency_metric_rows(curve, period="x", variant="P20")
    assert set(rows["calendar_mode"]) == {"artifact_calendar", "monday_to_friday"}
    assert set(rows["frequency"]) == {"daily", "weekly", "monthly", "quarterly"}
    assert rows.loc[rows["frequency"].eq("daily"), "daily_asynchrony_warning"].all()


def test_benchmark_comparison_uses_only_common_dates() -> None:
    dates = pd.date_range("2018-01-01", periods=500, freq="B")
    curve = pd.DataFrame({"date": dates, "equity": np.linspace(100, 180, len(dates))})
    benchmark = pd.DataFrame(
        {"date": dates[20:-10], "symbol": "SPY", "adj_close": np.linspace(100, 150, len(dates[20:-10]))}
    )
    rows, regressions = benchmark_comparison(
        curve, benchmark, benchmark="SPY", period="x", variant="P20"
    )
    evaluated = rows.loc[rows["status"].eq("evaluated")]
    assert not evaluated.empty
    assert (pd.to_datetime(evaluated["comparison_start"]) >= dates[20]).all()
    assert set(regressions["frequency"]) == set(evaluated["frequency"])


def test_opened_locked_role_is_explicitly_diagnostic() -> None:
    assert AUDIT_ROLE == "diagnostic_reanalysis_of_opened_locked_period"
