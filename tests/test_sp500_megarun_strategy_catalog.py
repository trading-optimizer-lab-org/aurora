from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
FEATURE_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json"


@pytest.fixture(scope="module")
def feature_contract():
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)
    return load_and_validate_feature_contract(FEATURE_CONTRACT_PATH, data_contract)


@pytest.fixture(scope="module")
def individual_catalog(feature_contract):
    from aurora.infra.sp500_megarun.strategy_catalog import build_individual_entries

    return build_individual_entries(feature_contract)


@pytest.fixture(scope="module")
def cross_catalog(feature_contract, individual_catalog):
    from aurora.infra.sp500_megarun.strategy_catalog import build_cross_entries

    individual_entries, _report = individual_catalog
    return build_cross_entries(feature_contract, individual_entries)


@pytest.fixture(scope="module")
def catalog_artifact_directories(tmp_path_factory):
    from aurora.infra.sp500_megarun.strategy_catalog import (
        build_and_write_strategy_catalog,
    )

    root = tmp_path_factory.mktemp("sp500_strategy_catalog")
    first = root / "first"
    second = root / "second"
    build_and_write_strategy_catalog(
        DATA_CONTRACT_PATH,
        FEATURE_CONTRACT_PATH,
        output_dir=first,
    )
    build_and_write_strategy_catalog(
        DATA_CONTRACT_PATH,
        FEATURE_CONTRACT_PATH,
        output_dir=second,
    )
    return first, second


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


def test_individual_catalog_covers_every_value_and_compatible_pair(
    individual_catalog,
) -> None:
    entries, report = individual_catalog

    assert {entry.components[0].lane_id for entry in entries} == {
        f"F{index:03d}" for index in range(1, 241)
    }
    assert report["lane_count"] == 240
    assert report["raw_cartesian_count"] == 682_652
    assert report["uncovered_requirements"] == []
    assert all(entry.strategy_kind == "single" for entry in entries)
    assert all(entry.validation_opened is False for entry in entries)
    assert all(entry.locked_opened is False for entry in entries)


def test_individual_catalog_excludes_forbidden_f002_pairs(individual_catalog) -> None:
    entries, _report = individual_catalog
    f002 = [entry for entry in entries if entry.components[0].lane_id == "F002"]

    assert f002
    assert all(
        entry.components[0].configuration["fast"]
        < entry.components[0].configuration["slow"]
        for entry in f002
    )


def test_cross_catalog_covers_every_rule_composition_and_arity(
    cross_catalog,
) -> None:
    entries, report = cross_catalog

    assert report["rule_count"] == 14
    assert report["raw_pair_composition_count"] == 26_480
    assert report["uncovered_rule_composition_arities"] == []
    assert report["uncovered_authorized_left_right_pairs"] == []
    assert report["uncovered_parameter_values"] == []
    assert {rule_id for entry in entries for rule_id in entry.cross_rule_ids} == {
        f"CR{index:02d}_{suffix}"
        for index, suffix in (
            (1, "TREND_CONFIRMATION"),
            (2, "REVERSAL_PRESSURE"),
            (3, "ADAPTIVE_TREND_REVERSAL"),
            (4, "RISK_VOLATILITY_GATE"),
            (5, "MACRO_VALUATION_TREND"),
            (6, "INTERNALS_MARKET"),
            (7, "CROSS_ASSET"),
            (8, "PUBLIC_EVENTS"),
            (9, "SIMPLE_ENSEMBLES"),
            (10, "MULTISCALE_PATH"),
            (11, "LIQUIDITY_FLOW"),
            (12, "INTERPRETABLE_MODELS"),
            (13, "VOLATILITY_POSITIONING"),
            (14, "FORECAST_COMBINATION"),
        )
    }
    assert all(2 <= entry.feature_count <= 5 for entry in entries)
    assert len({entry.scientific_recipe_sha256 for entry in entries}) == len(entries)


def test_commutative_crosses_canonicalize_component_permutations() -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import (
        CatalogComponentV1,
        canonicalize_composition,
    )

    first = CatalogComponentV1.create("F001", {"window": 20})
    second = CatalogComponentV1.create("F019", {"window": 63})

    left_components, left_composition = canonicalize_composition(
        "and", (first, second)
    )
    right_components, right_composition = canonicalize_composition(
        "and", (second, first)
    )

    assert left_components == right_components
    assert left_composition == right_composition == {"kind": "and"}


def test_catalog_build_does_not_import_market_data_runtime() -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import build_strategy_catalog

    before = set(sys.modules)
    build_strategy_catalog(DATA_CONTRACT_PATH, FEATURE_CONTRACT_PATH)
    imported = set(sys.modules) - before

    assert not {
        "aurora.infra.sp500_megarun.dehb_worker",
        "aurora.infra.sp500_megarun.materializer",
    } & imported


def test_catalog_artifacts_are_byte_reproducible(
    catalog_artifact_directories,
) -> None:
    first, second = catalog_artifact_directories

    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_catalog_manifest_matches_all_rows(catalog_artifact_directories) -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import (
        verify_strategy_catalog_directory,
    )

    first, _second = catalog_artifact_directories
    receipt = verify_strategy_catalog_directory(first)
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))

    assert receipt["accepted"] is True
    assert receipt["uncovered_requirement_count"] == 0
    assert receipt["strategy_count"] == manifest["strategy_count"]
    assert receipt["validation_opened"] is False
    assert receipt["locked_opened"] is False


def test_catalog_verifier_rejects_an_altered_artifact(
    tmp_path,
    catalog_artifact_directories,
) -> None:
    from aurora.infra.sp500_megarun.strategy_catalog import (
        CatalogBuildError,
        verify_strategy_catalog_directory,
    )

    first, _second = catalog_artifact_directories
    altered = tmp_path / "altered"
    shutil.copytree(first, altered)
    with (altered / "catalog.jsonl").open("ab") as handle:
        handle.write(b" ")

    with pytest.raises(CatalogBuildError, match="CATALOG_ARTIFACT_HASH_MISMATCH"):
        verify_strategy_catalog_directory(altered)
