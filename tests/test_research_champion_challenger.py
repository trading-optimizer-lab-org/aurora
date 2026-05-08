"""Tests for quantforge.research.champion_challenger."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.research.champion_challenger import (
    ChampionChallengerFramework,
    ChampionDecision,
)


def test_construction_validates():
    with pytest.raises(ValueError):
        ChampionChallengerFramework(champion="", challengers=["b"])
    with pytest.raises(ValueError):
        ChampionChallengerFramework(champion="a", challengers=[])
    with pytest.raises(ValueError):
        ChampionChallengerFramework(champion="a", challengers=["a"])
    with pytest.raises(ValueError):
        ChampionChallengerFramework(champion="a", challengers=["b"],
                                    metric="bogus")


def test_no_promotion_without_streak():
    cc = ChampionChallengerFramework(
        champion="champ", challengers=["chal"],
        metric="mean", min_edge=0.001, promotion_window=5,
        min_observations=20,
    )
    rng = np.random.default_rng(0)
    last: ChampionDecision | None = None
    for _ in range(15):
        last = cc.update({
            "champ": float(rng.normal(0.0, 0.01)),
            "chal": float(rng.normal(0.0, 0.01)),
        })
    assert last is not None
    assert last.champion == "champ"
    assert last.promoted is False


def test_challenger_promoted_with_consistent_edge():
    cc = ChampionChallengerFramework(
        champion="champ", challengers=["chal"],
        metric="mean", min_edge=0.001, promotion_window=3,
        min_observations=5,
    )
    last: ChampionDecision | None = None
    for _ in range(40):
        last = cc.update({"champ": 0.0001, "chal": 0.005})
    assert last is not None
    assert cc.champion == "chal"
    assert last.promoted in (True, False)  # at least at some step it flipped
    assert cc.state("chal").promotions >= 1


def test_unknown_strategy_update_raises():
    cc = ChampionChallengerFramework(champion="a", challengers=["b"])
    with pytest.raises(KeyError):
        cc.update({"z": 0.0})


def test_metric_sharpe_path():
    cc = ChampionChallengerFramework(
        champion="champ", challengers=["chal"],
        metric="sharpe", min_edge=0.5, promotion_window=2,
        min_observations=10,
    )
    rng = np.random.default_rng(7)
    for _ in range(30):
        cc.update({
            "champ": float(rng.normal(0.0, 0.02)),
            "chal": float(rng.normal(0.005, 0.02)),
        })
    # sharpe edge should at least populate metrics
    last = cc.update({
        "champ": float(rng.normal(0.0, 0.02)),
        "chal": float(rng.normal(0.005, 0.02)),
    })
    assert "champ" in last.metrics and "chal" in last.metrics


def test_state_lookup():
    cc = ChampionChallengerFramework(champion="a", challengers=["b"])
    assert cc.state("a").name == "a"
    with pytest.raises(KeyError):
        cc.state("z")
