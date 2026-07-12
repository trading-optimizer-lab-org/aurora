from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.run_gtbi_clean_portfolio as runner
from scripts.gtbi_clean_portfolio import DataQualityPolicy
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


def test_train_selection_does_not_use_validation_results() -> None:
    sweep = pd.DataFrame(
        [
            {
                "position_size_pct": 0.01,
                "max_positions": 10,
                "train_max_drawdown_pct": -10.0,
                "train_worst_year_pct": -8.0,
                "train_cagr_pct": 12.0,
                "validation_cagr_pct": -50.0,
            },
            {
                "position_size_pct": 0.02,
                "max_positions": 20,
                "train_max_drawdown_pct": -12.0,
                "train_worst_year_pct": -9.0,
                "train_cagr_pct": 8.0,
                "validation_cagr_pct": 100.0,
            },
        ]
    )
    selected = runner.choose_train_selected_result(sweep, risk_limit_pct=20.0)
    changed = sweep.copy()
    changed["validation_cagr_pct"] = [1_000.0, -1_000.0]
    changed_selected = runner.choose_train_selected_result(changed, risk_limit_pct=20.0)
    assert float(selected["position_size_pct"]) == 0.01
    assert float(changed_selected["position_size_pct"]) == 0.01


def test_train_sizing_row_contains_no_validation_metrics() -> None:
    result = SimpleNamespace(
        summary={
            "ending_equity": 110.0,
            "total_return_pct": 10.0,
            "cagr_pct": 5.0,
            "max_drawdown_pct": -8.0,
            "worst_year_pct": -3.0,
            "positive_years": 7,
            "years": 8,
            "trades_accepted": 100,
            "entries_skipped": 2,
            "max_open_positions": 10,
            "max_gross_exposure": 0.8,
        }
    )
    row = runner._train_sweep_row(position_size=0.01, max_positions=10, train_result=result)
    assert row["train_cagr_pct"] == 5.0
    assert not any(key.startswith("validation_") for key in row)


def test_canonical_dates_are_fixed_and_locked_is_strictly_after_validation() -> None:
    dates = runner.validate_canonical_dates(
        train_start="1993-01-01",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        locked_start="2021-01-01",
    )
    assert dates[-1] == pd.Timestamp("2021-01-01")
    with pytest.raises(ValueError, match="canonical"):
        runner.validate_canonical_dates(
            train_start="1993-01-01",
            train_end="2010-12-31",
            validation_start="2011-01-01",
            validation_end="2020-12-30",
            locked_start="2021-01-01",
        )


def test_benchmark_must_cover_the_complete_train_and_validation_period() -> None:
    complete_index = pd.date_range("1993-01-01", "2020-12-31", freq="B")
    complete = pd.DataFrame({"close": 1.0}, index=complete_index)
    runner.validate_benchmark_coverage(complete, start="1993-01-01", end="2020-12-31")
    missing = (complete.index >= pd.Timestamp("2000-01-01")) & (
        complete.index <= pd.Timestamp("2000-03-31")
    )
    incomplete = complete.loc[~missing]
    with pytest.raises(ValueError, match="cover"):
        runner.validate_benchmark_coverage(incomplete, start="1993-01-01", end="2020-12-31")


def test_only_segments_reaching_period_end_are_eligible() -> None:
    old_dates = pd.date_range("2010-01-01", "2019-12-31", freq="B")
    current_dates = pd.date_range("2015-01-01", "2020-12-30", freq="B")
    segments = {
        "A::segment_000": pd.DataFrame(index=old_dates),
        "A::segment_001": pd.DataFrame(index=current_dates),
    }
    selected = runner.period_covering_segments(segments, end="2020-12-31")
    assert list(selected) == ["A::segment_001"]


def test_run_cannot_be_called_locally_even_when_imported(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    output = tmp_path / "results"
    with pytest.raises(SystemExit, match="GitHub Actions only"):
        runner.run(argparse.Namespace(output_dir=output))
    assert not output.exists()


def test_github_run_requires_a_real_commit_sha(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_SHA"):
        runner._git_sha()
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    assert runner._git_sha() == "a" * 40


def test_parser_defaults_to_whole_shares_and_canonical_train_start() -> None:
    parser = runner.parser()
    args = parser.parse_args(
        [
            "--data-pack-root",
            "data",
            "--strategy-pack-root",
            "strategies",
            "--output-dir",
            "results",
        ]
    )
    assert args.allow_fractional_shares is False
    assert args.train_start == "1993-01-01"


def test_relative_strength_priorities_do_not_use_future_prices() -> None:
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    frame = pd.DataFrame({"date": dates, "close": [10.0, 11.0, 12.0, 13.0, 14.0]}).set_index("date", drop=False)
    benchmark = pd.DataFrame({"date": dates, "close": [10.0] * 5}).set_index("date", drop=False)
    original = runner.build_relative_strength_priorities({"A": frame}, benchmark, lookback=2)["A"]
    changed = frame.copy()
    changed.loc[pd.Timestamp("2020-01-05"), "close"] = 1_000.0
    changed_scores = runner.build_relative_strength_priorities({"A": changed}, benchmark, lookback=2)["A"]
    boundary = pd.Timestamp("2020-01-04")
    pd.testing.assert_series_equal(
        original.loc[original.index <= boundary],
        changed_scores.loc[changed_scores.index <= boundary],
    )
    assert original.loc[pd.Timestamp("2020-01-03")] == pytest.approx(0.2)


def test_sanitized_universe_identity_is_stable_and_changes_with_membership() -> None:
    dates = pd.date_range("2020-01-01", periods=2, freq="D")
    frame = pd.DataFrame({"date": dates}, index=dates)
    first = runner.sanitized_universe_identity({"A::segment_000": frame})
    second = runner.sanitized_universe_identity({"A::segment_000": frame.copy()})
    changed = runner.sanitized_universe_identity({"B::segment_000": frame})
    assert first == second
    assert first != changed


def test_provenance_captures_every_result_changing_runtime_setting() -> None:
    args = runner.parser().parse_args(
        [
            "--data-pack-root",
            "data",
            "--strategy-pack-root",
            "strategies",
            "--output-dir",
            "results",
        ]
    )
    policy = DataQualityPolicy(
        max_adjusted_gap_ratio=args.max_adjusted_gap_ratio,
        min_segment_rows=args.min_segment_rows,
    )
    payload = runner.build_provenance_payload(
        args=args,
        strategy_payload={"strategy_id": args.strategy_id},
        source_file_hashes={"prices.parquet": "1" * 64, "benchmark.parquet": "2" * 64},
        position_sizes=[0.01],
        max_positions_grid=[10],
        policy=policy,
        universe_identity="3" * 64,
        code_sha="4" * 40,
    )
    required = {
        "initial_capital",
        "transaction_cost_bps_per_side",
        "slippage_bps_per_side",
        "allow_fractional_shares",
        "safety_target_pct",
        "risk_limit_pct",
        "max_gross_exposure",
        "data_quality_policy",
        "max_symbols",
        "train_start",
        "selection_method",
        "priority_method",
        "sanitized_universe_identity",
    }
    assert required <= payload.keys()
    original_hash = runner.provenance_hash(payload)
    changed_args = argparse.Namespace(**vars(args))
    changed_args.initial_capital += 1.0
    changed_payload = runner.build_provenance_payload(
        args=changed_args,
        strategy_payload={"strategy_id": args.strategy_id},
        source_file_hashes={"prices.parquet": "1" * 64, "benchmark.parquet": "2" * 64},
        position_sizes=[0.01],
        max_positions_grid=[10],
        policy=policy,
        universe_identity="3" * 64,
        code_sha="4" * 40,
    )
    assert runner.provenance_hash(changed_payload) != original_hash
