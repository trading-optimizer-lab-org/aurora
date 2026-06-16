from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.sp500_26_paper_replication_backtest import (
    Paper26Config,
    build_strategy_returns,
    evaluate_spec,
    load_paper26_config,
    run_specs_chunk,
    synthetic_dataset,
)


def test_sp500_26_specs_load_and_have_expected_ids() -> None:
    config, specs, raw = load_paper26_config("config/sp500_26_paper_replication_specs.yaml")

    assert config.expected_specs == 26
    assert [spec["paper_id"] for spec in specs] == list(range(1, 27))
    assert raw["locked_start"] == "2021-01-01"
    assert raw["paper_exact_replication_claimed"] is False


def test_intraday_and_lei_are_cleanly_unsupported() -> None:
    config, specs, _ = load_paper26_config("config/sp500_26_paper_replication_specs.yaml")
    dataset = synthetic_dataset()
    by_id = {spec["paper_id"]: spec for spec in specs}

    intraday = evaluate_spec(by_id[3], dataset, config)
    lei = evaluate_spec(by_id[25], dataset, config)

    assert {row["status"] for row in intraday["results"]} == {"unsupported"}
    assert {row["unsupported_reason"] for row in intraday["results"]} == {"unsupported_missing_intraday_data"}
    assert {row["status"] for row in lei["results"]} == {"unsupported"}
    assert {row["unsupported_reason"] for row in lei["results"]} == {"unsupported_missing_conference_board_lei"}


def test_strategy_returns_are_lagged_one_period() -> None:
    config, specs, _ = load_paper26_config("config/sp500_26_paper_replication_specs.yaml")
    dataset = synthetic_dataset()
    ma_spec = next(spec for spec in specs if spec["strategy_type"] == "ma_timing")

    strategy = build_strategy_returns(ma_spec, dataset, config)
    position = strategy["position"]

    first_non_zero = position.ne(0.0).idxmax()
    assert pd.Timestamp(first_non_zero) > pd.Timestamp(config.train_start)


def test_chunk_outputs_locked_and_validation_policy_flags_false() -> None:
    config, specs, _ = load_paper26_config("config/sp500_26_paper_replication_specs.yaml")
    dataset = synthetic_dataset()

    results, annual, monthly, summary = run_specs_chunk(
        specs,
        dataset,
        config,
        chunk_index=0,
        chunks=26,
    )

    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    assert bool(results["locked_opened"].astype(bool).any()) is False
    assert bool(results["validation_used_for_selection"].astype(bool).any()) is False
    assert bool(results["paper_exact_replication_claimed"].astype(bool).any()) is False
    assert set(results["view"]) == {"paper_like", "aurora_comparable"}
    assert isinstance(annual, pd.DataFrame)
    assert isinstance(monthly, pd.DataFrame)


def test_validation_end_before_locked_start() -> None:
    config = Paper26Config(validation_end="2021-01-01", locked_start="2021-01-01")

    with pytest.raises(ValueError, match="validation_end"):
        _ = run_bad_config_validation(config)


def run_bad_config_validation(config: Paper26Config) -> None:
    from aurora.research.sp500_26_paper_replication_backtest import validate_specs

    validate_specs(
        config,
        [
            {
                "paper_id": idx,
                "slug": f"s{idx}",
                "fidelity_status": "paper_like_exact",
                "primary": True,
            }
            for idx in range(1, 27)
        ],
    )
