"""Closed contracts for the two GitHub Apps used by catalog bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Mapping

from pydantic import HttpUrl, model_validator

from .catalog_request_contract import FrozenModel, Sha256


Permission = Literal["read", "write"]

REQUESTER_PERMISSIONS = {"issues": "write", "metadata": "read"}
AUDITOR_MANIFEST_PERMISSIONS = {
    "actions": "read",
    "actions_variables": "read",
    "administration": "read",
    "contents": "read",
    "environments": "read",
    "issues": "read",
    "metadata": "read",
    "organization_administration": "read",
    "packages": "read",
}
AUDITOR_REPOSITORY_PERMISSIONS = {
    "actions": "read",
    "administration": "read",
    "contents": "read",
    "environments": "read",
    "issues": "read",
    "metadata": "read",
    "packages": "read",
    "variables": "read",
}
AUDITOR_ORGANIZATION_PERMISSIONS = {"administration": "read"}


class CatalogBootstrapAppManifestV1(FrozenModel):
    kind: Literal["requester", "auditor"]
    name: str
    description: str
    homepage_url: HttpUrl
    public: Literal[False]
    webhook_active: Literal[False]
    default_events: tuple[()]
    manifest_permissions: dict[str, Permission]
    expected_repository_permissions: dict[str, Permission]
    expected_organization_permissions: dict[str, Permission]
    expected_enterprise_permissions: dict[str, Permission]

    @model_validator(mode="after")
    def _require_exact_permissions(self) -> "CatalogBootstrapAppManifestV1":
        if self.kind == "requester":
            if self.manifest_permissions != REQUESTER_PERMISSIONS:
                raise ValueError("REQUESTER_MANIFEST_PERMISSIONS_INVALID")
            if self.expected_repository_permissions != REQUESTER_PERMISSIONS:
                raise ValueError("REQUESTER_REPOSITORY_PERMISSIONS_INVALID")
            if self.expected_organization_permissions or self.expected_enterprise_permissions:
                raise ValueError("REQUESTER_ACCOUNT_PERMISSIONS_INVALID")
        else:
            if self.manifest_permissions != AUDITOR_MANIFEST_PERMISSIONS:
                raise ValueError("AUDITOR_MANIFEST_PERMISSIONS_INVALID")
            if self.expected_repository_permissions != AUDITOR_REPOSITORY_PERMISSIONS:
                raise ValueError("AUDITOR_REPOSITORY_PERMISSIONS_INVALID")
            if self.expected_organization_permissions != AUDITOR_ORGANIZATION_PERMISSIONS:
                raise ValueError("AUDITOR_ORGANIZATION_PERMISSIONS_INVALID")
            if self.expected_enterprise_permissions:
                raise ValueError("AUDITOR_ENTERPRISE_PERMISSIONS_INVALID")
        return self


class CatalogBootstrapManifestSetV1(FrozenModel):
    schema_version: Literal["1"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    organization: Literal["trading-optimizer-lab-org"]
    requester: CatalogBootstrapAppManifestV1
    auditor: CatalogBootstrapAppManifestV1

    @model_validator(mode="after")
    def _require_app_roles(self) -> "CatalogBootstrapManifestSetV1":
        if self.requester.kind != "requester" or self.auditor.kind != "auditor":
            raise ValueError("CATALOG_BOOTSTRAP_APP_ROLES_INVALID")
        if self.requester.name == self.auditor.name:
            raise ValueError("CATALOG_BOOTSTRAP_APP_NAMES_COLLIDE")
        return self


class CatalogBootstrapPublicAppBindingV1(FrozenModel):
    schema_version: Literal["1"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    requester_app_id: int
    requester_app_slug: str
    requester_public_key_sha256: Sha256
    auditor_app_id: int
    auditor_app_slug: str
    auditor_public_key_sha256: Sha256


def load_catalog_bootstrap_manifests(
    source: Path | Mapping[str, object],
) -> CatalogBootstrapManifestSetV1:
    if isinstance(source, Path):
        return CatalogBootstrapManifestSetV1.model_validate_json(
            source.read_text("utf-8")
        )
    return CatalogBootstrapManifestSetV1.model_validate(dict(source))


def github_manifest_payload(
    app: CatalogBootstrapAppManifestV1,
    *,
    redirect_url: str,
) -> dict[str, object]:
    if not redirect_url.startswith("http://127.0.0.1:"):
        raise ValueError("CATALOG_BOOTSTRAP_CALLBACK_NOT_LOOPBACK")
    return {
        "name": app.name,
        "url": str(app.homepage_url),
        "description": app.description,
        "redirect_url": redirect_url,
        "public": False,
        "default_events": [],
        "default_permissions": dict(sorted(app.manifest_permissions.items())),
        "request_oauth_on_install": False,
        "setup_on_update": False,
    }


def canonical_manifest_bytes(value: CatalogBootstrapManifestSetV1) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
