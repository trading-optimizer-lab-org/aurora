from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from scripts.run_body_wick_sr_15m_backtest import (
    FINAL_ARTIFACT_NAME,
    StrategyVariant,
    build_variant_catalog,
    compute_zone_from_candle,
    detect_trades_for_symbol,
    run_merge,
    run_shard,
)


def make_bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close"])
    frame["Volume"] = 1_000
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.set_index("timestamp")


def base_variant(**overrides: object) -> StrategyVariant:
    values = {
        "variant_id": "test_variant",
        "side": "long",
        "zone_method": "body_wick",
        "setup_candle": "color",
        "min_range_atr": 0.0,
        "touch_rule": "wick_intersects",
        "confirmation_rule": "color_and_close_beyond_touch_close",
        "invalidation_rule": "wick_break",
        "max_zone_age_bars": 26,
        "exit_rule": "time",
        "hold_bars": 2,
        "stop_buffer_atr": 0.0,
        "target_r": 1.0,
    }
    values.update(overrides)
    return StrategyVariant(**values)


def test_support_zone_is_body_edge_to_lower_wick_for_bearish_candle() -> None:
    candle = pd.Series({"Open": 105.0, "High": 106.0, "Low": 99.0, "Close": 101.0})

    zone = compute_zone_from_candle(candle, side="long", zone_method="body_wick", atr=2.0)

    assert zone is not None
    assert zone.bottom == pytest.approx(99.0)
    assert zone.top == pytest.approx(101.0)


def test_resistance_zone_is_body_edge_to_upper_wick_for_bullish_candle() -> None:
    candle = pd.Series({"Open": 100.0, "High": 107.0, "Low": 99.0, "Close": 104.0})

    zone = compute_zone_from_candle(candle, side="short", zone_method="body_wick", atr=2.0)

    assert zone is not None
    assert zone.bottom == pytest.approx(104.0)
    assert zone.top == pytest.approx(107.0)


def test_long_enters_only_on_next_green_confirmation_after_support_touch() -> None:
    bars = make_bars(
        [
            ("2026-01-02 09:30", 105, 106, 99, 101),
            ("2026-01-02 09:45", 103, 104, 101.5, 103),
            ("2026-01-02 10:00", 103, 104, 100.5, 102),
            ("2026-01-02 10:15", 102, 105, 101.8, 104),
            ("2026-01-02 10:30", 104, 106, 103, 105),
        ]
    )

    trades = detect_trades_for_symbol(bars, "AAA", base_variant())

    assert len(trades) == 1
    assert trades[0]["entry_time"] == "2026-01-02 10:15:00"
    assert trades[0]["side"] == "long"


def test_long_does_not_enter_when_next_candle_after_touch_is_red() -> None:
    bars = make_bars(
        [
            ("2026-01-02 09:30", 105, 106, 99, 101),
            ("2026-01-02 09:45", 103, 104, 101.5, 103),
            ("2026-01-02 10:00", 103, 104, 100.5, 102),
            ("2026-01-02 10:15", 102, 103, 100.8, 101),
            ("2026-01-02 10:30", 101, 102, 100, 101.5),
        ]
    )

    trades = detect_trades_for_symbol(bars, "AAA", base_variant())

    assert trades == []


def test_short_zone_is_invalidated_if_price_wicks_above_resistance_top_before_touch() -> None:
    bars = make_bars(
        [
            ("2026-01-02 09:30", 100, 107, 99, 104),
            ("2026-01-02 09:45", 103, 108, 102, 103),
            ("2026-01-02 10:00", 103, 106, 102, 103),
            ("2026-01-02 10:15", 103, 104, 99, 100),
            ("2026-01-02 10:30", 100, 101, 98, 99),
        ]
    )

    trades = detect_trades_for_symbol(
        bars,
        "AAA",
        base_variant(side="short", confirmation_rule="color_and_close_beyond_touch_close"),
    )

    assert trades == []


def test_short_enters_when_resistance_is_touched_without_break_and_next_candle_is_red() -> None:
    bars = make_bars(
        [
            ("2026-01-02 09:30", 100, 107, 99, 104),
            ("2026-01-02 09:45", 103, 103.9, 102, 103),
            ("2026-01-02 10:00", 103, 106, 102, 103),
            ("2026-01-02 10:15", 103, 103.2, 99, 100),
            ("2026-01-02 10:30", 100, 101, 98, 99),
        ]
    )

    trades = detect_trades_for_symbol(
        bars,
        "AAA",
        base_variant(side="short", confirmation_rule="color_and_close_beyond_touch_close"),
    )

    assert len(trades) == 1
    assert trades[0]["entry_time"] == "2026-01-02 10:15:00"
    assert trades[0]["side"] == "short"


def test_variant_catalog_contains_zone_entry_invalidation_and_exit_versions() -> None:
    catalog = build_variant_catalog()

    assert len(catalog) >= 100
    assert {v.side for v in catalog} == {"long", "short"}
    assert {"body_wick", "deep_half", "atr_buffered"} <= {v.zone_method for v in catalog}
    assert {"wick_break", "close_break"} <= {v.invalidation_rule for v in catalog}
    assert {26, 78, 156} <= {v.max_zone_age_bars for v in catalog}
    assert {"time", "zone_stop_target", "zone_stop_time"} <= {v.exit_rule for v in catalog}


def test_zone_expires_after_max_age_without_entry() -> None:
    rows = [("2026-01-02 09:30", 105, 106, 99, 101)]
    for i in range(1, 6):
        rows.append((f"2026-01-02 {9 + i // 2:02d}:{30 if i % 2 == 0 else 45}", 103, 104, 102, 103))
    rows.extend(
        [
            ("2026-01-02 12:30", 103, 104, 100.5, 102),
            ("2026-01-02 12:45", 102, 105, 101.8, 104),
        ]
    )

    trades = detect_trades_for_symbol(bars=make_bars(rows), symbol="AAA", variant=base_variant(max_zone_age_bars=2))

    assert trades == []


def test_shard_and_merge_write_expected_outputs_without_using_locked_for_selection(tmp_path: Path) -> None:
    source = tmp_path / "source" / "data"
    source.mkdir(parents=True)
    for symbol in ["AAA", "BBB", "SPY"]:
        bars = make_bars(
            [
                ("2026-01-02 09:30", 105, 106, 99, 101),
                ("2026-01-02 09:45", 103, 104, 101.5, 103),
                ("2026-01-02 10:00", 103, 104, 100.5, 102),
                ("2026-01-02 10:15", 102, 105, 101.8, 104),
                ("2026-01-02 10:30", 104, 106, 103, 105),
                ("2026-01-02 10:45", 105, 106, 104, 105.5),
                ("2026-01-02 11:00", 105.5, 106, 104.5, 105),
                ("2026-01-02 11:15", 105, 106, 104, 105.2),
                ("2026-01-02 11:30", 105.2, 106, 104, 105.1),
            ]
        )
        bars.to_csv(source / f"{symbol}_15m.csv", index_label="timestamp")

    out = tmp_path / "out"
    run_shard(out, input_dir=tmp_path / "source", stage=0, total_stages=400, min_symbols=3, cost_bps=0.0)
    run_merge(out, target_sharpe=0.0)

    shard = pd.read_csv(out / "shards" / "stage_000" / "leaderboard.csv")
    final = pd.read_csv(out / "final" / "leaderboard.csv")
    manifest = json.loads((out / "final" / "manifest.json").read_text(encoding="utf-8"))

    assert not shard.empty
    assert not final.empty
    assert "locked_sharpe" in final.columns
    assert set(manifest["symbols"]) == {"AAA", "BBB", "SPY"}
    assert manifest["selection_policy"] == "train_ranks_validation_filters_locked_reported_only"


def test_merge_handles_empty_trade_shards(tmp_path: Path) -> None:
    shard = tmp_path / "out" / "shards" / "stage_000"
    shard.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "variant_id": "empty",
                "side": "long",
                "zone_method": "body_wick",
                "setup_candle": "color",
                "min_range_atr": 0.0,
                "touch_rule": "wick_intersects",
                "confirmation_rule": "color_only",
                "invalidation_rule": "wick_break",
                "max_zone_age_bars": 26,
                "exit_rule": "time",
                "hold_bars": 2,
                "stop_buffer_atr": 0.0,
                "target_r": 1.0,
                "trade_count": 0,
                "train_sharpe": 0.0,
                "validation_sharpe": 0.0,
                "locked_sharpe": 0.0,
                "validation_trades": 0,
                "locked_trades": 0,
                "locked_profit_factor": 0.0,
            }
        ]
    ).to_csv(shard / "leaderboard.csv", index=False)
    pd.DataFrame().to_csv(shard / "trades.csv", index=False)

    run_merge(tmp_path / "out", target_sharpe=0.0)

    manifest = json.loads((tmp_path / "out" / "final" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["variant_count"] == 1
    assert manifest["symbol_count"] == 0


def test_workflow_is_manual_and_targets_20_equities_plus_spy() -> None:
    path = Path(".github/workflows/body-wick-sr-15m-21symbols-backtest.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Body Wick S/R 15m 20 Equities Plus SPY Backtest"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert data[True]["workflow_dispatch"]["inputs"]["source_run_id"]["default"] == "27498064404"
    assert data[True]["workflow_dispatch"]["inputs"]["source_artifact"]["default"] == "free-15m-equity-universe-yfinance-data"
    assert data[True]["workflow_dispatch"]["inputs"]["jobs"]["default"] == "80"
    assert "SPY_15m.csv" in text
    assert "min-symbols 21" in text
    assert FINAL_ARTIFACT_NAME in text
