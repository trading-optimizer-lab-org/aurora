import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import load_catalog_campaign_registry
from aurora.infra.sp500_megarun import catalog_selected_results as selected

ROOT = Path(__file__).resolve().parents[1]


def test_current_sp500_requires_the_exact_thirteen_protected_keys():
    entry = load_catalog_campaign_registry(ROOT / 'config/catalog_campaign_registry_v1.json').campaigns[0]
    manifest = parse_catalog_campaign_definition_bytes((ROOT / entry.definition_manifest_path).read_bytes())
    raw = (ROOT / entry.selected_config_path).read_bytes()
    keys = selected.selected_result_keys_from_definition(entry=entry, definition=manifest, content=raw)
    assert keys == tuple(sorted(row['source_strategy_key'] for row in json.loads(raw)))
    assert len(keys) == 13
    with pytest.raises(ValueError, match='SELECTED_CONTENT'):
        selected.selected_result_keys_from_definition(entry=entry, definition=manifest, content=b'[]')


@pytest.mark.parametrize('raw,valid', [(b'[]', True), (b'[{"source_strategy_key":"a"}]', True),
    (b'[{"source_strategy_key":"a"},{"source_strategy_key":"a"}]', False),
    (b'[{"source_strategy_key":false}]', False), (b'{}', False),
    (b'[{"source_strategy_key":"a","source_strategy_key":"b"}]', False)])
def test_bound_selection_has_unique_strict_keys(raw, valid):
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
        CatalogCampaignDefinitionEntryV1, CatalogCampaignDefinitionManifestV1, registry_entry_sha256,
    )
    entry = load_catalog_campaign_registry(ROOT / 'config/catalog_campaign_registry_v1.json').campaigns[0]
    definition = CatalogCampaignDefinitionManifestV1(schema_version='1',
        closure_algorithm='aurora-catalog-transitive-closure-v1', campaign_key=entry.campaign_key,
        registry_entry_sha256=registry_entry_sha256(entry), entries=(
            CatalogCampaignDefinitionEntryV1.from_bytes(path=entry.selected_config_path, role='configuration', content=raw),))
    if valid:
        assert len(selected.selected_result_keys_from_definition(entry=entry, definition=definition, content=raw)) == len(json.loads(raw))
    else:
        with pytest.raises(ValueError):
            selected.selected_result_keys_from_definition(entry=entry, definition=definition, content=raw)
