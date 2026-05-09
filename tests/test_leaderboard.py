"""Tests for quantforge.research.leaderboard."""
from __future__ import annotations
import pytest

from aurora.research.leaderboard import LeaderboardEntry, StrategyLeaderboard


def test_submit_and_latest():
    lb = StrategyLeaderboard()
    e = lb.submit("user1", "strat1", calmar=1.5, sharpe=1.2, cagr=0.15, mdd=-0.1)
    assert isinstance(e, LeaderboardEntry)
    assert e.version == 1
    latest = lb.latest("user1", "strat1")
    assert latest is not None
    assert latest.version == 1
    assert latest.calmar == 1.5


def test_versioning_increments():
    lb = StrategyLeaderboard()
    lb.submit("u", "s", 1.0, 1.0, 0.1, -0.1)
    e2 = lb.submit("u", "s", 1.5, 1.2, 0.15, -0.1)
    assert e2.version == 2
    e3 = lb.submit("u", "s", 2.0, 1.3, 0.20, -0.1)
    assert e3.version == 3
    hist = lb.history("u", "s")
    assert [h.version for h in hist] == [1, 2, 3]


def test_top_by_calmar_descending():
    lb = StrategyLeaderboard()
    lb.submit("u", "a", 1.0, 1.0, 0.1, -0.1)
    lb.submit("u", "b", 3.0, 2.0, 0.3, -0.1)
    lb.submit("u", "c", 2.0, 1.5, 0.2, -0.1)
    top = lb.top("calmar", n=3)
    assert [t.strategy_name for t in top] == ["b", "c", "a"]


def test_top_by_mdd_ascending():
    lb = StrategyLeaderboard()
    lb.submit("u", "a", 1.0, 1.0, 0.1, -0.20)
    lb.submit("u", "b", 1.0, 1.0, 0.1, -0.05)
    top = lb.top("mdd", n=2)
    # mdd ascending: -0.20 first
    assert top[0].strategy_name == "a"


def test_top_metric_invalid():
    lb = StrategyLeaderboard()
    with pytest.raises(ValueError):
        lb.top("alpha", n=1)


def test_top_n_zero():
    lb = StrategyLeaderboard()
    with pytest.raises(ValueError):
        lb.top("calmar", n=0)


def test_top_returns_only_latest_version():
    lb = StrategyLeaderboard()
    lb.submit("u", "a", 1.0, 1.0, 0.1, -0.1)
    lb.submit("u", "a", 5.0, 1.0, 0.1, -0.1)  # latest version, calmar=5
    lb.submit("u", "b", 3.0, 1.0, 0.1, -0.1)
    top = lb.top("calmar", n=10)
    names = [e.strategy_name for e in top]
    assert names[0] == "a"  # latest 5.0 beats b 3.0
    assert top[0].calmar == 5.0


def test_all_users_and_count():
    lb = StrategyLeaderboard()
    lb.submit("u1", "a", 1.0, 1.0, 0.1, -0.1)
    lb.submit("u2", "a", 2.0, 1.0, 0.1, -0.1)
    lb.submit("u1", "b", 1.5, 1.0, 0.1, -0.1)
    assert sorted(lb.all_users()) == ["u1", "u2"]
    assert lb.count() == 3


def test_submit_invalid_inputs():
    lb = StrategyLeaderboard()
    with pytest.raises(ValueError):
        lb.submit("", "s", 1.0, 1.0, 0.1, -0.1)
    with pytest.raises(ValueError):
        lb.submit("u", "", 1.0, 1.0, 0.1, -0.1)


def test_latest_unknown_returns_none():
    lb = StrategyLeaderboard()
    assert lb.latest("ghost", "ghost") is None


def test_persistence_via_file(tmp_path):
    db = tmp_path / "lb.sqlite"
    lb1 = StrategyLeaderboard(db_path=str(db))
    lb1.submit("u", "s", 1.0, 1.0, 0.1, -0.1)
    lb1.close()
    lb2 = StrategyLeaderboard(db_path=str(db))
    assert lb2.count() == 1
    lb2.close()
