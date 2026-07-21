"""Contracts for causal, capital-free stock-protocol event-study execution."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.independent_opportunity_executor import (
    STATUSES,
    execute_independent_opportunities,
    prepare_opportunity_execution_context,
)
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.variants import map_exit_rule


CANONICAL_MANIFEST = (
    Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"
)


def _artifact_exit_rules() -> list[tuple[int, int, dict[str, object], dict[str, object]]]:
    manifest = load_protocol_manifest(CANONICAL_MANIFEST)
    rules: list[tuple[int, int, dict[str, object], dict[str, object]]] = []
    for protocol_test in manifest.tests:
        if protocol_test.test_id not in range(21, 27):
            continue
        for variant_index, variant in enumerate(protocol_test.variants):
            materialized = map_exit_rule(protocol_test.test_id, variant)
            rules.append(
                (
                    protocol_test.test_id,
                    variant_index,
                    dict(variant),
                    materialized,
                )
            )
    return rules


ARTIFACT_EXIT_RULES = _artifact_exit_rules()


def _panel(frame: pd.DataFrame) -> ResearchPanel:
    source = frame.copy()
    source["date"] = pd.to_datetime(source["date"])
    if "adj_close" not in source:
        source["adj_close"] = source["close"]
    for column, default in (
        ("volume", 1_000_000.0),
        ("dividends", 0.0),
        ("stock_splits", 0.0),
    ):
        if column not in source:
            source[column] = default
    audit = PackAudit(
        source_root="synthetic",
        output_root="synthetic",
        data_start=str(source["date"].min().date()),
        data_end=str(source["date"].max().date()),
        rows=len(source),
        symbols=source["symbol"].nunique(),
        locked_rows=0,
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash="synthetic",
    )
    return ResearchPanel(source, audit)


def _prices(
    periods: int = 12,
    *,
    start: str = "2020-01-02",
    symbol: str = "AAA",
) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    opens = 100.0 + np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": opens,
            "high": opens + 2.0,
            "low": opens - 2.0,
            "close": opens + 1.0,
            "adj_close": opens + 1.0,
        }
    )


def _split_prices(periods: int = 260, *, split_index: int = 2) -> pd.DataFrame:
    prices = _prices(periods=periods)
    adjusted_open = 100.0 + np.arange(periods, dtype=float)
    raw_multiplier = np.where(np.arange(periods) < split_index, 2.0, 1.0)
    prices["open"] = adjusted_open * raw_multiplier
    prices["high"] = (adjusted_open + 2.0) * raw_multiplier
    prices["low"] = (adjusted_open - 2.0) * raw_multiplier
    prices["close"] = (adjusted_open + 1.0) * raw_multiplier
    prices["adj_close"] = adjusted_open + 1.0
    prices["stock_splits"] = 0.0
    prices.loc[split_index, "stock_splits"] = 2.0
    return prices


def _signals(*dates: str, symbol: str = "AAA") -> pd.DataFrame:
    timestamps = pd.to_datetime(list(dates))
    return pd.DataFrame(
        {
            "selection_date": timestamps,
            "entry_signal_date": timestamps,
            "available_at": timestamps,
            "symbol": symbol,
            "score": 1.0,
            "atr20": 2.0,
            "vol_12_1": 0.2,
        }
    )


def _execute(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    rule: dict[str, object],
    **kwargs: object,
) -> pd.DataFrame:
    requested_cutoff = kwargs.pop("cutoff", prices["date"].max())
    return execute_independent_opportunities(
        signals,
        _panel(prices),
        rule,
        combination_id="combination-7",
        cutoff=requested_cutoff,
        **kwargs,
    )


def test_overlapping_signals_each_create_an_independent_opportunity() -> None:
    signals = _signals("2020-01-02", "2020-01-03")

    result = _execute(
        signals,
        _prices(),
        {"kind": "none", "holding_sessions": 4},
    )

    assert len(result) == 2
    assert result["entry_date"].tolist() == ["2020-01-03", "2020-01-06"]
    assert result["status"].eq("completed").all()
    assert result["exit_date"].tolist() == ["2020-01-09", "2020-01-10"]


def test_outcomes_and_ids_do_not_depend_on_input_order() -> None:
    prices = _prices()
    signals = _signals("2020-01-02", "2020-01-03")
    rule = {"kind": "none", "holding_sessions": 2}

    forward = _execute(signals, prices, rule)
    reverse = _execute(signals.iloc[::-1].reset_index(drop=True), prices, rule)

    columns = ["opportunity_id", "entry_date", "exit_date", "gross_return"]
    pd.testing.assert_frame_equal(
        forward[columns].sort_values("opportunity_id").reset_index(drop=True),
        reverse[columns].sort_values("opportunity_id").reset_index(drop=True),
    )
    first = forward.iloc[0]
    identity = [
        "combination-7",
        "AAA",
        "2020-01-02",
        "2020-01-02",
        "2020-01-03",
    ]
    expected = hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert first["opportunity_id"] == expected


def test_prepared_context_reuses_adjusted_groups_across_exit_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.research.stock_protocol import independent_opportunity_executor as module

    calls = Counter()
    original = module._adjust_execution_ohlc

    def counted(frame: pd.DataFrame) -> pd.DataFrame:
        calls["adjust"] += 1
        return original(frame)

    monkeypatch.setattr(module, "_adjust_execution_ohlc", counted)
    prices = _prices(periods=12)
    panel = _panel(prices)
    context = prepare_opportunity_execution_context(
        panel, cutoff=prices["date"].max()
    )
    group_id = id(context.groups["AAA"])

    for holding in range(1, 30):
        execute_independent_opportunities(
            _signals("2020-01-02"),
            panel,
            {"kind": "none", "holding_sessions": holding},
            combination_id=f"combination-{holding}",
            cutoff=prices["date"].max(),
            prepared_context=context,
        )

    assert calls == Counter({"adjust": 1})
    assert id(context.groups["AAA"]) == group_id


def test_international_coverage_uses_observed_market_sessions_not_nyse() -> None:
    vod = _prices(periods=3, start="2024-07-01", symbol="VOD-L")
    vod["date"] = pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03"])
    peer = _prices(periods=4, start="2024-07-01", symbol="BARC-L")
    peer["date"] = pd.to_datetime(
        ["2024-07-01", "2024-07-02", "2024-07-03", "2024-07-04"]
    )
    panel = _panel(pd.concat([vod, peer], ignore_index=True))
    context = prepare_opportunity_execution_context(panel, cutoff="2024-07-04")

    result = execute_independent_opportunities(
        _signals("2024-07-02", symbol="VOD-L"),
        panel,
        {"kind": "none", "holding_sessions": 10},
        combination_id="london-coverage",
        cutoff="2024-07-04",
        prepared_context=context,
    ).iloc[0]

    assert result["status"] == "failed_due_to_data"
    assert result["censor_reason"] == "symbol_coverage_ended_before_dataset_cutoff"
    assert result["coverage_market"] == "United Kingdom"
    assert result["coverage_exchange"] == "LSE"
    assert result["coverage_calendar_source"] == (
        "fallback_observed_market_exchange_sessions"
    )


def test_explicit_market_metadata_overrides_unsuffixed_us_convention() -> None:
    target = _prices(periods=3, start="2024-07-01", symbol="AAA")
    peer = _prices(periods=4, start="2024-07-01", symbol="BBB")
    source = pd.concat([target, peer], ignore_index=True)
    source["market"] = "Japan"
    source["exchange"] = "Tokyo"
    panel = _panel(source)

    result = execute_independent_opportunities(
        _signals("2024-07-02", symbol="AAA"),
        panel,
        {"kind": "none", "holding_sessions": 10},
        combination_id="explicit-tokyo-metadata",
        cutoff="2024-07-04",
    ).iloc[0]

    assert result["status"] == "failed_due_to_data"
    assert result["coverage_market"] == "Japan"
    assert result["coverage_exchange"] == "Tokyo"
    assert result["coverage_calendar_source"] == (
        "fallback_observed_market_exchange_sessions"
    )


def test_unknown_market_fallback_does_not_invent_peer_sessions() -> None:
    prices = _prices(periods=3, start="2024-07-01", symbol="MYSTERY-ZZ")
    panel = _panel(prices)

    result = execute_independent_opportunities(
        _signals("2024-07-01", symbol="MYSTERY-ZZ"),
        panel,
        {"kind": "none", "holding_sessions": 10},
        combination_id="unknown-market",
        cutoff=prices["date"].max(),
    ).iloc[0]

    assert result["status"] == "right_censored"
    assert result["coverage_calendar_source"] == (
        "fallback_observed_symbol_sessions_unknown_market"
    )


def test_volatility_is_measured_on_the_realized_path_and_entry_gap_is_recorded() -> None:
    prices = _prices(periods=6)
    prices["close"] = [100.0, 110.0, 99.0, 118.0, 103.0, 121.0]
    prices["adj_close"] = prices["close"]
    prices["high"] = prices[["open", "close"]].max(axis=1) + 1.0
    prices["low"] = prices[["open", "close"]].min(axis=1) - 1.0
    signals = _signals("2020-01-02")
    signals["vol_12_1"] = 9.99
    signals["adj_close"] = 100.0

    result = _execute(
        signals,
        prices,
        {"kind": "none", "holding_sessions": 3},
    ).iloc[0]

    expected = prices.loc[1:4, "close"].pct_change(fill_method=None).dropna().std(
        ddof=1
    ) * np.sqrt(252.0)
    assert result["trajectory_volatility"] == pytest.approx(expected)
    assert result["volatility"] == pytest.approx(expected)
    assert result["volatility"] != 9.99
    assert result["entry_gap"] == pytest.approx(prices.loc[1, "open"] / 100.0 - 1.0)
    assert result["remaining_sessions_estimate"] == 0


def test_follow_up_continues_beyond_entry_cohort_year_and_fold() -> None:
    prices = _prices(periods=9, start="2019-12-27")
    signal = _signals("2019-12-31").assign(fold_id="fold-2019", period="2019")

    result = _execute(
        signal,
        prices,
        {"kind": "none", "holding_sessions": 3},
    ).iloc[0]

    assert result["entry_date"] == "2020-01-01"
    assert result["exit_date"] == "2020-01-06"
    assert result["fold_id"] == "fold-2019"
    assert result["period"] == "2019"


def test_catastrophe_atr_is_fixed_at_entry_and_gap_executes_at_open() -> None:
    prices = _prices()
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 103.0, 98.0, 102.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [95.0, 97.0, 93.0, 96.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]
    prices["atr20"] = [2.0, 2.0, 50.0] + [50.0] * (len(prices) - 3)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "catastrophe_atr", "k": 2.0, "holding_sessions": 6},
    ).iloc[0]

    assert result["exit_date"] == "2020-01-06"
    assert result["exit_price"] == 95.0
    assert result["exit_reason"] == "gap_through_stop"
    assert result["stop_hit"]


def test_target_gap_uses_open_and_intrabar_conflict_uses_stop_first() -> None:
    prices = _prices()
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [111.0, 112.0, 109.0, 111.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]
    target = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "take_profit", "target_pct": 10.0, "holding_sessions": 6},
    ).iloc[0]
    assert target["exit_price"] == 111.0
    assert target["exit_reason"] == "gap_through_target"
    assert target["target_hit"]

    conflict_prices = _prices()
    conflict_prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 106.0, 94.0, 101.0]
    conflict_prices.loc[1, "adj_close"] = conflict_prices.loc[1, "close"]
    conflict = _execute(
        _signals("2020-01-02"),
        conflict_prices,
        {
            "kind": "stop_and_target",
            "stop_pct": 5.0,
            "target_pct": 5.0,
            "holding_sessions": 6,
        },
    ).iloc[0]
    assert conflict["exit_price"] == pytest.approx(95.0)
    assert conflict["optimistic_exit_price"] == pytest.approx(105.0)
    assert conflict["exit_reason"] == "stop_target_conflict_conservative"
    assert conflict["stop_hit"] and not conflict["target_hit"]


@pytest.mark.parametrize(
    ("kind", "history", "expected_level"),
    [
        ("min_10", 10, 90.0),
        ("min_20", 20, 80.0),
        ("sma_50", 50, 100.0),
    ],
)
def test_dynamic_levels_use_only_bars_before_current_session(
    kind: str,
    history: int,
    expected_level: float,
) -> None:
    periods = history + 4
    prices = _prices(periods=periods)
    if kind.startswith("min"):
        prices.loc[: history - 1, "low"] = np.linspace(expected_level, 110.0, history)
    else:
        prices.loc[: history - 1, "adj_close"] = expected_level
    entry_index = history
    prices.loc[entry_index, ["open", "high", "low", "close"]] = [
        110.0,
        112.0,
        expected_level - 5.0,
        111.0,
    ]
    prices.loc[entry_index, "adj_close"] = prices.loc[entry_index, "close"]
    signal_date = prices.loc[entry_index - 1, "date"]

    result = _execute(
        _signals(str(signal_date.date())),
        prices,
        {"kind": kind, "holding_sessions": 2},
    ).iloc[0]

    assert result["exit_price"] == pytest.approx(expected_level)
    assert result["exit_reason"] == "stop"


def test_trailing_atr_uses_entry_atr_and_prior_causal_high() -> None:
    prices = _prices()
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 120.0, 99.0, 118.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [110.0, 112.0, 108.0, 109.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "trailing_atr", "k": 3.0, "holding_sessions": 6},
    ).iloc[0]

    assert result["entry_date"] == "2020-01-03"
    assert result["exit_date"] == "2020-01-06"
    assert result["exit_price"] == 110.0
    assert result["exit_reason"] == "gap_through_stop"


def test_split_adjustment_keeps_atr_and_execution_ohlc_on_one_scale() -> None:
    prices = _split_prices(periods=8, split_index=2)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "catastrophe_atr", "k": 3.0, "holding_sessions": 2},
    ).iloc[0]

    assert result["entry_price"] == pytest.approx(prices.loc[1, "adj_close"] - 1.0)
    assert result["exit_price"] == pytest.approx(prices.loc[3, "adj_close"])
    assert result["exit_reason"] == "time_exit"
    assert result["gross_return"] == pytest.approx(104.0 / 101.0 - 1.0)


def test_breakout_level_is_compared_with_adjusted_entry_bar() -> None:
    prices = _split_prices(periods=8, split_index=3)

    result = _execute(
        _signals("2020-01-02").assign(breakout_level=100.0),
        prices,
        {"kind": "breakout_failure", "failure_window": 2, "holding_sessions": 4},
    ).iloc[0]

    assert result["entry_price"] == pytest.approx(101.0)
    assert result["exit_price"] == pytest.approx(100.0)
    assert result["exit_reason"] == "stop"


def test_sma50_and_entry_bar_are_both_adjusted_before_comparison() -> None:
    prices = _split_prices(periods=56, split_index=52)
    prices.loc[51, "low"] = 120.0 * 2.0
    expected_sma = float(prices.loc[1:50, "adj_close"].mean())

    result = _execute(
        _signals(str(prices.loc[50, "date"].date())),
        prices,
        {"kind": "sma_50", "holding_sessions": 3},
    ).iloc[0]

    assert result["entry_price"] == pytest.approx(151.0)
    assert result["exit_price"] == pytest.approx(expected_sma)
    assert result["exit_reason"] == "stop"


def test_missing_adjustment_factor_is_not_backfilled_from_future_bar() -> None:
    prices = _prices(periods=5)
    prices.loc[1, "adj_close"] = np.nan

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 2},
    ).iloc[0]

    assert result["status"] == "failed_due_to_data"
    assert result["censor_reason"] == "invalid_entry_open"


def test_breakout_failure_requires_real_level_and_tracks_differ() -> None:
    prices = _prices(periods=7)
    signal = _signals("2020-01-02")
    rule = {"kind": "breakout_failure", "failure_window": 2, "holding_sessions": 2}

    exact = _execute(signal, prices, rule, track="exact_track").iloc[0]
    corrected = _execute(signal, prices, rule, track="corrected_track").iloc[0]

    assert exact["status"] == "completed"
    assert exact["applicability"] == "historical_fallback"
    assert exact["time_exit"]
    assert corrected["status"] == "right_censored"
    assert corrected["applicability"] == "not_applicable"
    assert corrected["censor_reason"] == "exit_rule_not_applicable"
    assert pd.isna(corrected["exit_price"])
    assert pd.isna(corrected["gross_return"])
    assert not corrected["time_exit"]
    assert pd.notna(corrected["mtm_return"])

    real = signal.assign(breakout_level=100.5)
    real_result = _execute(real, prices, rule, track="corrected_track").iloc[0]
    assert real_result["status"] == "completed"
    assert real_result["exit_price"] == pytest.approx(100.5)
    assert real_result["stop_hit"]


def test_ranking_hysteresis_uses_causal_keep_set_and_exits_next_open() -> None:
    prices = _prices(periods=8)
    keep = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2020-01-03", "2020-01-06"]),
            "available_at": pd.to_datetime(["2020-01-03", "2020-01-06"]),
            "symbol": ["AAA", "BBB"],
        }
    )

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "ranking_hysteresis", "holding_sessions": 6},
        ranking_keep=keep,
    ).iloc[0]

    assert result["exit_date"] == "2020-01-07"
    assert result["exit_price"] == prices.loc[3, "open"]
    assert result["exit_reason"] == "ranking_hysteresis_next_open"

    noncausal = keep.assign(available_at=pd.Timestamp("2020-01-10"))
    with pytest.raises(ValueError, match="causal"):
        _execute(
            _signals("2020-01-02"),
            prices,
            {"kind": "ranking_hysteresis", "holding_sessions": 6},
            ranking_keep=noncausal,
        )


def test_cutoff_before_max_holding_is_right_censored_with_separate_mtm() -> None:
    prices = _prices(periods=4)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 10},
    ).iloc[0]

    assert result["status"] == "right_censored"
    assert result["censor_reason"] == "dataset_cutoff_before_max_holding"
    assert pd.isna(result["exit_date"])
    assert pd.isna(result["exit_price"])
    assert pd.isna(result["gross_return"])
    assert not result["time_exit"]
    assert result["mtm_date"] == "2020-01-07"
    assert result["mtm_price"] == prices.iloc[-1]["close"]
    assert result["mtm_return"] == pytest.approx(
        prices.iloc[-1]["close"] / prices.iloc[1]["open"] - 1.0
    )


def test_weekend_cutoff_uses_last_contractual_trading_session() -> None:
    prices = _prices(periods=2)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 10},
        cutoff="2020-01-05",
    ).iloc[0]

    assert result["status"] == "right_censored"
    assert result["censor_reason"] == "dataset_cutoff_before_max_holding"


def test_global_dataset_end_before_contractual_cutoff_fails_before_entry() -> None:
    prices = _prices(periods=3)

    result = _execute(
        _signals("2020-01-06"),
        prices,
        {"kind": "none", "holding_sessions": 2},
        cutoff="2020-01-08",
    ).iloc[0]

    assert result["status"] == "failed_due_to_data"
    assert result["censor_reason"] == "dataset_ended_before_contractual_cutoff"


def test_global_dataset_end_before_contractual_cutoff_fails_after_entry() -> None:
    prices = _prices(periods=4)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 10},
        cutoff="2020-01-09",
    ).iloc[0]

    assert result["status"] == "failed_due_to_data"
    assert result["censor_reason"] == "dataset_ended_before_contractual_cutoff"
    assert pd.notna(result["mtm_price"])


def test_symbol_coverage_ending_before_dataset_is_data_failure_unless_delisted() -> None:
    aaa = _prices(periods=4)
    bbb = _prices(periods=6, symbol="BBB")
    combined = pd.concat([aaa, bbb], ignore_index=True)

    failed = _execute(
        _signals("2020-01-02"),
        combined,
        {"kind": "none", "holding_sessions": 10},
    ).iloc[0]

    assert failed["status"] == "failed_due_to_data"
    assert failed["censor_reason"] == "symbol_coverage_ended_before_dataset_cutoff"
    assert pd.isna(failed["exit_price"])
    assert pd.notna(failed["mtm_price"])

    undated = combined.copy()
    undated["delisting_documented"] = False
    undated.loc[undated["symbol"].eq("AAA"), "delisting_documented"] = True
    undated_result = _execute(
        _signals("2020-01-02"),
        undated,
        {"kind": "none", "holding_sessions": 10},
    ).iloc[0]
    assert undated_result["status"] == "failed_due_to_data"
    assert undated_result["censor_reason"] == (
        "symbol_coverage_ended_before_dataset_cutoff"
    )

    documented = combined.copy()
    documented["delisting_date"] = pd.NaT
    documented.loc[documented["symbol"].eq("AAA"), "delisting_date"] = pd.Timestamp(
        "2020-01-08"
    )
    delisted = _execute(
        _signals("2020-01-02"),
        documented,
        {"kind": "none", "holding_sessions": 10},
    ).iloc[0]
    assert delisted["status"] == "right_censored"
    assert delisted["censor_reason"] == "documented_delisting_before_max_holding"
    assert delisted["delisting_date"] == "2020-01-08"

    unexplained = documented.copy()
    unexplained.loc[unexplained["symbol"].eq("AAA"), "delisting_date"] = pd.Timestamp(
        "2020-01-10"
    )
    unexplained_result = _execute(
        _signals("2020-01-02"),
        unexplained,
        {"kind": "none", "holding_sessions": 10},
    ).iloc[0]
    assert unexplained_result["status"] == "failed_due_to_data"
    assert unexplained_result["censor_reason"] == (
        "symbol_coverage_ended_before_dataset_cutoff"
    )


def test_dated_delisting_can_explain_symbol_end_before_entry() -> None:
    aaa = _prices(periods=2)
    bbb = _prices(periods=4, symbol="BBB")
    prices = pd.concat([aaa, bbb], ignore_index=True)
    prices["delisting_date"] = pd.NaT
    prices.loc[prices["symbol"].eq("AAA"), "delisting_date"] = pd.Timestamp(
        "2020-01-06"
    )

    result = _execute(
        _signals("2020-01-03"),
        prices,
        {"kind": "none", "holding_sessions": 2},
    ).iloc[0]

    assert result["status"] == "entry_censored"
    assert result["censor_reason"] == "documented_delisting_before_entry"
    assert result["delisting_date"] == "2020-01-06"


def test_open_exit_path_metrics_never_use_rest_of_exit_bar() -> None:
    prices = _prices(periods=6)
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [110.0, 1_000.0, 1.0, 500.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "take_profit", "target_pct": 5.0, "holding_sessions": 4},
    ).iloc[0]

    assert result["exit_reason"] == "gap_through_target"
    assert result["exit_price"] == 110.0
    assert result["maximum_favourable_excursion"] == pytest.approx(0.10)
    assert result["maximum_adverse_excursion"] == pytest.approx(0.0)
    assert result["intratrade_max_drawdown"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("rule", "expected_exit", "expected_mfe", "expected_mae", "expected_drawdown"),
    [
        (
            {"kind": "initial_stop_pct", "stop_pct": 5.0, "holding_sessions": 4},
            95.0,
            0.0,
            -0.05,
            -0.05,
        ),
        (
            {"kind": "take_profit", "target_pct": 5.0, "holding_sessions": 4},
            105.0,
            0.05,
            -0.10,
            -0.10,
        ),
    ],
)
def test_intrabar_exit_path_is_bounded_at_execution_conservatively(
    rule: dict[str, object],
    expected_exit: float,
    expected_mfe: float,
    expected_mae: float,
    expected_drawdown: float,
) -> None:
    prices = _prices(periods=6)
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [100.0, 1_000.0, 90.0, 500.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]

    result = _execute(_signals("2020-01-02"), prices, rule).iloc[0]

    assert result["exit_price"] == pytest.approx(expected_exit)
    assert result["maximum_favourable_excursion"] == pytest.approx(expected_mfe)
    assert result["maximum_adverse_excursion"] == pytest.approx(expected_mae)
    assert result["intratrade_max_drawdown"] == pytest.approx(expected_drawdown)


def test_completed_path_reports_excursions_drawdown_duration_and_flags() -> None:
    prices = _prices(periods=6)
    prices.loc[1, ["open", "high", "low", "close"]] = [100.0, 110.0, 95.0, 108.0]
    prices.loc[2, ["open", "high", "low", "close"]] = [107.0, 109.0, 90.0, 92.0]
    prices.loc[[1, 2], "adj_close"] = prices.loc[[1, 2], "close"]

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 1},
    ).iloc[0]

    assert result["status"] == "completed"
    assert result["time_exit"] and result["max_holding_reached"]
    assert not result["stop_hit"] and not result["target_hit"]
    assert result["holding_sessions"] == 1
    assert result["calendar_days_invested"] == 3
    assert result["maximum_favourable_excursion"] == pytest.approx(0.10)
    assert result["maximum_adverse_excursion"] == pytest.approx(-0.10)
    assert result["intratrade_max_drawdown"] == pytest.approx(90.0 / 110.0 - 1.0)


def test_holding_sessions_counts_elapsed_sessions_from_zero() -> None:
    prices = _prices(periods=25)

    result = _execute(
        _signals("2020-01-02"),
        prices,
        {"kind": "none", "holding_sessions": 20},
    ).iloc[0]

    assert result["entry_date"] == str(prices.loc[1, "date"].date())
    assert result["exit_date"] == str(prices.loc[21, "date"].date())
    assert result["holding_sessions"] == 20


def test_non_entry_and_data_states_are_explicit_and_bounded() -> None:
    prices = _prices(periods=3)
    signals = pd.concat(
        [
            _signals("2020-01-02").assign(entry_triggered=False),
            _signals("2020-01-02", symbol="MISSING"),
            _signals("2020-01-06"),
        ],
        ignore_index=True,
    )

    result = _execute(
        signals,
        prices,
        {"kind": "none", "holding_sessions": 2},
    )

    assert result["status"].tolist() == [
        "entry_not_triggered",
        "failed_due_to_data",
        "entry_censored",
    ]
    assert set(result["status"]) <= STATUSES
    assert result["opportunity_id"].nunique() == len(result)


def test_corrected_track_marks_input_non_applicability_without_entry() -> None:
    signal = _signals("2020-01-02").assign(applicable=False)

    corrected = _execute(
        signal,
        _prices(),
        {"kind": "none", "holding_sessions": 2},
        track="corrected_track",
    ).iloc[0]
    exact = _execute(
        signal,
        _prices(),
        {"kind": "none", "holding_sessions": 2},
        track="exact_track",
    ).iloc[0]

    assert corrected["status"] == "entry_not_triggered"
    assert corrected["applicability"] == "not_applicable"
    assert pd.isna(corrected["entry_price"])
    assert exact["status"] == "completed"
    assert exact["applicability"] == "historical_fallback"


def test_stable_identity_requires_a_combination_id() -> None:
    with pytest.raises(ValueError, match="combination_id"):
        execute_independent_opportunities(
            _signals("2020-01-02"),
            _panel(_prices()),
            {"kind": "none", "holding_sessions": 2},
            cutoff="2020-01-10",
        )


def test_artifact_contract_contains_all_29_exit_variants_and_families() -> None:
    assert len(ARTIFACT_EXIT_RULES) == 29
    assert Counter(test_id for test_id, _, _, _ in ARTIFACT_EXIT_RULES) == Counter(
        {
            protocol_test.test_id: len(protocol_test.variants)
            for protocol_test in load_protocol_manifest(CANONICAL_MANIFEST).tests
            if protocol_test.test_id in range(21, 27)
        }
    )


@pytest.mark.parametrize(
    ("test_id", "variant_index", "variant", "rule"),
    [
        pytest.param(*case, id=f"test-{case[0]}-variant-{case[1]}")
        for case in ARTIFACT_EXIT_RULES
    ],
)
def test_every_artifact_derived_exit_rule_executes_with_exact_parameters(
    test_id: int,
    variant_index: int,
    variant: dict[str, object],
    rule: dict[str, object],
) -> None:
    prices = _split_prices(periods=260, split_index=2)
    signal = _signals("2020-01-02").assign(breakout_level=1.0)
    kwargs: dict[str, object] = {}
    if test_id == 21:
        kwargs["ranking_keep"] = pd.DataFrame(
            {
                "signal_date": prices["date"],
                "available_at": prices["date"],
                "symbol": "AAA",
            }
        )

    result = _execute(signal, prices, rule, **kwargs).iloc[0]

    assert result["status"] == "completed"
    assert result["entry_price"] == pytest.approx(101.0)
    assert result["exit_reason"] != "gap_through_stop"
    assert result["gross_return"] > -0.10
    entry_index = int(
        prices.index[prices["date"].eq(pd.Timestamp(result["entry_date"]))][0]
    )
    exit_index = int(
        prices.index[prices["date"].eq(pd.Timestamp(result["exit_date"]))][0]
    )
    assert result["holding_sessions"] == exit_index - entry_index
    assert rule == map_exit_rule(test_id, variant)
    if test_id == 21:
        assert rule["entry_percentile"] == float(variant["entry_percentile"])
        assert rule["keep_percentile"] == float(variant["keep_percentile"])
    elif test_id == 22:
        assert rule["failure_window"] == int(variant["failure_window"])
    elif test_id == 23:
        assert rule["kind"] == str(variant["exit"])
        if rule["kind"] == "trailing_atr":
            assert rule["k"] == float(variant["atr_k"])
    elif test_id == 24:
        expected_kind = (
            "none"
            if str(variant["stop_atr"]).lower() == "none"
            else "catastrophe_atr"
        )
        assert rule["kind"] == expected_kind
        if expected_kind == "catastrophe_atr":
            assert rule["k"] == float(variant["stop_atr"])
    elif test_id == 25:
        assert rule == {
            "kind": "none",
            "holding_sessions": int(variant["holding_sessions"]),
        }
        expected_index = 1 + int(variant["holding_sessions"])
        assert result["exit_date"] == str(prices.iloc[expected_index]["date"].date())
        assert result["exit_price"] == pytest.approx(
            prices.iloc[expected_index]["adj_close"]
        )
        assert result["holding_sessions"] == int(variant["holding_sessions"])
        assert result["time_exit"]
    elif test_id == 26:
        assert rule["target_pct"] == float(variant["target_pct"])
        assert result["target_hit"]
    else:  # pragma: no cover - the canonical exit axis is constrained above
        raise AssertionError(f"unexpected artifact exit test {test_id}/{variant_index}")
