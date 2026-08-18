from __future__ import annotations

from aurora.infra.sp500_megarun.atlas_campaign_selection import (
    build_campaign_selection,
    selected_raw_ordinal,
)


def _space_payload() -> dict[str, object]:
    return {
        "canonical_recipe_count": 18,
        "ranges": [
            {"range_id": "range-a", "start_ordinal": 0, "stop_ordinal": 5},
            {"range_id": "range-b", "start_ordinal": 5, "stop_ordinal": 11},
            {"range_id": "range-c", "start_ordinal": 11, "stop_ordinal": 18},
        ],
    }


def test_selection_is_deterministic_and_covers_every_range_when_budget_allows() -> None:
    first = build_campaign_selection(_space_payload(), requested_recipe_count=9, seed=20260818)
    second = build_campaign_selection(_space_payload(), requested_recipe_count=9, seed=20260818)

    assert first == second
    assert first["requested_recipe_count"] == 9
    assert sum(int(item["quota"]) for item in first["ranges"]) == 9
    assert {item["range_id"] for item in first["ranges"]} == {
        "range-a",
        "range-b",
        "range-c",
    }
    assert len(first["selection_sha256"]) == 64


def test_selected_ordinals_are_unique_inside_their_declared_ranges() -> None:
    selection = build_campaign_selection(_space_payload(), requested_recipe_count=9, seed=7)
    selected = [selected_raw_ordinal(selection, campaign_ordinal) for campaign_ordinal in range(9)]

    assert len(set(selected)) == 9
    assert all(0 <= ordinal < 18 for ordinal in selected)
    for item in selection["ranges"]:
        start = int(item["campaign_start"])
        stop = int(item["campaign_stop"])
        values = [
            selected_raw_ordinal(selection, campaign_ordinal)
            for campaign_ordinal in range(start, stop)
        ]
        assert all(
            int(item["raw_start"]) <= ordinal < int(item["raw_stop"])
            for ordinal in values
        )


def test_small_budget_is_not_a_raw_prefix() -> None:
    selection = build_campaign_selection(_space_payload(), requested_recipe_count=3, seed=20260818)
    selected = [selected_raw_ordinal(selection, index) for index in range(3)]

    assert len(set(selected)) == 3
    assert selected != [0, 1, 2]
