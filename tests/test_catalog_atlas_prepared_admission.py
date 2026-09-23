"""Focused admission guards for cached Atlas PREPARED calibration."""

from datetime import datetime, timezone

import pytest

from scripts.verify_catalog_prepared_bundle import _atlas_verify_fresh_window


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


def test_cached_atlas_target_must_still_be_future() -> None:
    with pytest.raises(ValueError, match="CATALOG_ATLAS_PREPARED_TARGET_EXPIRED"):
        _atlas_verify_fresh_window(
            calibration={"recipes_per_minute": 10_000.0, "safety_fraction": 0.8},
            target_end_iso="2098-12-31T23:59:59Z",
            requested_recipe_count=209906,
            now=NOW,
        )


def test_cached_atlas_calibration_must_cover_full_request_from_now() -> None:
    with pytest.raises(ValueError, match="CATALOG_ATLAS_PREPARED_WINDOW_INSUFFICIENT"):
        _atlas_verify_fresh_window(
            calibration={"recipes_per_minute": 1.0, "safety_fraction": 0.8},
            target_end_iso="2099-01-01T01:00:00Z",
            requested_recipe_count=209906,
            now=NOW,
        )
