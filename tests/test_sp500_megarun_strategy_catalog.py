from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
FEATURE_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json"


def _single_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "strategy_id": "SCV1-" + "0" * 64,
        "scientific_recipe_sha256": "0" * 64,
        "strategy_kind": "single",
        "components": [
            {
                "lane_id": "F001",
                "configuration": {"kind": "sma", "window": 20},
                "configuration_sha256": "0" * 64,
            }
        ],
        "composition": {"kind": "identity"},
        "cross_rule_ids": [],
        "economic_rationales": [],
        "feature_count": 1,
        "initial_fidelity": 1,
        "coverage_tags": ["lane:F001"],
        "feature_contract_sha256": "1" * 64,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "performance_status": "not_evaluated",
    }
    payload.update(overrides)
    return payload


def test_catalog_identity_is_stable_across_mapping_order() -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import configuration_sha256

    left = {"window": 20, "kind": "sma"}
    right = {"kind": "sma", "window": 20}

    assert configuration_sha256("F001", left) == configuration_sha256("F001", right)


@pytest.mark.parametrize("boundary", ["validation_opened", "locked_opened"])
def test_catalog_entry_rejects_open_boundaries(boundary: str) -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import (
        CatalogBuildError,
        StrategyCatalogEntryV1,
    )

    with pytest.raises(CatalogBuildError, match="CATALOG_BOUNDARY_OPEN"):
        StrategyCatalogEntryV1.from_payload(_single_payload(**{boundary: True}))
