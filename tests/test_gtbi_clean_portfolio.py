from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.gtbi_clean_portfolio import (
    DataQualityPolicy,
    PortfolioConfig,
    UnresolvedPositionError,
    choose_risk_compliant_result,
    entry_priority_at_signal,
    prepare_signal_portfolio_data,
    sanitize_symbol_prices,
    simulate_portfolio,
    simulate_prepared_signal_portfolio,
    simulate_signal_portfolio,
)


def _prices(
    closes: list[float],
    *,
    start: str = "2020-01-01",
    adjusted: list[float] | None = None,
) -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(closes), freq="D")
    adjusted_values = adjusted if adjusted is not None else closes
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "adj_close": adjusted_values,
            "volume": [1_000_000.0] * len(closes),
        }
    )


def test_sanitize_prices_repairs_split_with_adjusted_ohlc() -> None:
    raw = _prices([100.0, 50.0, 52.0], adjusted=[50.0, 50.0, 52.0])
    raw["volume"] = [1_000_000.0, 2_000_000.0, 2_000_000.0]
    result = sanitize_symbol_prices(
        raw,
        symbol="SPLIT",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2, max_adjusted_gap_ratio=3.0),
    )
    assert list(result.segments) == ["SPLIT::segment_000"]
    assert result.segments["SPLIT::segment_000"]["close"].tolist() == pytest.approx([50.0, 50.0, 52.0])
    assert result.segments["SPLIT::segment_000"]["volume"].tolist() == pytest.approx([2_000_000.0] * 3)
    assert result.diagnostics["hard_breaks"] == 0
    assert result.diagnostics["adjusted_rows"] == 1


def test_sanitize_prices_splits_unexplained_currency_unit_jump() -> None:
    raw = _prices([10.0, 10.5, 1_050.0, 1_060.0])
    result = sanitize_symbol_prices(
        raw,
        symbol="UNITS",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2, max_adjusted_gap_ratio=3.0),
    )
    assert list(result.segments) == ["UNITS::segment_000", "UNITS::segment_001"]
    assert result.diagnostics["hard_breaks"] == 1
    anomaly = result.anomalies.iloc[0]
    assert anomaly["reason"] == "unexplained_adjusted_price_jump"
    assert float(anomaly["adjusted_open_to_previous_close_ratio"]) == pytest.approx(100.0)


def test_sanitize_prices_splits_long_missing_history_gap() -> None:
    raw = _prices([10.0, 10.5, 10.6, 10.7])
    raw["date"] = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-02-01", "2020-02-02"])
    result = sanitize_symbol_prices(
        raw,
        symbol="SUSPENDED",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2, max_calendar_gap_days=14),
    )
    assert list(result.segments) == ["SUSPENDED::segment_000", "SUSPENDED::segment_001"]
    assert result.diagnostics["calendar_breaks"] == 1
    assert "missing_price_history_gap" in result.anomalies["reason"].tolist()


def test_sanitize_prices_excludes_locked_rows() -> None:
    raw = _prices([10.0, 11.0, 12.0], start="2020-12-30")
    result = sanitize_symbol_prices(
        raw,
        symbol="LOCK",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2),
    )
    cleaned = next(iter(result.segments.values()))
    assert cleaned.index.max() == pd.Timestamp("2020-12-31")
    assert result.diagnostics["locked_rows_removed"] == 1


def test_sanitize_prices_can_keep_locked_rows_for_separate_forward_pass() -> None:
    raw = _prices([10.0, 11.0, 12.0], start="2020-12-30")
    result = sanitize_symbol_prices(
        raw,
        symbol="FORWARD",
        locked_start=None,
        policy=DataQualityPolicy(min_segment_rows=2),
    )
    cleaned = next(iter(result.segments.values()))
    assert cleaned.index.max() == pd.Timestamp("2021-01-01")
    assert result.diagnostics["locked_rows_removed"] == 0


def test_sanitize_prices_does_not_adjust_volume_for_small_dividend_factor_change() -> None:
    raw = _prices([100.0, 101.0, 102.0], adjusted=[98.0, 101.0, 102.0])
    raw["volume"] = [1_000_000.0] * 3
    result = sanitize_symbol_prices(
        raw,
        symbol="DIVIDEND",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2),
    )
    cleaned = next(iter(result.segments.values()))
    assert cleaned["volume"].tolist() == pytest.approx([1_000_000.0] * 3)


def test_sanitize_prices_adjusts_volume_for_five_for_four_split() -> None:
    raw = _prices([100.0, 80.0, 82.0], adjusted=[80.0, 80.0, 82.0])
    raw["volume"] = [1_000_000.0, 1_250_000.0, 1_250_000.0]
    result = sanitize_symbol_prices(
        raw,
        symbol="SPLIT_5_4",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2),
    )
    cleaned = next(iter(result.segments.values()))
    assert cleaned["volume"].tolist() == pytest.approx([1_250_000.0] * 3)


def test_sanitize_prices_adjusts_multiple_split_boundaries() -> None:
    raw = _prices(
        [120.0, 60.0, 20.0, 21.0],
        adjusted=[20.0, 20.0, 20.0, 21.0],
    )
    raw["volume"] = [1_000_000.0, 2_000_000.0, 6_000_000.0, 6_000_000.0]
    result = sanitize_symbol_prices(
        raw,
        symbol="MULTI_SPLIT",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2),
    )
    cleaned = next(iter(result.segments.values()))
    assert cleaned["volume"].tolist() == pytest.approx([6_000_000.0] * 4)


def test_sanitize_prices_removes_corrupt_intraday_spike() -> None:
    raw = _prices([10.0, 10.0, 10.0])
    raw.loc[1, "high"] = 1_000.0
    result = sanitize_symbol_prices(
        raw,
        symbol="SPIKE",
        locked_start="2021-01-01",
        policy=DataQualityPolicy(min_segment_rows=2, max_adjusted_gap_ratio=3.0),
    )
    cleaned = next(iter(result.segments.values()))
    assert len(cleaned) == 2
    assert float(cleaned["high"].max()) < 20.0
    assert result.diagnostics["intraday_anomalies_removed"] == 1


def test_entry_priority_uses_only_information_before_entry() -> None:
    frame = _prices([10.0, 11.0, 12.0, 99.0])
    benchmark = _prices([10.0, 10.0, 10.0, 1.0])
    entry_date = pd.Timestamp("2020-01-04")
    priority = entry_priority_at_signal(frame, benchmark, entry_date=entry_date, lookback=2)
    changed_future = frame.copy()
    changed_future.loc[changed_future["date"] == entry_date, "close"] = 0.01
    changed_benchmark = benchmark.copy()
    changed_benchmark.loc[changed_benchmark["date"] == entry_date, "close"] = 10_000.0
    assert entry_priority_at_signal(changed_future, changed_benchmark, entry_date=entry_date, lookback=2) == pytest.approx(priority)


def _trade(
    symbol: str,
    entry: str,
    exit_: str,
    entry_price: float,
    exit_price: float,
    priority: float,
    split: str = "validation",
) -> dict[str, object]:
    return {
        "candidate_id": "candidate",
        "symbol": symbol,
        "original_symbol": symbol,
        "split": split,
        "entry_date": entry,
        "exit_date": exit_,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": (exit_price / entry_price - 1.0) * 100.0,
        "holding_days": (pd.Timestamp(exit_) - pd.Timestamp(entry)).days,
        "exit_reason": "test",
        "entry_priority": priority,
    }


def test_portfolio_respects_cash_and_selects_highest_priority() -> None:
    trades = pd.DataFrame(
        [
            _trade("A", "2020-01-02", "2020-01-04", 10.0, 11.0, 1.0),
            _trade("B", "2020-01-02", "2020-01-04", 20.0, 22.0, 2.0),
        ]
    )
    frames = {"A": _prices([10.0, 10.5, 11.0], start="2020-01-02"), "B": _prices([20.0, 21.0, 22.0], start="2020-01-02")}
    result = simulate_portfolio(
        trades,
        frames,
        start="2020-01-02",
        end="2020-01-04",
        config=PortfolioConfig(
            initial_capital=100.0,
            position_size_pct=0.5,
            max_positions=1,
            allow_fractional_shares=True,
        ),
    )
    assert result.ledger["original_symbol"].tolist() == ["B"]
    assert result.skipped_entries.iloc[0]["reason"] == "max_positions"
    assert result.summary["ending_equity"] == pytest.approx(105.0)
    assert result.daily_equity.iloc[0]["gross_exposure"] == pytest.approx(0.5)
    assert result.daily_equity["gross_exposure"].max() <= 1.0 + 1e-12


def test_portfolio_uses_whole_shares_by_default() -> None:
    assert PortfolioConfig().allow_fractional_shares is False


def test_portfolio_processes_exits_before_same_day_entries() -> None:
    trades = pd.DataFrame(
        [
            _trade("A", "2020-01-02", "2020-01-03", 10.0, 10.0, 1.0),
            _trade("C", "2020-01-03", "2020-01-04", 10.0, 11.0, 1.0),
        ]
    )
    frames = {"A": _prices([10.0, 10.0, 10.0], start="2020-01-02"), "C": _prices([10.0, 10.0, 11.0], start="2020-01-02")}
    result = simulate_portfolio(
        trades,
        frames,
        start="2020-01-02",
        end="2020-01-04",
        config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger["original_symbol"].tolist() == ["A", "C"]
    assert result.summary["ending_equity"] == pytest.approx(110.0)


def test_portfolio_computes_real_drawdown_and_calendar_return() -> None:
    trades = pd.DataFrame([_trade("A", "2020-01-02", "2020-01-03", 100.0, 80.0, 1.0)])
    result = simulate_portfolio(
        trades,
        {"A": _prices([100.0, 80.0], start="2020-01-02")},
        start="2020-01-02",
        end="2020-01-03",
        config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.summary["max_drawdown_pct"] == pytest.approx(-20.0)
    assert result.annual_returns.iloc[0]["equity_return_pct"] == pytest.approx(-20.0)
    assert result.summary["worst_year_pct"] == pytest.approx(-20.0)


def test_choose_risk_compliant_result_requires_both_splits_below_limit() -> None:
    sweep = pd.DataFrame(
        [
            {"position_size_pct": 0.02, "max_positions": 20, "train_max_drawdown_pct": -18.0, "validation_max_drawdown_pct": -19.0, "train_worst_year_pct": -12.0, "validation_worst_year_pct": -15.0, "validation_cagr_pct": 8.0},
            {"position_size_pct": 0.03, "max_positions": 20, "train_max_drawdown_pct": -24.0, "validation_max_drawdown_pct": -26.0, "train_worst_year_pct": -18.0, "validation_worst_year_pct": -22.0, "validation_cagr_pct": 12.0},
            {"position_size_pct": 0.015, "max_positions": 20, "train_max_drawdown_pct": -14.0, "validation_max_drawdown_pct": -15.0, "train_worst_year_pct": -10.0, "validation_worst_year_pct": -11.0, "validation_cagr_pct": 7.0},
        ]
    )
    selected = choose_risk_compliant_result(sweep, risk_limit_pct=25.0)
    assert float(selected["position_size_pct"]) == pytest.approx(0.02)
    assert bool(selected["risk_limit_pass"])


def _exit_config(*, max_holding_days: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        stop_loss_pct=0.50,
        take_profit_pct=0.0,
        trailing_stop_pct=0.0,
        use_exit_ma=False,
        use_market_exit=False,
        max_holding_days=max_holding_days,
        take_profit_min_holding_days=0,
        minimum_holding_days_before_soft_exit=0,
        exit_ma_days=20,
        market_exit_confirmation_days=1,
    )


def _signal(frame: pd.DataFrame, true_dates: list[str]) -> pd.Series:
    index = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    return pd.Series(index.isin(pd.to_datetime(true_dates)), index=index)


def test_signal_portfolio_enters_next_open_and_exits_next_open() -> None:
    frame = _prices([10.0, 11.0, 12.0, 13.0])
    result = simulate_signal_portfolio(
        {"A": _signal(frame, ["2020-01-01"])},
        {"A": frame},
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-04",
        indicator_config=_exit_config(max_holding_days=2),
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    trade = result.ledger.iloc[0]
    assert trade["signal_date"] == pd.Timestamp("2020-01-01")
    assert trade["entry_date"] == pd.Timestamp("2020-01-02")
    assert trade["exit_date"] == pd.Timestamp("2020-01-04")
    assert trade["entry_price"] == pytest.approx(11.0)
    assert trade["exit_price"] == pytest.approx(13.0)


def test_signal_portfolio_can_enter_later_signal_after_capacity_frees() -> None:
    a = _prices([10.0, 10.0, 10.0, 10.0])
    b = _prices([20.0, 20.0, 20.0, 20.0])
    result = simulate_signal_portfolio(
        {"A": _signal(a, ["2020-01-01"]), "B": _signal(b, ["2020-01-01", "2020-01-02"])},
        {"A": a, "B": b},
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-04",
        indicator_config=_exit_config(max_holding_days=1),
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger["original_symbol"].tolist() == ["A", "B"]
    assert result.ledger["entry_date"].tolist() == [pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")]


def test_signal_portfolio_never_executes_after_period_end() -> None:
    frame = _prices([10.0, 11.0], start="2020-12-31")
    result = simulate_signal_portfolio(
        {"A": _signal(frame, ["2020-12-31"])},
        {"A": frame},
        market_exit_signals={},
        start="2020-12-31",
        end="2020-12-31",
        indicator_config=_exit_config(),
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger.empty
    assert result.summary["trades_accepted"] == 0


def test_signal_portfolio_rejects_entry_without_valid_next_open() -> None:
    frame = _prices([10.0, 11.0, 12.0])
    frame.loc[1, "open"] = float("nan")
    result = simulate_signal_portfolio(
        {"A": _signal(frame, ["2020-01-01"])},
        {"A": frame},
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-03",
        indicator_config=_exit_config(),
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger.empty
    assert result.skipped_entries.iloc[0]["reason"] == "missing_next_open"


def test_signal_portfolio_sizes_at_open_without_using_same_day_close() -> None:
    a = _prices([100.0, 100.0, 200.0, 200.0])
    a["open"] = [100.0, 100.0, 100.0, 200.0]
    b = _prices([10.0, 10.0, 10.0, 10.0])
    result = simulate_signal_portfolio(
        {"A": _signal(a, ["2020-01-01"]), "B": _signal(b, ["2020-01-02"])},
        {"A": a, "B": b},
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-04",
        indicator_config=_exit_config(max_holding_days=10),
        portfolio_config=PortfolioConfig(
            initial_capital=100.0,
            position_size_pct=0.25,
            max_positions=2,
            allow_fractional_shares=True,
        ),
    )
    b_trade = result.ledger[result.ledger["original_symbol"] == "B"].iloc[0]
    assert b_trade["allocated_capital"] == pytest.approx(25.0)


def test_signal_portfolio_rejects_unresolved_position_at_segment_end() -> None:
    frame = _prices([10.0, 11.0, 12.0])
    with pytest.raises(UnresolvedPositionError, match="no executable exit"):
        simulate_signal_portfolio(
            {"A::segment_000": _signal(frame, ["2020-01-01"])},
            {"A::segment_000": frame.assign(original_symbol="A")},
            market_exit_signals={},
            start="2020-01-01",
            end="2020-01-20",
            indicator_config=_exit_config(max_holding_days=50),
            portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
        )


def test_market_frame_normalizes_intraday_timestamps() -> None:
    frame = _prices([10.0, 11.0, 12.0])
    frame["date"] = pd.to_datetime(frame["date"]) + pd.Timedelta(hours=16)
    frame = frame.set_index("date", drop=False)
    result = simulate_signal_portfolio(
        {"A": pd.Series([True, False, False], index=frame.index)},
        {"A": frame},
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-03",
        indicator_config=_exit_config(max_holding_days=1),
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger.iloc[0]["entry_date"] == pd.Timestamp("2020-01-02")


def test_signal_portfolio_prefers_precomputed_strength_not_ticker_name() -> None:
    a = _prices([10.0, 10.0, 10.0])
    z = _prices([10.0, 10.0, 10.0])
    index = pd.DatetimeIndex(pd.to_datetime(a["date"]))
    priorities = {
        "A": pd.Series([1.0, 1.0, 1.0], index=index),
        "Z": pd.Series([2.0, 2.0, 2.0], index=index),
    }
    prepared = prepare_signal_portfolio_data(
        {"A": _signal(a, ["2020-01-01"]), "Z": _signal(z, ["2020-01-01"])},
        {"A": a, "Z": z},
        market_exit_signals={},
        priority_scores=priorities,
        start="2020-01-01",
        end="2020-01-03",
        indicator_config=_exit_config(max_holding_days=1),
    )
    result = simulate_prepared_signal_portfolio(
        prepared,
        portfolio_config=PortfolioConfig(initial_capital=100.0, position_size_pct=1.0, max_positions=1),
    )
    assert result.ledger.iloc[0]["original_symbol"] == "Z"
    assert result.ledger.iloc[0]["entry_priority"] == pytest.approx(2.0)


def test_prepared_signal_portfolio_matches_direct_path() -> None:
    frame = _prices([10.0, 11.0, 12.0, 13.0])
    signals = {"A": _signal(frame, ["2020-01-01"])}
    frames = {"A": frame}
    config = PortfolioConfig(initial_capital=100.0, position_size_pct=0.5, max_positions=1)
    direct = simulate_signal_portfolio(
        signals,
        frames,
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-04",
        indicator_config=_exit_config(max_holding_days=2),
        portfolio_config=config,
    )
    prepared = prepare_signal_portfolio_data(
        signals,
        frames,
        market_exit_signals={},
        start="2020-01-01",
        end="2020-01-04",
        indicator_config=_exit_config(max_holding_days=2),
    )
    cached = simulate_prepared_signal_portfolio(prepared, portfolio_config=config)
    pd.testing.assert_frame_equal(direct.daily_equity, cached.daily_equity)
    pd.testing.assert_frame_equal(direct.ledger, cached.ledger)
