"""Tests for aurora.research.wf_tournament."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.wf_tournament import (
    TournamentEntry,
    TournamentReport,
    WalkForwardTournament,
    WindowResult,
)


def _all_long(prices: pd.Series) -> np.ndarray:
    return np.ones(len(prices))


def _all_flat(prices: pd.Series) -> np.ndarray:
    return np.zeros(len(prices))


def _short(prices: pd.Series) -> np.ndarray:
    return -np.ones(len(prices))


def test_basic_tournament_runs(synthetic_prices_daily):
    entries = [
        TournamentEntry("long", _all_long),
        TournamentEntry("flat", _all_flat),
    ]
    t = WalkForwardTournament(train_size=100, test_size=50)
    rep = t.run(synthetic_prices_daily, entries)
    assert isinstance(rep, TournamentReport)
    assert rep.n_windows >= 1
    assert "long" in rep.standings and "flat" in rep.standings


def test_winners_recorded(synthetic_prices_daily):
    entries = [
        TournamentEntry("long", _all_long),
        TournamentEntry("flat", _all_flat),
        TournamentEntry("short", _short),
    ]
    t = WalkForwardTournament(train_size=100, test_size=60)
    rep = t.run(synthetic_prices_daily, entries)
    for w in rep.per_window:
        assert isinstance(w, WindowResult)
        assert w.winner in {"long", "flat", "short"}


def test_leader_returns_str(synthetic_prices_daily):
    entries = [
        TournamentEntry("a", _all_long),
        TournamentEntry("b", _all_flat),
    ]
    t = WalkForwardTournament(train_size=100, test_size=60)
    rep = t.run(synthetic_prices_daily, entries)
    leader = rep.leader()
    assert leader in {"a", "b"}


def test_empty_entries_raises(synthetic_prices_daily):
    t = WalkForwardTournament(train_size=100, test_size=50)
    with pytest.raises(ValueError):
        t.run(synthetic_prices_daily, [])


def test_too_short_series_raises():
    short = pd.Series([1.0, 2.0, 3.0],
                      index=pd.date_range("2020-01-01", periods=3, freq="B"))
    t = WalkForwardTournament(train_size=100, test_size=50)
    with pytest.raises(ValueError):
        t.run(short, [TournamentEntry("a", _all_long)])


def test_invalid_metric():
    with pytest.raises(ValueError):
        WalkForwardTournament(metric="alpha")


def test_invalid_sizes():
    with pytest.raises(ValueError):
        WalkForwardTournament(train_size=0, test_size=10)
    with pytest.raises(ValueError):
        WalkForwardTournament(train_size=10, test_size=0)


def test_standings_aggregation(synthetic_prices_daily):
    entries = [
        TournamentEntry("long", _all_long),
        TournamentEntry("flat", _all_flat),
    ]
    t = WalkForwardTournament(train_size=100, test_size=50)
    rep = t.run(synthetic_prices_daily, entries)
    # Total wins+losses across both names must equal n_windows*2 (with ties counted as wins for all winners)
    total = rep.standings["long"]["wins"] + rep.standings["long"]["losses"]
    assert total == rep.n_windows
    total = rep.standings["flat"]["wins"] + rep.standings["flat"]["losses"]
    assert total == rep.n_windows


def test_requires_pd_series():
    t = WalkForwardTournament(train_size=10, test_size=5)
    with pytest.raises(TypeError):
        t.run(np.zeros(20), [TournamentEntry("a", _all_long)])
