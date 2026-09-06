"""Auxiliary-result identities derived from the protected campaign definition."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionManifestV1,
    parse_catalog_campaign_definition_bytes,
    registry_entry_sha256,
)
from .catalog_campaign_registry import (
    CatalogCampaignEntryV1, _reject_duplicate_keys, _reject_nonfinite,
    load_catalog_campaign_registry, resolve_catalog_for_reduction,
)


def selected_result_keys_from_definition(
    *, entry: CatalogCampaignEntryV1,
    definition: CatalogCampaignDefinitionManifestV1, content: bytes,
) -> tuple[str, ...]:
    """Check one file binding; callers must establish the definition's authority."""
    if (definition.campaign_key != entry.campaign_key
            or definition.registry_entry_sha256 != registry_entry_sha256(entry)):
        raise ValueError('CATALOG_REDUCER_SELECTED_DEFINITION_MISMATCH')
    bindings = [row for row in definition.entries if row.path == entry.selected_config_path]
    if (len(bindings) != 1 or bindings[0].size_bytes != len(content)
            or bindings[0].sha256 != hashlib.sha256(content).hexdigest()):
        raise ValueError('CATALOG_REDUCER_SELECTED_CONTENT_MISMATCH')
    payload = json.loads(content, object_pairs_hook=_reject_duplicate_keys,
                         parse_constant=_reject_nonfinite)
    if not isinstance(payload, list):
        raise ValueError('CATALOG_REDUCER_SELECTED_CONFIG_INVALID')
    keys: list[str] = []
    for row in payload:
        key = row.get('source_strategy_key') if isinstance(row, dict) else None
        if (not isinstance(key, str) or not key or key != key.strip()
                or any(ord(character) < 32 for character in key) or key in keys):
            raise ValueError('CATALOG_REDUCER_SELECTED_KEYS_INVALID')
        keys.append(key)
    return tuple(sorted(keys))


def resolve_registered_selected_result_keys(
    *, repo_root: Path, scientific_contract_sha256: str,
    catalog_manifest_sha256: str, catalog_path: Path,
) -> tuple[str, ...]:
    """Use the same registered catalog and full definition as production admission."""
    from .catalog_campaign_definition_builder import verify_catalog_campaign_definition

    root = repo_root.resolve(strict=True)
    approved_catalog = resolve_catalog_for_reduction(
        repo_root=root, scientific_contract_sha256=scientific_contract_sha256,
        catalog_manifest_sha256=catalog_manifest_sha256,
    )
    if catalog_path.resolve(strict=True) != approved_catalog:
        raise ValueError('CATALOG_REDUCER_SELECTED_CATALOG_MISMATCH')
    registry = load_catalog_campaign_registry(root / 'config/catalog_campaign_registry_v1.json')
    matches = [row for row in registry.campaigns
               if row.active and row.scientific_contract_sha256 == scientific_contract_sha256]
    if len(matches) != 1:
        raise ValueError('CATALOG_REDUCER_SELECTED_CAMPAIGN_UNRESOLVED')
    entry = matches[0]
    definition_path = (root / entry.definition_manifest_path).resolve(strict=True)
    selected_path = (root / entry.selected_config_path).resolve(strict=True)
    if not definition_path.is_relative_to(root) or not selected_path.is_relative_to(root):
        raise ValueError('CATALOG_REDUCER_SELECTED_PATH_INVALID')
    definition = verify_catalog_campaign_definition(
        repo_root=root, registry_entry=entry,
        manifest=parse_catalog_campaign_definition_bytes(definition_path.read_bytes()),
    )
    return selected_result_keys_from_definition(
        entry=entry, definition=definition, content=selected_path.read_bytes(),
    )
