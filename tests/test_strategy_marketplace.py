"""Tests for aurora.research.strategy_marketplace."""
from __future__ import annotations
import pytest

from aurora.research.strategy_marketplace import (
    MarketplaceStrategy,
    StrategyMarketplace,
)


def test_register_and_get():
    m = StrategyMarketplace()
    s = m.register(
        author="alice", name="my_momentum", family="momentum",
        description="L=60 momentum",
        params={"lookback": 60}, metadata={"sharpe_oos": 1.2},
    )
    assert isinstance(s, MarketplaceStrategy)
    fetched = m.get("alice", "my_momentum")
    assert fetched is not None
    assert fetched.params == {"lookback": 60}
    assert fetched.metadata["sharpe_oos"] == 1.2


def test_register_duplicate_raises():
    m = StrategyMarketplace()
    m.register("u", "s")
    with pytest.raises(ValueError):
        m.register("u", "s")


def test_register_invalid_inputs():
    m = StrategyMarketplace()
    with pytest.raises(ValueError):
        m.register("", "name")
    with pytest.raises(ValueError):
        m.register("u", "")


def test_register_non_serializable_params():
    m = StrategyMarketplace()

    class _NotSerializable:
        pass

    with pytest.raises(ValueError):
        m.register("u", "s", params={"obj": _NotSerializable()})


def test_discover_filters():
    m = StrategyMarketplace()
    m.register("u1", "mom60", family="momentum")
    m.register("u1", "mom120", family="momentum")
    m.register("u2", "boll", family="mean_rev")
    by_fam = m.discover(family="momentum")
    assert {s.name for s in by_fam} == {"mom60", "mom120"}
    by_author = m.discover(author="u2")
    assert [s.name for s in by_author] == ["boll"]
    by_substr = m.discover(name_contains="mom")
    assert {s.name for s in by_substr} == {"mom60", "mom120"}


def test_discover_compound_filter():
    m = StrategyMarketplace()
    m.register("u1", "mom60", family="momentum")
    m.register("u2", "mom120", family="momentum")
    out = m.discover(family="momentum", author="u1")
    assert len(out) == 1
    assert out[0].author == "u1"


def test_delete_returns_bool():
    m = StrategyMarketplace()
    m.register("u", "s")
    assert m.delete("u", "s") is True
    assert m.delete("u", "s") is False


def test_count_authors_families():
    m = StrategyMarketplace()
    m.register("u1", "a", family="momentum")
    m.register("u2", "b", family="mean_rev")
    assert m.count() == 2
    assert sorted(m.authors()) == ["u1", "u2"]
    assert sorted(m.families()) == ["mean_rev", "momentum"]


def test_get_unknown_returns_none():
    m = StrategyMarketplace()
    assert m.get("ghost", "ghost") is None


def test_persistence(tmp_path):
    db = tmp_path / "mkt.sqlite"
    with StrategyMarketplace(db_path=str(db)) as m:
        m.register("u", "s")
    with StrategyMarketplace(db_path=str(db)) as m:
        assert m.get("u", "s") is not None
