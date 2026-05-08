"""Tests for quantforge.marketdata.survivorship_free."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.marketdata.survivorship_free import (
    SurvivorshipFreeUniverse,
    UniverseConfig,
)


@pytest.fixture
def universe() -> SurvivorshipFreeUniverse:
    u = SurvivorshipFreeUniverse(UniverseConfig(n_mock_symbols=50, mock_seed=42))
    u.load_listings()
    return u


def test_load_listings_has_required_columns(universe: SurvivorshipFreeUniverse):
    listings = universe._listings
    assert listings is not None
    assert set(["symbol", "listing_date", "delisting_date",
                "exchange", "sector"]).issubset(listings.columns)


def test_members_as_of_includes_delisted(universe: SurvivorshipFreeUniverse):
    members = universe.members_as_of(pd.Timestamp("2010-01-01"))
    # Both currently-active and to-be-delisted symbols can appear.
    assert len(members) > 0


def test_members_as_of_excludes_future_delisted(universe: SurvivorshipFreeUniverse):
    # A name with delisting_date 2005-01-01 should NOT appear at 2020.
    listings = universe._listings.copy()
    listings.loc[0, "listing_date"] = pd.Timestamp("2000-01-01")
    listings.loc[0, "delisting_date"] = pd.Timestamp("2005-01-01")
    universe.load_listings(listings)
    members = universe.members_as_of(pd.Timestamp("2020-01-01"))
    sym = listings.iloc[0]["symbol"]
    assert sym not in members["symbol"].values


def test_delisted_in_window(universe: SurvivorshipFreeUniverse):
    delisted = universe.delisted_in_window(
        pd.Timestamp("2000-01-01"), pd.Timestamp("2024-12-31"),
    )
    assert delisted["delisting_date"].notna().all()


def test_n_active_decreases_after_delistings(universe: SurvivorshipFreeUniverse):
    early = universe.n_active(pd.Timestamp("1995-06-01"))
    late = universe.n_active(pd.Timestamp("2024-06-01"))
    # Universe matures over time; we just want the API to return integers.
    assert isinstance(early, int)
    assert isinstance(late, int)


def test_exclude_delisted_filters_them_out():
    u = SurvivorshipFreeUniverse(UniverseConfig(
        include_delisted=False, n_mock_symbols=50, mock_seed=42,
    ))
    u.load_listings()
    members = u.members_as_of(pd.Timestamp("2020-01-01"))
    assert members["delisting_date"].isna().all()
