from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import aurora.infra.sp500_megarun.catalog_cloud_app as cloud_app
from aurora.infra.sp500_megarun.catalog_requester_broker import (
    CatalogBrokerGithubClient,
    CatalogBrokerHttpResponse,
)


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "trading-optimizer-lab-org/aurora"
EXPECTED_ACTOR = "aurora-catalog-request-f10c7b40e1[bot]"


def _private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _public_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _public_der_hash(key: rsa.RSAPrivateKey) -> str:
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def _make_repo(tmp_path: Path, key: rsa.RSAPrivateKey, **binding_updates: object) -> tuple[Path, bytes, bytes]:
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True)

    requester_config = json.loads(
        (ROOT / "config/catalog_requester_v1.json").read_text(encoding="utf-8")
    )
    _write_json(config_dir / "catalog_requester_v1.json", requester_config)

    public_pem = _public_pem(key)
    public_path = config_dir / "trusted-public.pem"
    public_path.write_bytes(public_pem)
    actors = json.loads(
        (ROOT / "config/catalog_controller_actors_v1.json").read_text(encoding="utf-8")
    )
    actors["requester_public_key_path"] = "config/trusted-public.pem"
    actors["requester_public_key_sha256"] = _public_der_hash(key)
    actors["request_actors"] = [EXPECTED_ACTOR]
    _write_json(config_dir / "catalog_controller_actors_v1.json", actors)

    binding = json.loads(
        (ROOT / "config/catalog_cloud_app_binding_v1.json").read_text(encoding="utf-8")
    )
    binding.update(binding_updates)
    _write_json(config_dir / "catalog_cloud_app_binding_v1.json", binding)
    return repo_root, _private_pem(key), public_pem


class _SyntheticTransport:
    def __init__(
        self,
        *,
        permissions: dict[str, str] | None = None,
        repositories: list[dict[str, str]] | None = None,
        revoke_status: int = 204,
    ) -> None:
        self.permissions = permissions or {"issues": "write", "metadata": "read"}
        self.repositories = repositories or [{"full_name": REPOSITORY}]
        self.revoke_status = revoke_status
        self.calls: list[tuple[str, str, dict[str, str], object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        self.calls.append((method, url, headers, json_body))
        if method == "POST" and url.endswith("/app/installations/155982969/access_tokens"):
            return CatalogBrokerHttpResponse(
                status_code=201,
                headers={},
                json_body={
                    "token": "opaque-installation-token",
                    "permissions": self.permissions,
                    "repositories": self.repositories,
                },
            )
        if method == "DELETE" and url == "https://api.github.com/installation/token":
            return CatalogBrokerHttpResponse(
                status_code=self.revoke_status,
                headers={},
                json_body=None,
            )
        raise AssertionError("unexpected synthetic transport endpoint")


def _patch_transport(monkeypatch: pytest.MonkeyPatch, transport: _SyntheticTransport) -> list[int]:
    timeouts: list[int] = []

    def factory(*, timeout_seconds: int) -> _SyntheticTransport:
        timeouts.append(timeout_seconds)
        return transport

    monkeypatch.setattr(cloud_app, "RequestsCatalogBrokerHttpTransport", factory)
    return timeouts


def test_session_uses_real_client_locked_timeout_masks_and_revokes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = _private_key()
    repo_root, private_pem, public_pem = _make_repo(tmp_path, key)
    transport = _SyntheticTransport()
    timeouts = _patch_transport(monkeypatch, transport)

    with cloud_app.cloud_app_session(repo_root, private_pem) as (client, token, trusted):
        assert isinstance(client, CatalogBrokerGithubClient)
        assert token == "opaque-installation-token"
        assert trusted == public_pem

    assert timeouts == [30]
    assert [call[0] for call in transport.calls] == ["POST", "DELETE"]
    assert transport.calls[1][1] == "https://api.github.com/installation/token"
    captured = capsys.readouterr()
    assert captured.out == "::add-mask::opaque-installation-token\n"
    assert "BEGIN PRIVATE KEY" not in captured.out
    assert "BEGIN PUBLIC KEY" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("binding_updates", "expected_code"),
    [
        ({"expected_actor": "other-app[bot]"}, "CLOUD_APP_ACTOR_MISMATCH"),
        ({"app_id": 4693453}, "CLOUD_APP_BINDING_INVALID"),
        ({"installation_id": 155982970}, "CLOUD_APP_BINDING_INVALID"),
        ({"repository": "other/example"}, "CLOUD_APP_BINDING_INVALID"),
    ],
)
def test_binding_identity_mismatches_are_rejected_before_token_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_updates: dict[str, object],
    expected_code: str,
) -> None:
    key = _private_key()
    repo_root, private_pem, _ = _make_repo(tmp_path, key, **binding_updates)
    transport = _SyntheticTransport()
    _patch_transport(monkeypatch, transport)

    with pytest.raises(ValueError, match=expected_code):
        with cloud_app.cloud_app_session(repo_root, private_pem):
            raise AssertionError("session must not yield")
    assert transport.calls == []


def test_public_hash_mismatch_and_private_key_mismatch_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _private_key()
    repo_root, private_pem, _ = _make_repo(tmp_path, key)
    actors_path = repo_root / "config/catalog_controller_actors_v1.json"
    actors = json.loads(actors_path.read_text(encoding="utf-8"))
    actors["requester_public_key_sha256"] = "0" * 64
    _write_json(actors_path, actors)
    transport = _SyntheticTransport()
    _patch_transport(monkeypatch, transport)

    with pytest.raises(ValueError, match="CLOUD_APP_PUBLIC_KEY_HASH_MISMATCH"):
        with cloud_app.cloud_app_session(repo_root, private_pem):
            raise AssertionError("session must not yield")
    assert transport.calls == []

    key2 = _private_key()
    repo_root2, _, _ = _make_repo(tmp_path / "second", key)
    with pytest.raises(ValueError, match="CLOUD_APP_PRIVATE_KEY_MISMATCH"):
        with cloud_app.cloud_app_session(repo_root2, _private_pem(key2)):
            raise AssertionError("session must not yield")
    assert transport.calls == []


@pytest.mark.parametrize(
    ("permissions", "repositories", "expected_code"),
    [
        ({"issues": "write", "metadata": "read", "contents": "read"}, None, "REQUESTER_APP_OVERPRIVILEGED"),
        (None, [{"full_name": "other/example"}], "REQUESTER_APP_REPOSITORY_SCOPE_INVALID"),
    ],
)
def test_installation_token_scope_is_verified_before_yield_and_revoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permissions: dict[str, str] | None,
    repositories: list[dict[str, str]] | None,
    expected_code: str,
) -> None:
    key = _private_key()
    repo_root, private_pem, _ = _make_repo(tmp_path, key)
    transport = _SyntheticTransport(permissions=permissions, repositories=repositories)
    _patch_transport(monkeypatch, transport)

    with pytest.raises(ValueError, match=expected_code):
        with cloud_app.cloud_app_session(repo_root, private_pem):
            raise AssertionError("session must not yield")
    assert [call[0] for call in transport.calls] == ["POST"]


def test_body_exception_is_preserved_when_revocation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = _private_key()
    repo_root, private_pem, _ = _make_repo(tmp_path, key)
    transport = _SyntheticTransport(revoke_status=500)
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="body-failure"):
        with cloud_app.cloud_app_session(repo_root, private_pem):
            raise RuntimeError("body-failure")
    captured = capsys.readouterr()
    assert captured.err == "CLOUD_APP_TOKEN_REVOCATION_FAILED\n"
    assert "opaque-installation-token" not in captured.err


def test_revocation_failure_without_body_exception_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = _private_key()
    repo_root, private_pem, _ = _make_repo(tmp_path, key)
    transport = _SyntheticTransport(revoke_status=500)
    _patch_transport(monkeypatch, transport)

    with pytest.raises(ValueError, match="CLOUD_APP_TOKEN_REVOCATION_FAILED"):
        with cloud_app.cloud_app_session(repo_root, private_pem):
            pass
    captured = capsys.readouterr()
    assert captured.err == "CLOUD_APP_TOKEN_REVOCATION_FAILED\n"
    assert "opaque-installation-token" not in captured.err
