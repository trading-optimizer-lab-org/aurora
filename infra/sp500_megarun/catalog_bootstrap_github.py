"""Exact GitHub installation verification and public binding derivation."""

from __future__ import annotations

import hashlib
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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


@dataclass(frozen=True, slots=True)
class VerifiedCatalogAppAccess:
    installation_id: int
    installation: VerifiedCatalogAppInstallation


class _Response(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _Http(Protocol):
    def request(self, method: str, url: str, **kwargs: object) -> _Response: ...


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _app_jwt(app_id: int, key: rsa.RSAPrivateKey) -> str:
    now = datetime.now(tz=UTC)
    header = _base64url(b'{"alg":"RS256","typ":"JWT"}')
    payload = _base64url(
        json.dumps(
            {
                "exp": int((now + timedelta(minutes=8)).timestamp()),
                "iat": int((now - timedelta(seconds=30)).timestamp()),
                "iss": str(app_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    unsigned = f"{header}.{payload}".encode("ascii")
    signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
    return f"{unsigned.decode()}.{_base64url(signature)}"


class CatalogBootstrapGitHubClient:
    def __init__(
        self,
        *,
        app_id: int,
        private_key_pem: bytearray,
        http: _Http | None = None,
    ) -> None:
        if app_id < 1:
            raise ValueError("APP_IDENTITY_INVALID")
        key = serialization.load_pem_private_key(bytes(private_key_pem), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("APP_PRIVATE_KEY_INVALID")
        if http is None:
            import requests

            http = requests.Session()
        self.app_id = app_id
        self._private_key_pem = private_key_pem
        self._key = key
        self._http = http

    def __repr__(self) -> str:
        return f"CatalogBootstrapGitHubClient(app_id={self.app_id}, private_material=<redacted>)"

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        bearer: str,
        body: Mapping[str, object] | None = None,
    ) -> object:
        response = self._http.request(
            method,
            f"https://api.github.com{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {bearer}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json=None if body is None else dict(body),
            timeout=(5, 20),
        )
        response.raise_for_status()
        return response.json()

    def find_exact_installation(
        self,
        expected: CatalogBootstrapAppManifestV1,
    ) -> VerifiedCatalogAppAccess:
        jwt = _app_jwt(self.app_id, self._key)
        rows = self._request("GET", "/app/installations", bearer=jwt)
        if not isinstance(rows, list):
            raise ValueError("APP_INSTALLATION_LIST_INVALID")
        matches = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and row.get("app_id") == self.app_id
            and isinstance(row.get("account"), Mapping)
            and row["account"].get("login") == "trading-optimizer-lab-org"
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), int):
            raise ValueError("APP_INSTALLATION_NOT_EXACT")
        row = matches[0]
        installation_id = int(row["id"])
        token_payload = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            bearer=jwt,
            body={
                "repositories": ["aurora"],
                "permissions": dict(sorted(expected.manifest_permissions.items())),
            },
        )
        if not isinstance(token_payload, Mapping) or not isinstance(
            token_payload.get("token"), str
        ):
            raise ValueError("APP_INSTALLATION_TOKEN_INVALID")
        ephemeral = str(token_payload["token"])
        repositories = self._request(
            "GET",
            "/installation/repositories",
            bearer=ephemeral,
        )
        if not isinstance(repositories, Mapping) or not isinstance(
            repositories.get("repositories"), list
        ):
            raise ValueError("APP_INSTALLATION_REPOSITORIES_INVALID")
        names = [
            item.get("full_name")
            for item in repositories["repositories"]
            if isinstance(item, Mapping)
        ]
        verified = verify_exact_installation(
            {
                "app_id": row.get("app_id"),
                "app_slug": row.get("app_slug"),
                "repositories": names,
                "permissions": row.get("permissions"),
            },
            expected,
        )
        ephemeral = ""
        jwt = ""
        return VerifiedCatalogAppAccess(
            installation_id=installation_id,
            installation=verified,
        )

    def close(self) -> None:
        for index in range(len(self._private_key_pem)):
            self._private_key_pem[index] = 0
        self._key = None  # type: ignore[assignment]


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
