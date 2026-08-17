"""Unit tests for the 20-minute calibration contract and sizing."""

from __future__ import annotations

import pytest

from aurora.infra.sp500_megarun.catalog_atlas_calibration import (
    AtlasCalibrationReceiptV1,
    target_minutes,
    target_recipe_count,
)


def test_target_minutes_requires_timezone() -> None:
    with pytest.raises(ValueError, match="TIMEZONE"):
        target_minutes(now_iso="2026-08-17T10:00:00", target_end_iso="2026-08-20T07:30:00+02:00")


def test_target_sizing_applies_margin() -> None:
    assert target_recipe_count(
        available_minutes=100.0,
        recipes_per_minute=10.0,
        safety_fraction=0.8,
    ) == 800


def test_receipt_rejects_more_than_twenty_minutes() -> None:
    with pytest.raises(ValueError):
        AtlasCalibrationReceiptV1(
            schema_version="1",
            catalog_sha256="a" * 64,
            started_at_iso="2026-08-17T10:00:00+02:00",
            stopped_at_iso="2026-08-17T10:20:00+02:00",
            wall_seconds=1200.1,
            hard_limit_seconds=1200.0,
            timed_out_cleanly=True,
            physical_recipe_count=1,
            cache_hit_count=0,
            physical_component_count=1,
            physical_component_seconds=1.0,
            recipe_seconds=1.0,
            result_store_seconds=1.0,
            recipes_per_minute=1.0,
            recommended_mode="component_warm",
            available_minutes_to_target=1.0,
            safety_fraction=0.8,
            target_recipe_count_with_margin=1,
            validation_opened=False,
            locked_opened=False,
        )
