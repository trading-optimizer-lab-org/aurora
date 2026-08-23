"""Exact GitHub installation verification and public binding derivation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from cryptography.hazmat.primitives import serialization

from .catalog_bootstrap_contract import CatalogBootstrapAppManifestV1


@dataclass(frozen=True, slots=True)
class VerifiedCatalogAppInstallation:
    app_id: int
    app_slug: str
    repositories: tuple[str, ...]
    repository_permissions: dict[str, str]
    organization_permissions: dict[str, str]
    enterprise_permissions: dict[str, str]


@dataclass(frozen=True, slots=True)
class CatalogAppPublicBinding:
    kind: str
    app_id: int
    app_slug: str
    public_key_pem: bytes
    public_key_sha256: str


def _mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(permission, str)
        for key, permission in value.items()
    ):
        raise ValueError("APP_PERMISSION_DRIFT")
    return dict(value)


def _normalized_permissions(
    snapshot: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    if "permissions" not in snapshot:
        return (
            _mapping(snapshot.get("repository_permissions")),
            _mapping(snapshot.get("organization_permissions")),
            _mapping(snapshot.get("enterprise_permissions")),
        )
    provider = _mapping(snapshot.get("permissions"))
    organization: dict[str, str] = {}
    repository: dict[str, str] = {}
    enterprise: dict[str, str] = {}
    for name, permission in provider.items():
        if name == "actions_variables":
            repository["variables"] = permission
        elif name == "organization_administration":
            organization["administration"] = permission
        elif name.startswith("enterprise_"):
            enterprise[name] = permission
        else:
            repository[name] = permission
    return repository, organization, enterprise


def verify_exact_installation(
    snapshot: Mapping[str, object],
    expected: CatalogBootstrapAppManifestV1,
) -> VerifiedCatalogAppInstallation:
    repositories = snapshot.get("repositories")
    if repositories != ["trading-optimizer-lab-org/aurora"]:
        raise ValueError("INSTALL_SCOPE_INVALID")
    repository, organization, enterprise = _normalized_permissions(snapshot)
    if (
        repository != expected.expected_repository_permissions
        or organization != expected.expected_organization_permissions
        or enterprise != expected.expected_enterprise_permissions
    ):
        raise ValueError("APP_PERMISSION_DRIFT")
    app_id = snapshot.get("app_id")
    app_slug = snapshot.get("app_slug")
    if not isinstance(app_id, int) or app_id < 1 or not isinstance(app_slug, str):
        raise ValueError("APP_IDENTITY_INVALID")
    return VerifiedCatalogAppInstallation(
        app_id=app_id,
        app_slug=app_slug,
        repositories=tuple(repositories),
        repository_permissions=repository,
        organization_permissions=organization,
        enterprise_permissions=enterprise,
    )


def derive_public_binding(
    *,
    kind: str,
    app_id: int,
    slug: str,
    private_key_pem: bytearray,
) -> CatalogAppPublicBinding:
    try:
        key = serialization.load_pem_private_key(bytes(private_key_pem), password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("APP_PRIVATE_KEY_INVALID") from exc
    public_key = key.public_key()
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return CatalogAppPublicBinding(
        kind=kind,
        app_id=app_id,
        app_slug=slug,
        public_key_pem=public_pem,
        public_key_sha256=hashlib.sha256(public_der).hexdigest(),
    )
