from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from infra.sp500_megarun import catalog_bootstrap_secrets as secrets_module

from infra.sp500_megarun.catalog_bootstrap_contract import (
    load_catalog_bootstrap_manifests,
)
from infra.sp500_megarun.catalog_bootstrap_github import (
    CatalogBootstrapGitHubClient,
    derive_public_binding,
    verify_exact_installation,
)
from infra.sp500_megarun.catalog_bootstrap_secrets import (
    clear_private_material,
    store_requester_key_once,
    upload_auditor_key_once,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = load_catalog_bootstrap_manifests(
    ROOT / "config/catalog_bootstrap_app_manifests_v1.json"
)


def _key_pem() -> bytearray:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return bytearray(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _installation() -> dict[str, object]:
    return {
        "app_id": 123,
        "app_slug": "aurora-catalog-requester",
        "repositories": ["trading-optimizer-lab-org/aurora"],
        "repository_permissions": dict(
            MANIFESTS.requester.expected_repository_permissions
        ),
        "organization_permissions": {},
        "enterprise_permissions": {},
    }


def test_installation_rejects_extra_repository_or_permission() -> None:
    extra_repository = _installation()
    extra_repository["repositories"] = [
        "trading-optimizer-lab-org/aurora",
        "trading-optimizer-lab-org/other",
    ]
    with pytest.raises(ValueError, match="INSTALL_SCOPE_INVALID"):
        verify_exact_installation(extra_repository, MANIFESTS.requester)

    extra_permission = _installation()
    extra_permission["repository_permissions"] = {
        **MANIFESTS.requester.expected_repository_permissions,
        "contents": "read",
    }
    with pytest.raises(ValueError, match="APP_PERMISSION_DRIFT"):
        verify_exact_installation(extra_permission, MANIFESTS.requester)


def test_installation_accepts_provider_permission_names_for_auditor() -> None:
    snapshot = {
        "app_id": 456,
        "app_slug": "aurora-catalog-controls-auditor",
        "repositories": [MANIFESTS.repository],
        "permissions": dict(MANIFESTS.auditor.manifest_permissions),
    }
    verified = verify_exact_installation(snapshot, MANIFESTS.auditor)
    assert verified.repository_permissions == dict(
        MANIFESTS.auditor.expected_repository_permissions
    )
    assert verified.organization_permissions == {"administration": "read"}
    assert verified.enterprise_permissions == {}


def test_public_binding_contains_only_public_key_material() -> None:
    private = _key_pem()
    binding = derive_public_binding(
        kind="requester",
        app_id=123,
        slug="aurora-catalog-requester",
        private_key_pem=private,
    )
    assert binding.public_key_pem.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert b"PRIVATE KEY" not in binding.public_key_pem
    assert len(binding.public_key_sha256) == 64


def test_requester_key_requires_preclosed_parent(tmp_path: Path) -> None:
    if secrets_module.os.name == "nt":
        result = secrets_module.subprocess.run(
            ["icacls.exe", str(tmp_path), "/grant", "*S-1-1-0:(OI)(CI)F"],
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0
    with pytest.raises(ValueError, match="SECRET_ACL_OPEN"):
        store_requester_key_once(tmp_path / "requester-private-key.pem", _key_pem())


def test_default_acl_checker_passes_path_via_dedicated_environment_variable(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    class Result:
        returncode = 0
        stdout = "O:BAG:SYD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

    def fake_run(args: list[str], **kwargs: object) -> Result:
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(secrets_module, "_is_reparse_point", lambda _path: False)
    monkeypatch.setattr(secrets_module.subprocess, "run", fake_run)

    assert secrets_module._default_acl_checker(tmp_path) is True
    args, kwargs = calls[0]
    assert str(tmp_path) not in args
    assert "$env:AURORA_CATALOG_ACL_PATH" in args[-1]
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["AURORA_CATALOG_ACL_PATH"] == str(tmp_path)
    assert not any(key.casefold() == "psmodulepath" for key in environment)


def test_requester_key_is_create_new_and_read_back_verified(tmp_path: Path) -> None:
    target = tmp_path / "requester-private-key.pem"
    first = _key_pem()
    fingerprint = store_requester_key_once(
        target,
        first,
        acl_checker=lambda _parent: True,
    )
    assert len(fingerprint) == 64
    assert target.exists()
    assert not any(first)
    with pytest.raises(ValueError, match="SECRET_ALREADY_EXISTS"):
        store_requester_key_once(
            target,
            _key_pem(),
            acl_checker=lambda _parent: True,
        )


class _RunResult:
    returncode = 0
    stdout = b'{"name":"AURORA_CATALOG_AUDITOR_PRIVATE_KEY","created_at":"now"}'
    stderr = b""


def test_auditor_upload_uses_stdin_then_removes_staging(tmp_path: Path) -> None:
    calls: list[tuple[list[str], bytes | None]] = []

    def run(args: list[str], **kwargs: object) -> _RunResult:
        calls.append((args, kwargs.get("input")))
        return _RunResult()

    staging = tmp_path / "auditor-private-key.pem"
    material = _key_pem()
    proof = upload_auditor_key_once(
        staging,
        material,
        acl_checker=lambda _parent: True,
        run=run,
    )
    assert proof["name"] == "AURORA_CATALOG_AUDITOR_PRIVATE_KEY"
    assert calls[0][0] == [
        "gh",
        "secret",
        "set",
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "--env",
        "catalog-production",
        "--repo",
        "trading-optimizer-lab-org/aurora",
    ]
    assert calls[0][1] and b"PRIVATE KEY" in calls[0][1]
    assert not staging.exists()
    assert not any(material)


def test_clear_private_material_zeroes_all_buffers() -> None:
    values = [bytearray(b"one"), bytearray(b"two")]
    clear_private_material(*values)
    assert all(not any(value) for value in values)


class _GithubResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _GithubHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _GithubResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/app/installations"):
            return _GithubResponse(
                [
                    {
                        "id": 789,
                        "app_id": 123,
                        "app_slug": "aurora-catalog-requester",
                        "account": {"login": "trading-optimizer-lab-org"},
                        "permissions": {"issues": "write", "metadata": "read"},
                    }
                ]
            )
        if url.endswith("/access_tokens"):
            return _GithubResponse({"token": "EPHEMERAL-MARKER"})
        if url.endswith("/installation/repositories"):
            return _GithubResponse(
                {
                    "total_count": 1,
                    "repositories": [{"full_name": "trading-optimizer-lab-org/aurora"}],
                }
            )
        raise AssertionError(url)


def test_app_client_verifies_exact_live_installation_without_exposing_token() -> None:
    private = _key_pem()
    http = _GithubHttp()
    client = CatalogBootstrapGitHubClient(
        app_id=123,
        private_key_pem=private,
        http=http,
    )
    verified = client.find_exact_installation(MANIFESTS.requester)
    assert verified.installation_id == 789
    assert verified.installation.app_slug == "aurora-catalog-requester"
    assert "EPHEMERAL-MARKER" not in repr(client)
    client.close()
    assert not any(private)
