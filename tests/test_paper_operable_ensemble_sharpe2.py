from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_paper_operable_ensemble_sharpe2 import (
    TARGET_SHARPE,
    candidate_id,
    evaluate_config,
    iter_candidate_configs,
    volatility_scale,
)


def test_volatility_scale_uses_prior_month() -> None:
    idx = pd.date_range("2000-01-31", periods=8, freq="ME")
    returns = pd.Series([0.01, 0.02, -0.03, 0.01, 0.04, -0.02, 0.01, 0.03], index=idx)
    scale = volatility_scale(returns, lookback=3, target=0.02, max_scale=2.0)
    shocked = returns.copy()
    shocked.iloc[-1] = -0.50
    shocked_scale = volatility_scale(shocked, lookback=3, target=0.02, max_scale=2.0)
    assert scale.iloc[-1] == shocked_scale.iloc[-1]
    assert scale.index.equals(returns.index)


def test_evaluate_config_keeps_validation_report_only() -> None:
    idx = pd.date_range("1995-01-31", periods=300, freq="ME")
    returns = pd.DataFrame(
        {
            "paper_a": np.full(len(idx), 0.01),
            "paper_b": np.sin(np.arange(len(idx)) / 6.0) * 0.01,
        },
        index=idx,
    )
    manifest = pd.DataFrame(
        {
            "paper_id": ["paper_a", "paper_b"],
            "paper_title": ["Paper A", "Paper B"],
            "source_url": ["https://example.com/a", "https://example.com/b"],
        }
    )
    config = {"mode": "equal", "ids": ["paper_a", "paper_b"]}
    row = evaluate_config(config, returns, manifest)
    assert row["locked_opened"] is False
    assert row["validation_used_for_selection"] is False
    assert row["uses_individual_stocks"] is False
    assert row["paper_exact_replication_claimed"] is False
    assert row["train_sharpe"] >= TARGET_SHARPE


def test_candidate_id_is_stable() -> None:
    config = {"mode": "equal", "ids": ["b", "a"], "vol_lookback": 6}
    assert candidate_id(config) == candidate_id(dict(config))


def test_stage_config_generation_is_bounded_and_deterministic() -> None:
    ids = [f"paper_{i}" for i in range(10)]
    first = iter_candidate_configs(ids, stage=3, total_stages=20, configs_per_stage=50)
    second = iter_candidate_configs(ids, stage=3, total_stages=20, configs_per_stage=50)
    assert first == second
    assert len(first) <= 100
    assert any("vol_lookback" in cfg for cfg in first)


def test_operable_ensemble_workflow_shape() -> None:
    path = Path(".github/workflows/paper-operable-ensemble-sharpe2-360stages.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "Paper Operable Ensemble Sharpe2 360 Stages"
    assert "workflow_dispatch" in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(180)" in text
    assert "stage_b" in text
    assert "max-parallel: 180" in text
    assert "run_paper_operable_ensemble_sharpe2.py" in text
