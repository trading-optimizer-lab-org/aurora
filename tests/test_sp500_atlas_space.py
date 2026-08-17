"""Tests for the metadata-only complete Atlas-1 recipe space."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_atlas_space import (
    build_atlas_space,
    recipe_for_ordinal,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract


ROOT = Path(__file__).parents[1]


@lru_cache(maxsize=1)
def _space():
    data = load_and_validate_contract(ROOT / "config/sp500_megarun_free_data_240.json")
    contract = load_and_validate_feature_contract(
        ROOT / "config/sp500_megarun_feature_contract_240.json", data
    )
    return build_atlas_space(contract)


def test_atlas_space_is_train_only_and_non_empty() -> None:
    space, components = _space()
    assert space.train_end == "2010-12-31"
    assert space.validation_opened is False
    assert space.locked_opened is False
    assert len(components) == 240
    assert space.canonical_recipe_count > 0
    assert space.formal_duplicate_count >= 0


def test_ranges_are_contiguous_and_cover_the_declared_space() -> None:
    space, _ = _space()
    cursor = 0
    for item in space.ranges:
        assert item.start_ordinal == cursor
        assert item.stop_ordinal > item.start_ordinal
        assert item.formal_source_variant_count >= 1
        cursor = item.stop_ordinal
    assert cursor == space.canonical_recipe_count


def test_first_and_last_recipe_are_deterministic() -> None:
    space, components = _space()
    first = recipe_for_ordinal(space, components, 0)
    last = recipe_for_ordinal(space, components, space.canonical_recipe_count - 1)
    assert first["ordinal"] == 0
    assert last["ordinal"] == space.canonical_recipe_count - 1
    assert first["scientific_recipe_sha256"] != last["scientific_recipe_sha256"]
    assert first["validation_opened"] is False
    assert last["locked_opened"] is False


def test_formal_aliases_are_accounted_for_without_historical_positions() -> None:
    space, _ = _space()
    assert space.raw_requested_recipe_count >= space.canonical_recipe_count
    assert any(item.formal_source_variant_count > 1 for item in space.ranges)
