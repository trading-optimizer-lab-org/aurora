from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from aurora.research.literature_strategy_backtest import (
    LiteratureBacktestConfig,
    candidate_id_from_signature,
    evaluate_signature,
    load_signatures,
    run_chunk,
    signature_to_spec,
)
from scripts.build_literature_sharpe2_signature_variants import build_variants


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "signature_hash": "abc123",
        "distinct_strategy_signature": "momentum|equity_index|momentum_trend|forecast_rank_template|monthly|12m",
        "rows": 1,
        "exact_rows": 1,
        "template_rows": 0,
        "primary_family": "momentum",
        "asset_bucket": "equity_index",
        "signal_bucket": "momentum_trend",
        "action_bucket": "forecast_rank_template",
        "frequency_bucket": "monthly",
        "parameter_bucket": "12m",
        "example_study_id": "W1",
        "example_idea_id": "lit_w1",
        "example_title": "Paper",
    }
    row.update(overrides)
    return row


def _dataset() -> dict[str, object]:
    idx = pd.date_range("1995-01-03", "2020-12-31", freq="B")
    base = np.sin(np.arange(len(idx)) / 19.0) * 0.002 + 0.0002
    prices = pd.DataFrame(
        {
            "SPY": 100.0 * np.cumprod(1.0 + base),
            "QQQ": 80.0 * np.cumprod(1.0 + base * 1.2),
            "TLT": 90.0 * np.cumprod(1.0 - base * 0.4 + 0.0001),
        },
        index=idx,
    )
    returns = prices.pct_change()
    context = pd.DataFrame(
        {
            "VIXCLS": 20.0 + np.cos(np.arange(len(idx)) / 13.0),
            "DGS10": 3.0 + np.sin(np.arange(len(idx)) / 250.0),
        },
        index=idx,
    )
    return {
        "prices": prices,
        "returns": returns,
        "context": context,
        "symbols_by_bucket": {
            "equity_index": ("SPY", "QQQ"),
            "rates_fixed_income": ("TLT",),
        },
        "locked_opened": False,
    }


def _late_symbol_dataset() -> dict[str, object]:
    idx = pd.date_range("1995-01-03", "2020-12-31", freq="B")
    base = np.sin(np.arange(len(idx)) / 19.0) * 0.002 + 0.0002
    spy = pd.Series(100.0 * np.cumprod(1.0 + base), index=idx)
    qqq = pd.Series(80.0 * np.cumprod(1.0 + base * 1.2), index=idx)
    qqq.loc[qqq.index < "2003-01-01"] = np.nan
    prices = pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)
    return {
        "prices": prices,
        "returns": prices.pct_change(),
        "context": pd.DataFrame(index=idx),
        "symbols_by_bucket": {"equity_index": ("SPY", "QQQ")},
        "locked_opened": False,
    }


def test_manifest_has_9419_unique_signatures() -> None:
    frame = load_signatures("config/literature_strategy_signatures_9419.csv", expected=9419)

    assert len(frame) == 9419
    assert frame["signature_hash"].nunique() == 9419


def test_signature_to_spec_is_stable_and_candidate_id_ignores_chunk() -> None:
    row = _row()
    spec, reason = signature_to_spec(row, _dataset())

    assert reason == ""
    assert spec["symbols"] == ("SPY", "QQQ")
    assert spec["frequency"] == "monthly"
    assert candidate_id_from_signature(row) == candidate_id_from_signature(dict(row))


def test_required_start_filters_late_symbols() -> None:
    config = LiteratureBacktestConfig(require_data_start_lte="1995-01-01")
    spec, reason = signature_to_spec(_row(), _late_symbol_dataset(), config)

    assert reason == ""
    assert spec["symbols"] == ("SPY",)


def test_required_start_rejects_strategy_when_all_symbols_are_late() -> None:
    dataset = _late_symbol_dataset()
    dataset["prices"] = dataset["prices"].loc[:, ["QQQ"]]
    dataset["returns"] = dataset["returns"].loc[:, ["QQQ"]]
    dataset["symbols_by_bucket"] = {"equity_index": ("QQQ",)}
    config = LiteratureBacktestConfig(require_data_start_lte="1995-01-01")

    out = evaluate_signature(_row(), dataset, config)

    assert out["status"] == "unsupported"
    assert out["unsupported_reason"] == "unsupported_no_asset_mapping"


def test_unsupported_cases_are_explicit() -> None:
    intraday, intraday_reason = signature_to_spec(_row(frequency_bucket="intraday"), _dataset())
    missing_asset, missing_asset_reason = signature_to_spec(_row(asset_bucket="unknown"), _dataset())
    missing_signal, missing_signal_reason = signature_to_spec(_row(signal_bucket="unknown"), _dataset())

    assert intraday == {}
    assert intraday_reason == "unsupported_frequency_intraday"
    assert missing_asset == {}
    assert missing_asset_reason == "unsupported_no_asset_mapping"
    assert missing_signal == {}
    assert missing_signal_reason == "unsupported_no_signal_mapping"


def test_evaluate_signature_uses_train_size_and_keeps_validation_report_only() -> None:
    out = evaluate_signature(_row(), _dataset(), LiteratureBacktestConfig())

    assert out["status"] == "evaluated"
    assert out["locked_opened"] is False
    assert out["validation_used_for_selection"] is False
    assert out["paper_exact_replication_claimed"] is False
    assert out["train_observations"] > 0
    assert out["validation_observations"] > 0
    assert "train_sharpe" in out
    assert "validation_sharpe" in out
    assert "train_sp500_down_true_positive_count" in out
    assert "train_sp500_down_false_negative_count" in out
    assert "train_sp500_down_false_positive_count" in out
    assert "validation_sp500_down_precision_pct" in out


def test_evaluate_signature_respects_config_size_grid() -> None:
    out = evaluate_signature(_row(), _dataset(), LiteratureBacktestConfig(size_grid=(0.0, 0.25)))

    assert out["status"] == "evaluated"
    assert out["size_chosen_train"] in {0.0, 0.25}


def test_intraday_is_not_backtested_without_intraday_dataset() -> None:
    out = evaluate_signature(_row(frequency_bucket="intraday"), _dataset(), LiteratureBacktestConfig())

    assert out["status"] == "unsupported"
    assert out["unsupported_reason"] == "unsupported_frequency_intraday"


def test_run_chunk_covers_expected_slice() -> None:
    signatures = pd.DataFrame([_row(signature_hash=f"h{i}") for i in range(10)])

    rows, manifest, summary = run_chunk(
        signatures,
        _dataset(),
        LiteratureBacktestConfig(expected_signatures=10),
        chunk_index=1,
        chunks=3,
    )

    assert summary["start"] == 3
    assert summary["end"] == 6
    assert len(rows) == 3
    assert len(manifest) == 3
    assert summary["locked_opened"] is False


def test_merge_fails_when_chunks_missing_or_duplicates(tmp_path: Path) -> None:
    from scripts.merge_literature_strategy_backtest_chunks import merge

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    row = {
        "signature_hash": "a",
        "candidate_id": "lit_a",
        "distinct_strategy_signature": "x",
        "primary_family": "momentum",
        "asset_bucket": "equity_index",
        "signal_bucket": "momentum_trend",
        "action_bucket": "market_timing",
        "frequency_bucket": "monthly",
        "parameter_bucket": "12m",
        "example_study_id": "W1",
        "example_idea_id": "I1",
        "example_title": "Paper",
        "source_text_ref": "{}",
        "rule_summary": "rule",
        "fidelity_caveat": "template",
        "source_exactness": "template_only",
        "status": "evaluated",
        "unsupported_reason": "",
        "error": "",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "train_score": 1.0,
        "validation_sharpe": 1.0,
    }
    pd.DataFrame([row]).to_csv(
        input_dir / "literature_strategy_backtest_chunk_000.csv",
        index=False,
    )

    with pytest.raises(SystemExit, match="expected 2 chunks"):
        merge(argparse.Namespace(input_dir=str(input_dir), output_dir=str(output_dir), expected_chunks=2, expected_signatures=1, max_parallel_requested=180))

    partial_summary = merge(
        argparse.Namespace(
            input_dir=str(input_dir),
            output_dir=str(output_dir / "partial"),
            expected_chunks=2,
            expected_signatures=2,
            max_parallel_requested=180,
            allow_partial=True,
        )
    )
    assert partial_summary["partial"] is True
    assert partial_summary["chunks_missing"] == [1]

    pd.DataFrame([row]).to_csv(
        input_dir / "literature_strategy_backtest_chunk_001.csv",
        index=False,
    )
    with pytest.raises(SystemExit, match="duplicate signature_hash"):
        merge(argparse.Namespace(input_dir=str(input_dir), output_dir=str(output_dir), expected_chunks=2, expected_signatures=2, max_parallel_requested=180))


def test_chunk_script_smoke_with_synthetic_manifest(tmp_path: Path) -> None:
    signatures = tmp_path / "signatures.csv"
    out = tmp_path / "out"
    pd.DataFrame(
        [
            _row(signature_hash="m1", signal_bucket="momentum_trend"),
            _row(signature_hash="v1", signal_bucket="volatility_signal"),
            _row(signature_hash="c1", asset_bucket="bonds_rates", signal_bucket="carry_yield"),
            _row(signature_hash="i1", frequency_bucket="intraday"),
            _row(signature_hash="x1", asset_bucket="unknown"),
        ]
    ).to_csv(signatures, index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_literature_strategy_backtest_chunk.py",
            "--signatures",
            str(signatures),
            "--expected-signatures",
            "5",
            "--chunk-index",
            "0",
            "--chunks",
            "1",
            "--output-dir",
            str(out),
            "--synthetic-smoke",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)
    rows = pd.read_csv(next(out.glob("literature_strategy_backtest_chunk_000.csv")))

    assert summary["locked_opened"] is False
    assert int((rows["status"] == "evaluated").sum()) == 3
    assert int((rows["status"] == "unsupported").sum()) == 2


def test_workflow_shape_for_literature_strategy_backtest_9419() -> None:
    path = Path(".github/workflows/literature-strategy-backtest-9419-9h.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Literature Strategy Backtest 9419 9h"
    assert data["env"]["EXPECTED_SIGNATURES"] == "9419"
    assert data["env"]["CHUNKS"] == "180"
    assert data["env"]["LOCKED_START"] == "2021-01-01"
    assert data["jobs"]["chunk"]["strategy"]["max-parallel"] == 180
    assert len(data["jobs"]["chunk"]["strategy"]["matrix"]["chunk"]) == 180
    assert "scripts/run_literature_strategy_backtest_chunk.py" in text
    assert "scripts/run_sp500_weekly_hedge_dehb_stage.py" not in text
    assert "literature-strategy-backtest-9419-9h-results" in text


def test_sharpe2_variant_builder_preserves_paper_traceability() -> None:
    source = pd.DataFrame(
        [
            _row(
                signature_hash="paper1",
                exact_rows=3,
                template_rows=0,
                primary_family="momentum",
                asset_bucket="equity_index",
                signal_bucket="momentum_trend",
                action_bucket="market_timing",
                frequency_bucket="monthly",
                parameter_bucket="12m",
                example_study_id="W123",
                example_idea_id="lit_w123",
                example_title="A paper-backed timing rule",
            )
        ]
    )

    variants = build_variants(source, max_variants=20)

    assert not variants.empty
    assert variants["signature_hash"].is_unique
    assert variants["example_study_id"].eq("W123").all()
    assert variants["paper_exact_replication_claimed"].eq(False).all()
    assert variants["locked_opened"].eq(False).all()
    assert variants["validation_used_for_selection"].eq(False).all()
    assert variants["source_text_ref"].str.contains('"paper_based": true').all()


def test_sharpe2_merge_writes_acceptance_file(tmp_path: Path) -> None:
    from scripts.merge_literature_strategy_backtest_chunks import merge

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    row = {
        "signature_hash": "pass1",
        "candidate_id": "lit_pass1",
        "distinct_strategy_signature": "paper|equity_index|momentum_trend|market_timing|monthly|12m",
        "primary_family": "momentum",
        "asset_bucket": "equity_index",
        "signal_bucket": "momentum_trend",
        "action_bucket": "market_timing",
        "frequency_bucket": "monthly",
        "parameter_bucket": "12m",
        "example_study_id": "W1",
        "example_idea_id": "I1",
        "example_title": "Paper",
        "source_text_ref": "{}",
        "rule_summary": "rule",
        "fidelity_caveat": "paper-derived proxy",
        "source_exactness": "exact_source",
        "status": "evaluated",
        "unsupported_reason": "",
        "error": "",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "train_score": 5.0,
        "train_sharpe": 2.1,
        "validation_sharpe": 2.2,
    }
    pd.DataFrame([row]).to_csv(input_dir / "literature_strategy_backtest_chunk_000.csv", index=False)

    summary = merge(
        argparse.Namespace(
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            expected_chunks=1,
            expected_signatures=1,
            max_parallel_requested=360,
        )
    )

    accepted = pd.read_csv(output_dir / "literature_strategy_backtest_sharpe2_pass.csv")
    assert summary["sharpe2_pass_count"] == 1
    assert accepted.iloc[0]["candidate_id"] == "lit_pass1"
    assert "acceptance_reason" in accepted.columns


def test_sharpe2_paper_variants_workflow_shape() -> None:
    path = Path(".github/workflows/literature-sharpe2-paper-variants-360jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Literature Sharpe2 Paper Variants 360 Jobs"
    assert data["env"]["LOCKED_START"] == "2021-01-01"
    assert data["env"]["SOURCE_SIGNATURES"] == "config/literature_strategy_signatures_9419.csv"
    assert data[True]["workflow_dispatch"]["inputs"]["max_parallel_requested"]["default"] == "360"
    assert "scripts/build_literature_sharpe2_signature_variants.py" in text
    assert "literature_strategy_backtest_sharpe2_pass.csv" not in text
    assert "literature-sharpe2-paper-variants-results" in text


def test_scripts_py_compile() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "research/literature_strategy_backtest.py",
            "scripts/run_literature_strategy_backtest_chunk.py",
            "scripts/merge_literature_strategy_backtest_chunks.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
