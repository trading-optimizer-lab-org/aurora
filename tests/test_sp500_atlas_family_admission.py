"""Focused tests for closed Atlas family admission."""

from __future__ import annotations

from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_family_admission import (
    build_existing_family_manifest,
    classify_family,
    formal_recipe_equivalence,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract


@pytest.fixture(scope="module")
def feature_contract():
    root = Path(__file__).parents[1]
    data = load_and_validate_contract(root / "config/sp500_megarun_free_data_240.json")
    return load_and_validate_feature_contract(
        root / "config/sp500_megarun_feature_contract_240.json", data
    )


def test_existing_manifest_has_exactly_the_240_train_only_families(
    feature_contract,
) -> None:
    rows = build_existing_family_manifest(feature_contract)
    assert len(rows) == 240
    assert all(row.status == "accepted" for row in rows)
    assert all(row.available_through == "2010-12-31" for row in rows)


def test_accepted_new_family_requires_causal_evidence() -> None:
    with pytest.raises(ValueError, match="EVIDENCE_INCOMPLETE"):
        classify_family(
            {"family_id": "NEW", "status": "accepted"},
            {},
        )


def test_new_family_after_train_end_is_rejected() -> None:
    with pytest.raises(ValueError, match="AFTER_TRAIN_END"):
        classify_family(
            {
                "family_id": "NEW",
                "status": "accepted",
                "source_ids": ["public"],
                "source_sha256": "a" * 64,
                "available_through": "2011-01-01",
                "available_at_mode": "next_session",
            },
            {},
        )


def test_empirical_position_similarity_is_not_recipe_equivalence() -> None:
    left = {
        "strategy_kind": "single",
        "components": ["a"],
        "composition": {"kind": "identity"},
        "feature_contract_sha256": "b" * 64,
        "search_end": "2010-12-31",
    }
    right = {**left, "components": ["c"]}
    assert formal_recipe_equivalence(left, right) is False


def test_exact_recipe_is_formally_equivalent_even_with_provenance_changes() -> None:
    left = {
        "strategy_kind": "cross",
        "components": ["a", "b"],
        "composition": {"kind": "and"},
        "feature_contract_sha256": "b" * 64,
        "search_end": "2010-12-31",
        "cross_rule_ids": ["CR01"],
    }
    right = {**left, "cross_rule_ids": ["CR02"], "coverage_tags": ["other"]}
    assert formal_recipe_equivalence(left, right) is True
