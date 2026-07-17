"""Scientific execution, portfolio-equity and metric contracts."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.execution import execute_next_open
from aurora.research.stock_protocol.metrics import (
    compute_portfolio_metrics,
    yearly_returns,
)
from aurora.research.stock_protocol.portfolio import (
    UnsupportedPortfolioData,
    build_portfolio,
    simulate_daily_portfolio,
)


def _panel(symbols: tuple[str, ...] = ("AAA",)) -> ResearchPanel:
    dates = pd.bdate_range("2020-01-02", periods=8)
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(symbols):
        offset = 10.0 * symbol_index
        for index, timestamp in enumerate(dates):
            open_price = 100.0 + offset + index
            rows.append(
                {
                    "date": timestamp,
                    "symbol": symbol,
                    "open": open_price,
                    "high": open_price + 2.0,
                    "low": open_price - 2.0,
                    "close": open_price + 1.0,
                    "adj_close": open_price + 1.0,
                    "volume": 1_000_000.0,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    audit = PackAudit(
        "source",
        "pack",
        "2020-01-02",
        "2020-12-31",
        len(frame),
        len(symbols),
        0,
        False,
        False,
        "dataset-hash",
    )
    return ResearchPanel(frame, audit)


def _signals(symbol: str = "AAA") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_date": [pd.Timestamp("2020-01-02")],
            "available_at": [pd.Timestamp("2020-01-02")],
            "symbol": [symbol],
            "score": [1.0],
            "atr20": [2.0],
            "vol_12_1": [0.2],
        }
    )


def test_duplicate_signal_does_not_open_overlapping_position():
    signals = pd.concat(
        [
            _signals(),
            _signals().assign(
                signal_date=pd.Timestamp("2020-01-03"),
                available_at=pd.Timestamp("2020-01-03"),
            ),
        ],
        ignore_index=True,
    )
    trades = execute_next_open(signals, _panel(), {"kind": "none", "holding_sessions": 4})
    assert len(trades) == 1
    assert trades.iloc[0]["entry_date"] == "2020-01-03"


def test_ranking_hysteresis_exits_next_open_after_falling_out_of_keep_set():
    keep = pd.DataFrame(
        {
            "signal_date": [pd.Timestamp("2020-01-06")],
            "symbol": ["BBB"],
        }
    )
    trades = execute_next_open(
        _signals(),
        _panel(),
        {
            "kind": "ranking_hysteresis",
            "holding_sessions": 6,
            "keep_percentile": 30,
        },
        ranking_keep=keep,
    )
    assert trades.iloc[0]["exit_date"] == "2020-01-07"
    assert trades.iloc[0]["exit_reason"] == "ranking_hysteresis_next_open"


def test_stop_crossed_by_gap_executes_at_open():
    panel = _panel()
    frame = panel.frame.copy()
    frame.loc[frame["date"] == pd.Timestamp("2020-01-06"), ["open", "high", "low", "close"]] = [90.0, 92.0, 89.0, 91.0]
    trades = execute_next_open(
        _signals(),
        ResearchPanel(frame, panel.audit),
        {"kind": "initial_stop_pct", "stop_pct": 5.0, "holding_sessions": 5},
    )
    assert trades.iloc[0]["exit_date"] == "2020-01-06"
    assert trades.iloc[0]["exit_price"] == 90.0
    assert trades.iloc[0]["exit_reason"] == "gap_through_stop"


def test_same_bar_stop_target_conflict_is_conservative_and_audited():
    panel = _panel()
    frame = panel.frame.copy()
    day = pd.Timestamp("2020-01-06")
    frame.loc[frame["date"] == day, ["open", "high", "low", "close"]] = [101.0, 108.0, 94.0, 102.0]
    trades = execute_next_open(
        _signals(),
        ResearchPanel(frame, panel.audit),
        {
            "kind": "stop_and_target",
            "stop_pct": 5.0,
            "target_pct": 5.0,
            "holding_sessions": 5,
        },
    )
    trade = trades.iloc[0]
    assert trade["exit_reason"] == "stop_target_conflict_conservative"
    assert trade["exit_price"] == pytest.approx(101.0 * 0.95)
    assert trade["optimistic_exit_price"] == pytest.approx(101.0 * 1.05)


def test_holding_period_cannot_exceed_twelve_months():
    with pytest.raises(ValueError, match="252"):
        execute_next_open(_signals(), _panel(), {"kind": "none", "holding_sessions": 253})


def test_equal_weights_and_cash_residual_respect_asset_cap():
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "entry_date": ["2020-01-03"] * 2,
            "volatility": [0.1, 0.2],
        }
    )
    result = build_portfolio(trades, {"sizing": "equal", "asset_cap": 0.4})
    assert result["weight"].tolist() == pytest.approx([0.4, 0.4])
    assert result["weight"].sum() == pytest.approx(0.8)
    assert result["cash_weight"].unique().tolist() == pytest.approx([0.2])


def test_inverse_volatility_weights_change_real_allocations():
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "entry_date": ["2020-01-03"] * 2,
            "volatility": [0.1, 0.2],
        }
    )
    result = build_portfolio(trades, {"sizing": "inverse_vol"})
    assert result.loc[result.symbol == "AAA", "weight"].iloc[0] == pytest.approx(2 / 3)
    assert result.loc[result.symbol == "BBB", "weight"].iloc[0] == pytest.approx(1 / 3)
    assert result["weight"].sum() == pytest.approx(1.0)


def test_correlation_cap_rejects_redundant_simultaneous_position():
    panel = _panel(("AAA", "BBB"))
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "entry_date": [str(panel.frame["date"].max().date())] * 2,
            "volatility": [0.1, 0.1],
            "score": [2.0, 1.0],
        }
    )
    result = build_portfolio(
        trades,
        {"sizing": "equal", "corr_cap": 0.60, "corr_lookback": 5},
        panel=panel,
    )
    assert result["weight"].gt(0).sum() == 1
    assert result.loc[result["weight"].eq(0), "portfolio_rejected_reason"].eq(
        "correlation_cap"
    ).all()


def test_sector_cap_without_historical_pit_classification_is_unsupported():
    trades = pd.DataFrame(
        {"symbol": ["AAA"], "entry_date": ["2020-01-03"], "volatility": [0.1]}
    )
    with pytest.raises(UnsupportedPortfolioData, match="sector"):
        build_portfolio(trades, {"sizing": "equal", "sector_cap": 0.20})


def test_spy_regime_reduces_exposure_using_only_prior_prices():
    dates = pd.bdate_range("2019-01-02", periods=40)
    rows = []
    for symbol in ("AAA", "SPY"):
        closes = np.linspace(100, 120, len(dates)) if symbol == "AAA" else np.linspace(120, 80, len(dates))
        for date, close in zip(dates, closes):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "adj_close": close,
                    "volume": 1_000_000,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    audit = _panel().audit
    panel = ResearchPanel(frame, audit)
    trades = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "entry_date": [str(dates[-1].date())],
            "volatility": [0.1],
        }
    )
    result = build_portfolio(
        trades,
        {"sizing": "equal", "regime": "sma_200", "regime_sma_window": 20},
        panel=panel,
    )
    assert result["regime_exposure"].iloc[0] == pytest.approx(0.5)
    assert result["weight"].sum() == pytest.approx(0.5)


def test_daily_portfolio_equity_uses_weights_cash_and_two_sided_costs():
    panel = _panel(("AAA", "BBB"))
    trades = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "signal_date": ["2020-01-02"] * 2,
            "entry_date": ["2020-01-03"] * 2,
            "entry_price": [101.0, 111.0],
            "exit_date": ["2020-01-08"] * 2,
            "exit_price": [105.0, 115.0],
            "gross_return": [105 / 101 - 1, 115 / 111 - 1],
            "weight": [0.4, 0.4],
        }
    )
    curve, positions, ledger = simulate_daily_portfolio(
        trades,
        panel,
        initial_capital=100_000.0,
        cost_bps_per_side=10,
    )
    assert curve["date"].is_monotonic_increasing
    assert curve["date"].is_unique
    assert curve.iloc[0]["cash"] > 19_000.0
    assert curve["equity"].gt(0).all()
    assert curve["gross_exposure"].max() <= 0.81
    assert positions["market_value"].notna().all()
    assert ledger["entry_cost"].sum() > 0
    assert ledger["exit_cost"].sum() > 0
    assert ledger["net_return"].lt(ledger["gross_return"]).all()


def test_stock_split_adjusts_live_shares_instead_of_creating_fake_loss():
    panel = _panel()
    frame = panel.frame.copy()
    split_date = frame["date"].iloc[3]
    frame.loc[frame["date"].ge(split_date), ["open", "high", "low", "close", "adj_close"]] /= 2.0
    frame.loc[frame["date"].eq(split_date), "stock_splits"] = 2.0
    trades = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "signal_date": [str(frame["date"].iloc[0].date())],
            "entry_date": [str(frame["date"].iloc[1].date())],
            "entry_price": [float(frame["open"].iloc[1])],
            "exit_date": [str(frame["date"].iloc[-1].date())],
            "exit_price": [float(frame["close"].iloc[-1])],
            "gross_return": [0.0],
            "weight": [1.0],
        }
    )
    curve, _, ledger = simulate_daily_portfolio(
        trades, ResearchPanel(frame, panel.audit), initial_capital=100_000.0
    )
    assert curve["equity"].min() > 90_000.0
    assert ledger["split_adjustment_count"].iloc[0] == 1


def test_daily_portfolio_carries_last_close_across_symbol_market_holidays():
    panel = _panel(("AAA", "BBB"))
    missing_date = pd.Timestamp(panel.frame["date"].sort_values().unique()[3])
    frame = panel.frame.loc[
        ~(
            panel.frame["symbol"].eq("AAA")
            & panel.frame["date"].eq(missing_date)
        )
    ].copy()
    aaa = frame.loc[frame["symbol"].eq("AAA")].sort_values("date")
    trades = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "signal_date": [aaa["date"].iloc[0]],
            "entry_date": [aaa["date"].iloc[1]],
            "entry_price": [aaa["open"].iloc[1]],
            "exit_date": [aaa["date"].iloc[-1]],
            "exit_price": [aaa["close"].iloc[-1]],
            "gross_return": [aaa["close"].iloc[-1] / aaa["open"].iloc[1] - 1.0],
            "weight": [1.0],
        }
    )

    curve, positions, ledger = simulate_daily_portfolio(
        trades,
        ResearchPanel(frame, panel.audit),
        initial_capital=100_000.0,
    )

    holiday_position = positions.loc[positions["date"].eq(missing_date)].iloc[0]
    previous_close = aaa.loc[aaa["date"].lt(missing_date), "close"].iloc[-1]
    assert holiday_position["close"] == pytest.approx(previous_close)
    assert curve["equity"].gt(0).all()
    assert ledger["status"].iloc[0] == "closed"


def test_metrics_are_computed_from_daily_equity_and_known_drawdown():
    curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]),
            "equity": [100.0, 110.0, 88.0, 105.6],
            "gross_exposure": [0.0, 1.0, 1.0, 0.0],
            "turnover": [0.0, 1.0, 0.0, 1.0],
            "costs": [0.0, 0.1, 0.0, 0.1],
        }
    )
    trades = pd.DataFrame(
        {
            "entry_date": ["2020-01-03", "2020-01-06"],
            "exit_date": ["2020-01-06", "2020-01-07"],
            "net_return": [-0.2, 0.2],
            "gross_return": [-0.2, 0.2],
        }
    )
    metrics = compute_portfolio_metrics(curve, trades)
    assert metrics["max_drawdown"] == pytest.approx(-0.2)
    assert metrics["total_return"] == pytest.approx(0.056)
    assert metrics["turnover"] == pytest.approx(2.0)
    assert metrics["average_exposure"] == pytest.approx(0.5)
    assert metrics["trades"] == 2
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["profit_factor"] == pytest.approx(1.0)
    assert all(math.isfinite(float(value)) for value in metrics.values())


@pytest.mark.parametrize(
    "equity",
    [
        [100.0, np.nan],
        [100.0, np.inf],
        [100.0, 0.0],
        [100.0, -1.0],
    ],
)
def test_metrics_reject_non_finite_or_non_positive_equity(equity: list[float]):
    curve = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-02", "2020-01-03"]), "equity": equity}
    )
    with pytest.raises(ValueError, match="equity"):
        compute_portfolio_metrics(curve, pd.DataFrame())


def test_metrics_reject_unsorted_or_duplicate_dates():
    unsorted = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-03", "2020-01-02"]),
            "equity": [100.0, 101.0],
        }
    )
    with pytest.raises(ValueError, match="date"):
        compute_portfolio_metrics(unsorted, pd.DataFrame())
    duplicated = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
            "equity": [100.0, 101.0],
        }
    )
    with pytest.raises(ValueError, match="date"):
        compute_portfolio_metrics(duplicated, pd.DataFrame())


def test_yearly_returns_come_from_equity_curve():
    curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2019-01-02", "2019-12-31", "2020-01-02", "2020-12-31"]),
            "equity": [100.0, 110.0, 110.0, 99.0],
        }
    )
    result = yearly_returns(curve)
    assert result.set_index("year").loc[2019, "return"] == pytest.approx(0.1)
    assert result.set_index("year").loc[2020, "return"] == pytest.approx(-0.1)
