"""Registered tiny acceptance campaign must use the normal producer contracts."""
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import load_catalog_campaign_registry, resolve_catalog_campaign
from scripts.plan_sp500_optimized_catalog_run import build_repository_contract

ROOT = Path(__file__).resolve().parents[1]


def test_canary_registration_matches_real_producer_identity():
    registry = load_catalog_campaign_registry(ROOT / 'config/catalog_campaign_registry_v1.json')
    entry = resolve_catalog_campaign(registry, 'catalog-fast-canary-v1', ROOT)
    contract = build_repository_contract(repo_root=ROOT,
        policy_path=ROOT / entry.optimization_policy_path,
        campaign_path=ROOT / entry.campaign_contract_path,
        catalog_dir=ROOT / entry.catalog_dir,
        selected_config_path=ROOT / entry.selected_config_path)
    assert contract.execution.workers == entry.max_free_workers == 4
    assert contract.workload.requested_recipes == 8
    assert contract.workload.unique_components == 13
    assert canonical_sha256(contract.science) == entry.scientific_contract_sha256
    assert contract.science.validation_opened is False
    assert contract.science.locked_opened is False
    assert (ROOT / entry.selected_config_path).read_text().strip() == '[]'


def test_each_definition_tracks_registry_without_other_manifest_outputs():
    import hashlib
    from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import discover_catalog_campaign_definition
    registry = load_catalog_campaign_registry(ROOT / 'config/catalog_campaign_registry_v1.json')
    for key in ('sp500-optimized-catalog-v1', 'catalog-fast-canary-v1'):
        entry = resolve_catalog_campaign(registry, key, ROOT)
        definition = discover_catalog_campaign_definition(repo_root=ROOT, registry_entry=entry)
        paths = {row.path: row for row in definition.entries}
        assert not any(row.definition_manifest_path in paths for row in registry.campaigns)
        assert paths['config/catalog_campaign_registry_v1.json'].sha256 == hashlib.sha256((ROOT / 'config/catalog_campaign_registry_v1.json').read_bytes()).hexdigest()
        assert entry.selected_config_path in paths
        assert entry.catalog_dir + '/manifest.json' in paths


def test_normal_reducer_resolves_full_protected_auxiliary_definitions():
    import hashlib
    from aurora.infra.sp500_megarun.catalog_selected_results import resolve_registered_selected_result_keys
    registry = load_catalog_campaign_registry(ROOT / 'config/catalog_campaign_registry_v1.json')
    for key, count in (('sp500-optimized-catalog-v1', 13), ('catalog-fast-canary-v1', 0)):
        entry = resolve_catalog_campaign(registry, key, ROOT)
        keys = resolve_registered_selected_result_keys(repo_root=ROOT,
            scientific_contract_sha256=entry.scientific_contract_sha256,
            catalog_manifest_sha256=hashlib.sha256((ROOT / entry.catalog_dir / 'manifest.json').read_bytes()).hexdigest(),
            catalog_path=ROOT / entry.catalog_dir / 'catalog.jsonl')
        assert len(keys) == count
