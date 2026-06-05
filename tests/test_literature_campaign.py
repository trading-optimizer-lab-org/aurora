from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from aurora.research.literature_campaign import build_campaign_inputs, load_campaign_config


def _exactness_csv(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "study_id": "W1",
                "idea_id": "lit_w1",
                "strategy_family": "momentum",
                "signal_formula": "12 month momentum signal",
                "asset_universe": "S&P 500 ETFs",
                "tradable_assets": "SPY QQQ",
                "frequency": "monthly",
                "position_rule": "long winners and short losers",
                "thresholds": "rank signal",
                "lookback_windows": "12 months",
                "sample_period": "1995-2020",
                "benchmark": "SPY",
                "exactness_status": "exact_replicable",
                "exactness_status_after_review": "exact_replicable",
                "evidence_quote_refs": json.dumps(
                    {
                        "formula": "12 month momentum signal",
                        "universe": "S&P 500 ETFs",
                        "direction": "long winners and short losers",
                        "frequency": "monthly",
                    }
                ),
            },
            {
                "study_id": "W2",
                "idea_id": "lit_w2",
                "strategy_family": "volatility_timing",
                "signal_formula": "VIX volatility signal",
                "asset_universe": "S&P 500 ETFs",
                "tradable_assets": "SPY",
                "frequency": "daily",
                "position_rule": "reduce exposure when volatility rises",
                "thresholds": "volatility rank",
                "lookback_windows": "63 days",
                "sample_period": "1995-2020",
                "benchmark": "SPY",
                "exactness_status": "template_replicable",
                "exactness_status_after_review": "template_replicable",
                "evidence_quote_refs": json.dumps(
                    {
                        "formula": "VIX volatility signal",
                        "universe": "S&P 500 ETFs",
                        "direction": "reduce exposure",
                        "frequency": "daily",
                    }
                ),
            },
            {
                "study_id": "W3",
                "idea_id": "lit_w3",
                "strategy_family": "mystery",
                "signal_formula": "",
                "asset_universe": "",
                "tradable_assets": "",
                "frequency": "",
                "position_rule": "",
                "thresholds": "",
                "lookback_windows": "",
                "sample_period": "",
                "benchmark": "",
                "exactness_status": "exact_replicable",
                "exactness_status_after_review": "exact_replicable",
                "evidence_quote_refs": "{}",
            },
        ]
    ).to_csv(path, index=False)


def _config(path: Path, exactness: Path, **overrides: object) -> Path:
    raw = {
        "campaign_id": "test_campaign",
        "objective": "test objective",
        "sources": {
            "local_exactness_csv": str(exactness),
            "local_text_corpus": "missing.zst",
            "search_external": False,
            "external_queries": [],
        },
        "rules": {
            "allow_exact": True,
            "allow_proxy": True,
            "allow_template": False,
            "require_full_text_evidence": True,
            "forbid_invented_proxies": True,
            "min_lag_days": 1,
            "locked_start": "2021-01-01",
            "locked_opened": False,
        },
        "universe": {
            "allow_assets": ["ETF", "rates", "macro", "volatility_index"],
            "forbid_assets": [],
            "require_data_available": True,
        },
        "backtest": {
            "train_start": "1995-01-01",
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "benchmark": "SPY",
            "size_grid": [0, 1, 2],
            "choose_size_on_train_only": True,
        },
        "ranking": {
            "primary_metric": "train_score",
            "tie_breakers": ["train_sharpe"],
        },
        "github": {
            "chunks": 2,
            "max_parallel": 2,
        },
    }
    for dotted, value in overrides.items():
        section, key = dotted.split("__", 1)
        raw[section][key] = value
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_campaign_config_validates_locked_and_train_only_size(tmp_path: Path) -> None:
    exactness = tmp_path / "exactness.csv"
    _exactness_csv(exactness)
    cfg = _config(tmp_path / "campaign.yaml", exactness)

    loaded = load_campaign_config(cfg)

    assert loaded.campaign_id == "test_campaign"
    assert loaded.locked_start == "2021-01-01"


def test_campaign_config_rejects_open_locked_or_validation_size(tmp_path: Path) -> None:
    exactness = tmp_path / "exactness.csv"
    _exactness_csv(exactness)
    open_locked = _config(tmp_path / "open_locked.yaml", exactness, rules__locked_opened=True)
    bad_size = _config(tmp_path / "bad_size.yaml", exactness, backtest__choose_size_on_train_only=False)
    bad_ranking = _config(tmp_path / "bad_ranking.yaml", exactness, ranking__primary_metric="validation_sharpe")

    with pytest.raises(ValueError, match="locked_opened=false"):
        load_campaign_config(open_locked)
    with pytest.raises(ValueError, match="train only"):
        load_campaign_config(bad_size)
    with pytest.raises(ValueError, match="validation is report_only"):
        load_campaign_config(bad_ranking)


def test_campaign_builds_specs_and_unsupported_reasons(tmp_path: Path) -> None:
    exactness = tmp_path / "exactness.csv"
    _exactness_csv(exactness)
    cfg = load_campaign_config(_config(tmp_path / "campaign.yaml", exactness))

    built = build_campaign_inputs(cfg)
    specs = built["specs"]
    unsupported = built["unsupported"]

    assert len(specs) == 1
    assert specs.iloc[0]["example_study_id"] == "W1"
    assert specs.iloc[0]["source_text_ref"]
    assert bool(specs.iloc[0]["paper_exact_replication_claimed"]) is False
    assert set(unsupported["unsupported_reason"]) == {
        "exactness_status_not_allowed",
        "missing_required_evidence",
    }


def test_campaign_scripts_smoke_build_chunk_merge(tmp_path: Path) -> None:
    exactness = tmp_path / "exactness.csv"
    _exactness_csv(exactness)
    cfg = _config(tmp_path / "campaign.yaml", exactness)
    built = tmp_path / "built"
    chunk = tmp_path / "chunk"
    merged = tmp_path / "merged"

    subprocess.run(
        [sys.executable, "scripts/build_literature_campaign_specs.py", "--config", str(cfg), "--output-dir", str(built)],
        check=True,
        capture_output=True,
        text=True,
    )
    specs = pd.read_csv(built / "campaign_strategy_specs.csv")
    assert len(specs) == 1

    subprocess.run(
        [
            sys.executable,
            "scripts/run_literature_campaign_backtest_chunk.py",
            "--config",
            str(cfg),
            "--specs",
            str(built / "campaign_strategy_specs.csv"),
            "--chunk-index",
            "0",
            "--chunks",
            "1",
            "--output-dir",
            str(chunk),
            "--synthetic-smoke",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/merge_literature_campaign_backtest.py",
            "--config",
            str(cfg),
            "--input-dir",
            str(chunk),
            "--output-dir",
            str(merged),
            "--expected-chunks",
            "1",
            "--expected-specs",
            "1",
            "--max-parallel-requested",
            "2",
            "--prepare-dir",
            str(built),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads((merged / "campaign_summary.json").read_text(encoding="utf-8"))
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    assert (merged / "campaign_leaderboard.csv").exists()
    assert (merged / "campaign_backtest_train.csv").exists()
    assert (merged / "campaign_sp500_down_months.csv").exists()
    assert (merged / "campaign_top20_diverse.csv").exists()
    assert (merged / "campaign_studies.csv").exists()
    assert (merged / "campaign_rule_extraction.csv").exists()
    assert (merged / "campaign_strategy_specs.csv").exists()
    top = pd.read_csv(merged / "campaign_top20_diverse.csv")
    assert bool(top.iloc[0]["diverse_selected"]) is True
    assert "validation_sp500_down_month_avg_return_pct" in top.columns


def test_real_1995_campaign_config_is_strict() -> None:
    cfg = load_campaign_config("config/literature_campaign_sp500_down_alpha_20_real_1995_v1.yaml")

    assert cfg.campaign_id == "sp500_down_alpha_20_real_1995_v1"
    assert cfg.require_effective_start == "1995-01-01"
    assert cfg.raw["rules"]["sp500_down_horizon"] == "months"
    assert cfg.raw["diversity"]["target_count"] == 20
    assert cfg.raw["ranking"]["primary_metric"] == "train_sp500_down_month_avg_return_pct"
    assert cfg.chunks == 355
    assert cfg.max_parallel == 355


def test_curated_sp500_down_paper_campaign_builds_clean_specs() -> None:
    cfg = load_campaign_config("config/literature_campaign_sp500_down_papers_curated_v1.yaml")

    built = build_campaign_inputs(cfg)
    specs = built["specs"]
    unsupported = built["unsupported"]

    assert cfg.campaign_id == "sp500_down_papers_curated_v1"
    assert cfg.chunks == 355
    assert cfg.max_parallel == 355
    assert len(specs) >= 300
    assert len(unsupported) == 21
    assert set(unsupported["primary_family"]) == {"statistical_safety"}
    assert set(unsupported["unsupported_reason"]) == {"unsupported_not_a_trading_strategy"}
    assert specs["example_study_id"].str.startswith("curated_").all()
    assert specs["source_exactness"].eq("proxy_or_template_source").all()
    assert specs["paper_exact_replication_claimed"].eq(False).all()
    assert specs["locked_opened"].eq(False).all()
    assert specs["validation_used_for_selection"].eq(False).all()
    assert "volatility_timing" in set(specs["primary_family"])
    assert "ml_cross_section_asset_pricing" in set(specs["primary_family"])


def test_campaign_merge_rejects_late_start_finalist(tmp_path: Path) -> None:
    from scripts.merge_literature_campaign_backtest import merge_campaign

    exactness = tmp_path / "exactness.csv"
    _exactness_csv(exactness)
    cfg = _config(
        tmp_path / "campaign.yaml",
        exactness,
        rules__require_effective_start_lte="1995-01-01",
        ranking__primary_metric="train_sp500_down_month_avg_return_pct",
    )
    input_dir = tmp_path / "chunks"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    pd.DataFrame(
        [
            {
                "signature_hash": "late",
                "candidate_id": "lit_late",
                "distinct_strategy_signature": "x",
                "primary_family": "momentum",
                "asset_bucket": "equity_index",
                "signal_bucket": "momentum_trend",
                "action_bucket": "forecast_rank_template",
                "frequency_bucket": "monthly",
                "parameter_bucket": "12m",
                "example_study_id": "W1",
                "example_idea_id": "lit_w1",
                "example_title": "Late paper",
                "source_text_ref": "{}",
                "rule_summary": "late rule",
                "fidelity_caveat": "exact source, Aurora template backtest",
                "source_exactness": "exact_source",
                "status": "evaluated",
                "unsupported_reason": "",
                "error": "",
                "effective_start": "1998-01-01",
                "train_score": 1.0,
                "validation_sharpe": 1.0,
                "validation_mdd": -0.1,
                "validation_sp500_down_month_avg_return_pct": 2.0,
                "validation_sp500_down_month_positive_pct": 70.0,
                "locked_opened": False,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
            }
        ]
    ).to_csv(input_dir / "literature_strategy_backtest_chunk_000.csv", index=False)
    pd.DataFrame([{"signature_hash": "late"}]).to_csv(
        input_dir / "literature_strategy_backtest_chunk_000_manifest.csv",
        index=False,
    )

    with pytest.raises(SystemExit, match="empty after required 1995-01-01 start"):
        merge_campaign(
            argparse.Namespace(
                config=str(cfg),
                input_dir=str(input_dir),
                output_dir=str(output_dir),
                expected_chunks=1,
                expected_specs=1,
                max_parallel_requested=2,
                prepare_dir="",
            )
        )


def test_literature_campaign_workflow_shape() -> None:
    path = Path(".github/workflows/literature-campaign-to-backtest.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Literature Campaign To Backtest"
    assert "campaign_config" in data[True]["workflow_dispatch"]["inputs"]
    assert data["permissions"]["models"] == "read"
    assert "scripts/validate_literature_campaign.py" in text
    assert "scripts/build_literature_campaign_specs.py" in text
    assert "scripts/run_literature_campaign_backtest_chunk.py" in text
    assert "scripts/merge_literature_campaign_backtest.py" in text
    assert "scripts/run_sp500_weekly_hedge_dehb_stage.py" not in text
    assert "locked_opened" not in data["env"]
    assert "backtest_chunks_a" in data["jobs"]
    assert "backtest_chunks_b" in data["jobs"]
    assert "chunk_list_a" in text
    assert "chunk_list_b" in text
