from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.run_gtbi_clean_portfolio import (
    build_concentration_summary,
    load_strategy_payload,
    parse_float_grid,
    parse_int_grid,
    validate_selected_result,
)


def test_load_strategy_payload_finds_exact_id_in_shard(tmp_path) -> None:
    shards = tmp_path / "shards"
    shards.mkdir()
    wanted = {"strategy_id": "lhv1_x_fam_00_v0201", "schema_version": "test"}
    (shards / "shard_001.jsonl").write_text(
        json.dumps({"strategy_id": "other"}) + "\n" + json.dumps(wanted) + "\n",
        encoding="utf-8",
    )

    assert load_strategy_payload(tmp_path, wanted["strategy_id"]) == wanted


def test_grid_parsers_are_deterministic_and_reject_invalid_values() -> None:
    assert parse_float_grid("0.01, 0.005,0.01") == [0.005, 0.01]
    assert parse_int_grid("20,10,20") == [10, 20]
    with pytest.raises(ValueError, match="position sizes"):
        parse_float_grid("0,0.01")
    with pytest.raises(ValueError, match="max positions"):
        parse_int_grid("0,20")


def test_concentration_summary_detects_single_trade_and_symbol_dependence() -> None:
    ledger = pd.DataFrame(
        {
            "original_symbol": ["A", "B", "B"],
            "net_pnl": [80.0, 10.0, 10.0],
            "portfolio_trade_return_pct": [8.0, 1.0, 1.0],
        }
    )

    summary = build_concentration_summary(ledger, initial_capital=1_000.0)

    assert summary["top_trade_positive_pnl_share"] == pytest.approx(0.8)
    assert summary["top_symbol_positive_pnl_share"] == pytest.approx(0.8)
    assert summary["return_without_top_10_trades_pct"] == pytest.approx(0.0)


def test_validate_selected_result_enforces_risk_locked_and_accounting() -> None:
    selected = {
        "train_max_drawdown_pct": -20.0,
        "validation_max_drawdown_pct": -21.0,
        "train_worst_year_pct": -15.0,
        "validation_worst_year_pct": -18.0,
    }
    annual = pd.DataFrame({"split": ["train", "validation"], "year": [2010, 2020]})
    equity = pd.DataFrame(
        {
            "split": ["train", "validation"],
            "date": pd.to_datetime(["2010-12-31", "2020-12-31"]),
            "cash": [10.0, 20.0],
            "open_positions": [0, 0],
            "gross_exposure": [0.0, 0.0],
        }
    )

    validate_selected_result(selected, annual, equity, locked_start="2021-01-01", risk_limit_pct=25.0)

    invalid = dict(selected, validation_worst_year_pct=-25.0)
    with pytest.raises(ValueError, match="risk limit"):
        validate_selected_result(invalid, annual, equity, locked_start="2021-01-01", risk_limit_pct=25.0)
    locked = annual.copy()
    locked.loc[len(locked)] = ["validation", 2021]
    with pytest.raises(ValueError, match="locked"):
        validate_selected_result(selected, locked, equity, locked_start="2021-01-01", risk_limit_pct=25.0)

