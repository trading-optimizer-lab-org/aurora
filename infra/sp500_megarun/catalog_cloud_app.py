"""Bounded GitHub App session for the cloud catalog intake.

This module validates the requester, controller actor and cloud-app binding
before asking the real GitHub App client for an installation token.  The
installation identity remains historical until that real token is obtained
and its permissions and repository scope are checked by the client.

The session does not, by itself, establish local private-key custody, a
cutover, or chat-origin evidence.  It also does not qualify any authority or
emission state; callers must perform those checks separately.

If the broker rejects an installation-token response before returning its
opaque token (for example, because permissions or repository scope are wrong),
this boundary has no token value to revoke.  It propagates that safe broker
error and does not mark the installation qualified; changing that broker
behavior is intentionally outside this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ConfigDict, Field, StrictInt, StrictStr

from .catalog_request_contract import FrozenModel
from .catalog_requester_broker import (
    CatalogBrokerGithubClient,
    CatalogRequesterBrokerConfigV1,
    RequestsCatalogBrokerHttpTransport,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_TRUSTED_APP_ID = 4_693_452
_TRUSTED_INSTALLATION_ID = 155_982_969
_TRUSTED_ACTOR = "aurora-catalog-request-f10c7b40e1[bot]"
_PUBLIC_KEY_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 64 * 1024
_MAX_PUBLIC_KEY_BYTES = 16 * 1024


class CatalogCloudAppBindingV1(FrozenModel):
    """Strict schema for the app/installation identity used by this boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"]
    repository: StrictStr
    app_id: StrictInt = Field(ge=1)
    installation_id: StrictInt = Field(ge=1)
    expected_actor: StrictStr


def _invalid(code: str) -> ValueError:
    return ValueError(code)


def _reject_nul(value: object) -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise _invalid("CLOUD_APP_JSON_NUL")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_nul(key)
            _reject_nul(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_nul(item)


def _fixed_root(repo_root: Path) -> Path:
    if not isinstance(repo_root, Path):
        raise _invalid("CLOUD_APP_REPO_ROOT_INVALID")
    try:
        root = repo_root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _invalid("CLOUD_APP_REPO_ROOT_INVALID") from None
    if not root.is_dir():
        raise _invalid("CLOUD_APP_REPO_ROOT_INVALID")
    return root


def _safe_relative_path(value: object) -> PurePosixPath:
    if type(value) is not str or not value or "\x00" in value:
        raise _invalid("CLOUD_APP_PUBLIC_KEY_PATH_INVALID")
    if "\\" in value or any(ord(char) < 0x20 for char in value):
        raise _invalid("CLOUD_APP_PUBLIC_KEY_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise _invalid("CLOUD_APP_PUBLIC_KEY_PATH_INVALID")
    if ":" in path.parts[0]:
        raise _invalid("CLOUD_APP_PUBLIC_KEY_PATH_INVALID")
    return path


def _fixed_file(root: Path, relative: str, *, code: str, maximum_bytes: int) -> tuple[Path, bytes]:
    if "\x00" in relative:
        raise _invalid(code)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            raise _invalid(code)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise _invalid(code)
        if not stat.S_ISREG(candidate.stat().st_mode):
            raise _invalid(code)
        data = candidate.read_bytes()
    except ValueError:
        raise
    except (OSError, RuntimeError):
        raise _invalid(code) from None
    if len(data) > maximum_bytes:
        raise _invalid(code)
    return candidate, data


def _strict_json_object(data: bytes, *, code: str) -> dict[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _invalid("CLOUD_APP_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise _invalid("CLOUD_APP_JSON_NONFINITE")

    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except ValueError as exc:
        if str(exc).startswith("CLOUD_APP_"):
            raise
        raise _invalid(code) from None
    except (TypeError, UnicodeError):
        raise _invalid(code) from None
    if not isinstance(payload, dict):
        raise _invalid(code)
    _reject_nul(payload)
    return payload


def _load_json(root: Path, relative: str, *, code: str) -> dict[str, object]:
    _, data = _fixed_file(root, relative, code=code, maximum_bytes=_MAX_JSON_BYTES)
    return _strict_json_object(data, code=code)


def _load_requester_config(root: Path) -> CatalogRequesterBrokerConfigV1:
    payload = _load_json(
        root,
        "config/catalog_requester_v1.json",
        code="CLOUD_APP_REQUESTER_CONFIG_INVALID",
    )
    try:
        # JSON has no tuple type.  Normalize only this historical tuple field
        # after checking its element types, then keep the rest of the model
        # validation strict.
        forbidden = payload.get("forbidden_write_permissions")
        if type(forbidden) is not list or any(type(item) is not str for item in forbidden):
            raise _invalid("CLOUD_APP_REQUESTER_CONFIG_INVALID")
        strict_payload = dict(payload)
        strict_payload["forbidden_write_permissions"] = tuple(forbidden)
        config = CatalogRequesterBrokerConfigV1.model_validate(strict_payload, strict=True)
    except Exception:
        raise _invalid("CLOUD_APP_REQUESTER_CONFIG_INVALID") from None
    if config.repository != _REPOSITORY:
        raise _invalid("CLOUD_APP_REPOSITORY_MISMATCH")
    return config


def _load_actors(root: Path) -> tuple[str, str, list[str]]:
    payload = _load_json(
        root,
        "config/catalog_controller_actors_v1.json",
        code="CLOUD_APP_ACTORS_INVALID",
    )
    if payload.get("schema_version") != "1":
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    if payload.get("production_enabled") is not True:
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    if payload.get("required_request_actor_kind") != "non_admin_github_app":
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    if payload.get("deny_actor_if_repository_admin_credential_is_exposed") is not True:
        raise _invalid("CLOUD_APP_ACTORS_INVALID")

    actors = payload.get("request_actors")
    if (
        not isinstance(actors, list)
        or not actors
        or any(type(actor) is not str or not actor for actor in actors)
    ):
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    public_key_path = payload.get("requester_public_key_path")
    public_key_hash = payload.get("requester_public_key_sha256")
    if type(public_key_path) is not str or type(public_key_hash) is not str:
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    if not _PUBLIC_KEY_HASH_PATTERN.fullmatch(public_key_hash):
        raise _invalid("CLOUD_APP_ACTORS_INVALID")
    return public_key_path, public_key_hash, actors


def _load_binding(root: Path) -> CatalogCloudAppBindingV1:
    payload = _load_json(
        root,
        "config/catalog_cloud_app_binding_v1.json",
        code="CLOUD_APP_BINDING_INVALID",
    )
    try:
        binding = CatalogCloudAppBindingV1.model_validate(payload, strict=True)
    except Exception:
        raise _invalid("CLOUD_APP_BINDING_INVALID") from None
    if (
        binding.schema_version != "1"
        or binding.repository != _REPOSITORY
        or binding.app_id != _TRUSTED_APP_ID
        or binding.installation_id != _TRUSTED_INSTALLATION_ID
    ):
        raise _invalid("CLOUD_APP_BINDING_INVALID")
    if binding.expected_actor != _TRUSTED_ACTOR:
        raise _invalid("CLOUD_APP_ACTOR_MISMATCH")
    return binding


def _load_trusted_public_key(
    root: Path,
    *,
    public_key_path: str,
    expected_hash: str,
    private_key_pem: bytes,
) -> bytes:
    public_path = _safe_relative_path(public_key_path)
    candidate, trusted_public_key = _fixed_file(
        root,
        str(public_path),
        code="CLOUD_APP_PUBLIC_KEY_INVALID",
        maximum_bytes=_MAX_PUBLIC_KEY_BYTES,
    )
    del candidate
    try:
        public_key = serialization.load_pem_public_key(trusted_public_key)
    except (TypeError, ValueError):
        raise _invalid("CLOUD_APP_PUBLIC_KEY_INVALID") from None
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise _invalid("CLOUD_APP_PUBLIC_KEY_INVALID")
    try:
        trusted_der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        canonical_public_pem = public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (TypeError, ValueError):
        raise _invalid("CLOUD_APP_PUBLIC_KEY_INVALID") from None
    if canonical_public_pem != trusted_public_key:
        raise _invalid("CLOUD_APP_PUBLIC_KEY_INVALID")
    if hashlib.sha256(trusted_der).hexdigest() != expected_hash:
        raise _invalid("CLOUD_APP_PUBLIC_KEY_HASH_MISMATCH")

    if type(private_key_pem) is not bytes or not private_key_pem:
        raise _invalid("CLOUD_APP_PRIVATE_KEY_INVALID")
    try:
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError):
        raise _invalid("CLOUD_APP_PRIVATE_KEY_INVALID") from None
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
        raise _invalid("CLOUD_APP_PRIVATE_KEY_INVALID")
    try:
        derived_public_key = private_key.public_key()
        derived_public_pem = derived_public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        derived_der = derived_public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (TypeError, ValueError):
        raise _invalid("CLOUD_APP_PRIVATE_KEY_INVALID") from None
    if derived_public_pem != trusted_public_key:
        raise _invalid("CLOUD_APP_PRIVATE_KEY_MISMATCH")
    if hashlib.sha256(derived_der).hexdigest() != expected_hash:
        raise _invalid("CLOUD_APP_PRIVATE_KEY_MISMATCH")
    return trusted_public_key


def _build_client(repo_root: Path, private_key_pem: bytes) -> tuple[CatalogBrokerGithubClient, bytes]:
    root = _fixed_root(repo_root)
    config = _load_requester_config(root)
    public_key_path, public_key_hash, actors = _load_actors(root)
    binding = _load_binding(root)
    if actors != [_TRUSTED_ACTOR] or binding.expected_actor not in actors:
        raise _invalid("CLOUD_APP_ACTOR_MISMATCH")
    trusted_public_key = _load_trusted_public_key(
        root,
        public_key_path=public_key_path,
        expected_hash=public_key_hash,
        private_key_pem=private_key_pem,
    )
    transport = RequestsCatalogBrokerHttpTransport(timeout_seconds=config.timeout_seconds)
    client = CatalogBrokerGithubClient(
        config=config,
        http=transport,
        app_id=binding.app_id,
        installation_id=binding.installation_id,
        private_key_pem=private_key_pem,
        expected_actor=binding.expected_actor,
    )
    return client, trusted_public_key


def _mask_token(token: str) -> None:
    if type(token) is not str or not token or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in token
    ):
        raise _invalid("CLOUD_APP_TOKEN_INVALID")
    print(f"::add-mask::{token}", flush=True)


def _report_revocation_failure() -> None:
    # Never include the exception text: a transport implementation may embed
    # the token, JWT, request headers or another secret in it.
    print("CLOUD_APP_TOKEN_REVOCATION_FAILED", file=sys.stderr, flush=True)


@contextmanager
def cloud_app_session(
    repo_root: Path,
    private_key_pem: bytes,
) -> Iterator[tuple[CatalogBrokerGithubClient, str, bytes]]:
    """Yield a verified client, token and trusted public-key PEM bytes.

    The real client obtains and verifies the installation token before the
    yield.  The token is registered with the Actions ``add-mask`` command and
    is revoked on every normal or exceptional exit.  This boundary does not
    prove local key custody, cutover or chat origin, and it does not itself
    mark an installation or authority as qualified.  A token response rejected
    before the client returns its opaque token cannot be revoked here because
    this API deliberately does not receive unproven token material.
    """

    client, trusted_public_key = _build_client(repo_root, private_key_pem)
    token = client.installation_token()
    try:
        _mask_token(token)
    except BaseException:
        try:
            client.revoke_installation_token(token)
        except BaseException:
            _report_revocation_failure()
        raise
    try:
        yield client, token, trusted_public_key
    except BaseException:
        try:
            client.revoke_installation_token(token)
        except BaseException:
            _report_revocation_failure()
        raise
    else:
        try:
            client.revoke_installation_token(token)
        except BaseException:
            _report_revocation_failure()
            raise _invalid("CLOUD_APP_TOKEN_REVOCATION_FAILED") from None


__all__ = ["CatalogCloudAppBindingV1", "cloud_app_session"]
