from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    CatalogCampaignRegistryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)


ROOT = Path(__file__).resolve().parents[1]
PATH_FIELDS = (
    "definition_manifest_path",
    "optimization_policy_path",
    "campaign_contract_path",
    "catalog_dir",
    "selected_config_path",
    "admission_evidence_path",
    "data_contract_path",
    "feature_contract_path",
)


def _campaign(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "campaign_key": "sp500-optimized-catalog-v1",
        "engine_id": "optimized_catalog_v1",
        "definition_manifest_path": (
            "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ),
        "optimization_policy_path": "config/sp500_catalog_optimization_policy_v1.json",
        "campaign_contract_path": "config/sp500_megarun_dehb_campaign_v1.json",
        "catalog_dir": "config/sp500_megarun_strategy_catalog_v1",
        "selected_config_path": "config/sp500_megarun_selected_dehb_13.json",
        "admission_evidence_path": (
            "config/sp500_catalog_admission_evidence_current_v1.json"
        ),
        "data_contract_path": "config/sp500_megarun_free_data_240.json",
        "feature_contract_path": "config/sp500_megarun_feature_contract_240.json",
        "runtime_input_run_id": 31418682679,
        "reference_run_id": 31948898747,
        "scientific_contract_sha256": "f" * 64,
        "max_free_workers": 360,
        "allowed_protected_branch": "main",
        "source_artifact_contracts": ["runtime_input_pack_v1"],
        "component_store_family": "sp500_component_store_v1",
        "reducer_family": "catalog_hierarchical_reducer_v1",
        "active": True,
    }
    value.update(updates)
    return value


def _write_registry(path: Path, campaigns: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"schema_version": "1", "campaigns": campaigns}),
        encoding="utf-8",
    )


def _materialize_repository_paths(root: Path, campaign: dict[str, object]) -> None:
    for field in PATH_FIELDS:
        if field == "definition_manifest_path":
            continue
        path = root / str(campaign[field])
        if field == "catalog_dir":
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")


def test_registered_campaign_resolves_only_existing_repo_paths() -> None:
    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(
        registry, "sp500-optimized-catalog-v1", ROOT
    )
    assert entry.engine_id == "optimized_catalog_v1"
    assert entry.scientific_contract_sha256 == (
        "f0e8c6db17a915f7c5f1dfec7d49ce5a69375c7252c23b49d82283120266419f"
    )
    assert entry.definition_manifest_path not in entry.repository_paths
    for value in entry.repository_paths:
        assert (ROOT / value).exists()


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "../outside",
        "config/../outside",
        "config/./file.json",
        "config//file.json",
        "/absolute",
        "C:/outside",
        r"C:\outside",
        "config/\x00file.json",
        ".github/workflows",
        ".github/workflows/evil.yml",
    ],
)
def test_registry_rejects_unsafe_path_shapes(tmp_path: Path, value: str) -> None:
    path = tmp_path / "registry.json"
    _write_registry(path, [_campaign(optimization_policy_path=value)])
    with pytest.raises(ValueError, match="CATALOG_REGISTRY_INVALID"):
        load_catalog_campaign_registry(path)


@pytest.mark.parametrize("field", PATH_FIELDS)
def test_every_repository_path_field_uses_strict_validation(
    tmp_path: Path, field: str
) -> None:
    path = tmp_path / "registry.json"
    _write_registry(path, [_campaign(**{field: "../outside"})])
    with pytest.raises(ValueError, match="CATALOG_REGISTRY_INVALID"):
        load_catalog_campaign_registry(path)


def test_resolution_requires_exactly_one_active_match(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    campaign = _campaign()
    _materialize_repository_paths(root, campaign)

    duplicate = CatalogCampaignRegistryV1.model_validate(
        {"schema_version": "1", "campaigns": [campaign, campaign]}
    )
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_UNRESOLVED"):
        resolve_catalog_campaign(duplicate, str(campaign["campaign_key"]), root)

    inactive = CatalogCampaignRegistryV1.model_validate(
        {
            "schema_version": "1",
            "campaigns": [{**campaign, "active": False}],
        }
    )
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_UNRESOLVED"):
        resolve_catalog_campaign(inactive, str(campaign["campaign_key"]), root)

    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_UNRESOLVED"):
        resolve_catalog_campaign(inactive, "unknown-campaign-v1", root)


def test_resolution_rejects_missing_or_escaping_repository_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    campaign = _campaign()
    _materialize_repository_paths(root, campaign)
    missing = root / str(campaign["data_contract_path"])
    missing.unlink()
    registry = CatalogCampaignRegistryV1.model_validate(
        {"schema_version": "1", "campaigns": [campaign]}
    )
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_PATH_INVALID"):
        resolve_catalog_campaign(registry, str(campaign["campaign_key"]), root)


@pytest.mark.parametrize("workers", [1, 120, 360])
def test_campaign_accepts_representative_free_worker_ceilings(workers: int) -> None:
    entry = CatalogCampaignEntryV1.model_validate(
        _campaign(max_free_workers=workers)
    )
    assert entry.max_free_workers == workers


@pytest.mark.parametrize("workers", [0, 361])
def test_campaign_rejects_worker_ceiling_outside_free_limit(workers: int) -> None:
    with pytest.raises(ValueError):
        CatalogCampaignEntryV1.model_validate(_campaign(max_free_workers=workers))


@pytest.mark.parametrize(
    "registered,qualified,live,expected",
    [
        (360, 300, 173, 173),
        (120, 300, 173, 120),
        (360, 80, 173, 80),
    ],
)
def test_admission_uses_lowest_safe_worker_ceiling(
    registered: int, qualified: int, live: int, expected: int
) -> None:
    entry = CatalogCampaignEntryV1.model_validate(
        _campaign(max_free_workers=registered)
    )
    assert (
        entry.select_safe_worker_ceiling(
            compatible_qualified_ceiling=qualified,
            current_safe_free_capacity=live,
        )
        == expected
    )


def test_registry_import_boundary_stays_minimal() -> None:
    path = ROOT / "infra/sp500_megarun/catalog_campaign_registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "aurora.infra.github_performance.contracts" not in imported_modules
    assert "infra.github_performance.contracts" not in imported_modules


def test_active_campaign_names_all_fixed_execution_families() -> None:
    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    active = tuple(item for item in registry.campaigns if item.active)
    assert active
    for campaign in active:
        assert len(campaign.scientific_contract_sha256) == 64
        assert campaign.allowed_protected_branch == "main"
        assert campaign.source_artifact_contracts
        assert campaign.component_store_family
        assert campaign.reducer_family
