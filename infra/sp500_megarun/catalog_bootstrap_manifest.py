"""Loopback-only GitHub App Manifest callback and conversion primitives."""

from __future__ import annotations

import hmac
import html
import json
import re
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Literal, Mapping, Protocol
from urllib.parse import parse_qs, urlsplit

from .catalog_bootstrap_contract import (
    CatalogBootstrapAppManifestV1,
    github_manifest_payload,
)


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


class ManifestLoopbackServer:
    def __init__(
        self,
        session: ManifestSession,
        app: CatalogBootstrapAppManifestV1,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if session.kind != app.kind:
            raise ValueError("MANIFEST_SESSION_ROLE_INVALID")
        self.session = session
        self.app = app
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._accepted: AcceptedManifestCallback | None = None
        self._delivered = False
        self._ready = threading.Event()
        self._server = HTTPServer((session.bind_host, 0), self._handler_type())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"catalog-manifest-{app.kind}",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def start_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/start"

    @property
    def callback_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.session.callback_path}"

    def _start_page(self) -> bytes:
        redirect = f"{self.callback_url}?state={self.session.state}"
        manifest = json.dumps(
            github_manifest_payload(self.app, redirect_url=redirect),
            sort_keys=True,
            separators=(",", ":"),
        )
        action = (
            "https://github.com/organizations/"
            "trading-optimizer-lab-org/settings/apps/new"
        )
        return (
            "<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer>"
            "<title>AURORA GitHub App</title>"
            f"<p>GitHub va a crear {html.escape(self.app.name)} con permisos cerrados.</p>"
            f"<form id=f method=post action=\"{action}\">"
            f"<input type=hidden name=manifest value=\"{html.escape(manifest, quote=True)}\">"
            "<button type=submit>Continuar en GitHub</button></form>"
            "<script>document.getElementById('f').submit()</script>"
        ).encode("utf-8")

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return None

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if sum(len(key) + len(value) for key, value in self.headers.items()) > 16384:
                    self._send(431, b"request rejected")
                    return
                expected_host = f"127.0.0.1:{owner.port}"
                if self.headers.get("Host") != expected_host:
                    self._send(400, b"request rejected")
                    return
                parsed = urlsplit(self.path)
                if parsed.path == "/start" and not parsed.query:
                    self._send(200, owner._start_page())
                    return
                if parsed.path != owner.session.callback_path or len(self.path) > 1024:
                    self._send(404, b"not found")
                    return
                query_values = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(values) != 1 for values in query_values.values()):
                    self._send(400, b"request rejected")
                    return
                query = {key: values[0] for key, values in query_values.items()}
                try:
                    owner._accepted = accept_manifest_callback(
                        owner.session,
                        query,
                        owner._clock(),
                        host="127.0.0.1",
                    )
                except ValueError:
                    self._send(400, b"request rejected")
                    return
                owner.session = owner._accepted.session
                owner._ready.set()
                self._send(200, b"<p>AURORA ha recibido la confirmacion. Puede cerrar esta pestana.</p>")

        return Handler

    def __enter__(self) -> "ManifestLoopbackServer":
        self._thread.start()
        return self

    def wait(
        self,
        *,
        now: datetime | None = None,
        timeout_seconds: float = 3600,
    ) -> AcceptedManifestCallback:
        if self._delivered:
            raise ValueError("CALLBACK_REPLAY")
        if not self._ready.wait(timeout_seconds):
            raise ValueError("CALLBACK_EXPIRED")
        if now is not None and _utc(now) > self.session.expires_at:
            raise ValueError("CALLBACK_EXPIRED")
        if self._accepted is None:
            raise ValueError("CALLBACK_MISSING")
        self._delivered = True
        return self._accepted

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def __exit__(self, *_: object) -> None:
        self.close()
