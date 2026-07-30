"""Operational bootstrap controls for the GTBI V7 readiness plan.

Exports are loaded on first use so byte-only tools do not import optional
validation or scientific dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CanonicalizationError",
    "CANONICAL_ROLES",
    "QualityValidationResult",
    "StructuralValidationResult",
    "GitHubApiClient",
    "InventoryError",
    "RoleRegistryError",
    "build_blocked_role_registry",
    "build_owner_controlled_role_registry",
    "canonical_bytes",
    "canonical_text",
    "domain_digest",
    "git_blob_id",
    "raw_sha256",
    "generate_local_inventory",
    "generate_remote_inventory",
    "validate_inventory",
    "validate_master_plan_structure",
    "validate_quality_evidence",
    "validate_role_registry",
]

_EXPORT_MODULES = {
    "CanonicalizationError": "canonical",
    "canonical_bytes": "canonical",
    "canonical_text": "canonical",
    "domain_digest": "canonical",
    "git_blob_id": "canonical",
    "raw_sha256": "canonical",
    "QualityValidationResult": "quality",
    "validate_quality_evidence": "quality",
    "CANONICAL_ROLES": "roles",
    "RoleRegistryError": "roles",
    "build_blocked_role_registry": "roles",
    "build_owner_controlled_role_registry": "roles",
    "validate_role_registry": "roles",
    "StructuralValidationResult": "structure",
    "validate_master_plan_structure": "structure",
    "GitHubApiClient": "inventory",
    "InventoryError": "inventory",
    "generate_local_inventory": "inventory",
    "generate_remote_inventory": "inventory",
    "validate_inventory": "inventory",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
