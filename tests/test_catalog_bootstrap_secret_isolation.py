from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from infra.sp500_megarun.catalog_bootstrap_contract import (
    load_catalog_bootstrap_manifests,
)
from infra.sp500_megarun.catalog_bootstrap_github import (
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
    with pytest.raises(ValueError, match="SECRET_ACL_OPEN"):
        store_requester_key_once(tmp_path / "requester-private-key.pem", _key_pem())


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
