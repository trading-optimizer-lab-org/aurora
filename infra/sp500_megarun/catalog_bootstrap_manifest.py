"""Loopback-only GitHub App Manifest callback and conversion primitives."""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Mapping, Protocol


_CODE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_STATE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class _Response(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _Http(Protocol):
    def post(self, url: str, **kwargs: object) -> _Response: ...


@dataclass(frozen=True, slots=True)
class ManifestSession:
    kind: Literal["requester", "auditor"]
    state: str
    bind_host: Literal["127.0.0.1"]
    callback_path: Literal["/github/manifest/callback"]
    created_at: datetime
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True, slots=True)
class AcceptedManifestCallback:
    session: ManifestSession
    query: dict[str, str]


@dataclass(slots=True)
class GitHubManifestConversion:
    app_id: int
    slug: str
    private_key_pem: bytearray = field(repr=False)
    client_secret: bytearray = field(repr=False)
    webhook_secret: bytearray = field(repr=False)

    def __repr__(self) -> str:
        return (
            "GitHubManifestConversion("
            f"app_id={self.app_id!r}, slug={self.slug!r}, private_material=<redacted>)"
        )

    def clear(self) -> None:
        for value in (
            self.private_key_pem,
            self.client_secret,
            self.webhook_secret,
        ):
            for index in range(len(value)):
                value[index] = 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("MANIFEST_TIME_MUST_BE_AWARE")
    return value.astimezone(UTC)


def start_manifest_session(
    kind: Literal["requester", "auditor"],
    *,
    now: datetime,
) -> ManifestSession:
    created = _utc(now)
    state = secrets.token_urlsafe(48)
    if not _STATE.fullmatch(state):
        raise ValueError("MANIFEST_STATE_GENERATION_FAILED")
    return ManifestSession(
        kind=kind,
        state=state,
        bind_host="127.0.0.1",
        callback_path="/github/manifest/callback",
        created_at=created,
        expires_at=created + timedelta(hours=1),
    )


def accept_manifest_callback(
    session: ManifestSession,
    query: Mapping[str, str],
    now: datetime,
    *,
    host: str = "127.0.0.1",
) -> AcceptedManifestCallback:
    if session.used:
        raise ValueError("CALLBACK_REPLAY")
    if host != session.bind_host:
        raise ValueError("CALLBACK_HOST_INVALID")
    if _utc(now) > session.expires_at:
        raise ValueError("CALLBACK_EXPIRED")
    if set(query) != {"code", "state"} or not all(
        isinstance(value, str) for value in query.values()
    ):
        raise ValueError("CALLBACK_QUERY_INVALID")
    code = query["code"]
    state = query["state"]
    if not _CODE.fullmatch(code):
        raise ValueError("MANIFEST_CODE_INVALID")
    if not _STATE.fullmatch(state) or not hmac.compare_digest(state, session.state):
        raise ValueError("STATE_MISMATCH")
    accepted_query = {"code": code, "state": state}
    return AcceptedManifestCallback(
        session=replace(session, used=True),
        query=accepted_query,
    )


def _private_bytes(payload: dict[str, object], name: str) -> bytearray:
    value = payload.pop(name, None)
    if not isinstance(value, str) or not value:
        raise ValueError("MANIFEST_CONVERSION_INVALID")
    return bytearray(value.encode("utf-8"))


def exchange_manifest_code(
    code: str,
    *,
    http: _Http | None = None,
) -> GitHubManifestConversion:
    if not _CODE.fullmatch(code):
        raise ValueError("MANIFEST_CODE_INVALID")
    if http is None:
        import requests

        http = requests.Session()
    response = http.post(
        f"https://api.github.com/app-manifests/{code}/conversions",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        timeout=(5, 20),
    )
    response.raise_for_status()
    raw_payload = response.json()
    if not isinstance(raw_payload, dict):
        raise ValueError("MANIFEST_CONVERSION_INVALID")
    payload = dict(raw_payload)
    app_id = payload.get("id")
    slug = payload.get("slug")
    if not isinstance(app_id, int) or app_id < 1 or not isinstance(slug, str):
        raise ValueError("MANIFEST_CONVERSION_INVALID")
    private_key_pem = _private_bytes(payload, "pem")
    try:
        client_secret = _private_bytes(payload, "client_secret")
        webhook_secret = _private_bytes(payload, "webhook_secret")
    except Exception:
        for index in range(len(private_key_pem)):
            private_key_pem[index] = 0
        raise
    return GitHubManifestConversion(
        app_id=app_id,
        slug=slug,
        private_key_pem=private_key_pem,
        client_secret=client_secret,
        webhook_secret=webhook_secret,
    )
