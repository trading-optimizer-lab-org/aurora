from __future__ import annotations

import numpy as np
import pandas as pd


def test_global_robustness_counts_trials_dedupes_and_never_uses_sharpe() -> None:
    from aurora.infra.sp500_megarun.dehb_global_robustness import (
        evaluate_global_robustness,
    )

    rng = np.random.default_rng(42)
    index = pd.bdate_range("2000-01-03", periods=320)
    spy = pd.Series(rng.normal(0.0001, 0.001, len(index)), index=index)
    returns = pd.DataFrame(
        {
            "winner": spy.to_numpy() + 0.002,
            "weak": spy.to_numpy() - 0.0002,
        },
        index=index,
    )
    report = evaluate_global_robustness(
        returns,
        spy,
        finalist_ids=("winner", "weak"),
        raw_trial_count=1000,
        strategy_fingerprints={"winner": "f1", "weak": "f2"},
        seed=9,
        bootstrap_samples=64,
        alpha=0.10,
        maximum_pbo=0.50,
    )

    assert report["raw_trial_count"] == 1000
    assert report["unique_candidate_count"] == 2
    assert report["uses_sharpe"] is False
    assert report["pbo"]["uses_sharpe"] is False
    assert report["model_confidence_set"]["uses_sharpe"] is False
    assert set(report["finalists"]["winner"]["gates"]) == {
        "43", "44", "45", "46", "47", "48"
    }
    assert report["finalists"]["winner"]["trial_count_penalty_uses_raw_trials"] == 1000
    assert report["finalists"]["winner"]["trial_count_threshold"] > 0.0
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


def test_geometric_pbo_prefers_stable_geometric_winner_without_sharpe() -> None:
    from aurora.infra.sp500_megarun.dehb_global_robustness import (
        geometric_cscv_pbo,
    )

    frame = pd.DataFrame(
        {
            "stable": np.full(320, 0.002),
            "loser": np.full(320, -0.001),
        }
    )
    report = geometric_cscv_pbo(frame, partitions=16, seed=3)

    assert report["pbo"] == 0.0
    assert report["uses_sharpe"] is False
    assert report["selection_metric"] == "mean_log_strategy_return"
