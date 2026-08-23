from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import urllib.request

import pytest

from infra.sp500_megarun.catalog_bootstrap_contract import (
    load_catalog_bootstrap_manifests,
)
from infra.sp500_megarun.catalog_bootstrap_manifest import (
    GitHubManifestConversion,
    ManifestLoopbackServer,
    accept_manifest_callback,
    exchange_manifest_code,
    start_manifest_session,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def test_callback_is_loopback_state_bound_and_one_use() -> None:
    session = start_manifest_session("requester", now=NOW)
    assert session.bind_host == "127.0.0.1"
    assert session.callback_path == "/github/manifest/callback"
    with pytest.raises(ValueError, match="STATE_MISMATCH"):
        accept_manifest_callback(
            session,
            {"code": "c" * 24, "state": "bad"},
            NOW,
        )
    accepted = accept_manifest_callback(
        session,
        {"code": "c" * 24, "state": session.state},
        NOW,
    )
    with pytest.raises(ValueError, match="CALLBACK_REPLAY"):
        accept_manifest_callback(accepted.session, accepted.query, NOW)


def test_callback_rejects_expiry_unknown_fields_and_non_loopback_host() -> None:
    session = start_manifest_session("auditor", now=NOW)
    query = {"code": "c" * 24, "state": session.state}
    with pytest.raises(ValueError, match="CALLBACK_EXPIRED"):
        accept_manifest_callback(session, query, NOW + timedelta(hours=1, seconds=1))
    with pytest.raises(ValueError, match="CALLBACK_QUERY_INVALID"):
        accept_manifest_callback(session, {**query, "extra": "x"}, NOW)
    with pytest.raises(ValueError, match="CALLBACK_HOST_INVALID"):
        accept_manifest_callback(session, query, NOW, host="localhost")


def test_conversion_repr_never_contains_private_material() -> None:
    value = GitHubManifestConversion(
        app_id=123,
        slug="aurora-catalog-requester",
        private_key_pem=bytearray(b"PRIVATE-MARKER"),
        client_secret=bytearray(b"CLIENT-MARKER"),
        webhook_secret=bytearray(b"WEBHOOK-MARKER"),
    )
    rendered = repr(value)
    assert "PRIVATE-MARKER" not in rendered
    assert "CLIENT-MARKER" not in rendered
    assert "WEBHOOK-MARKER" not in rendered
    value.clear()
    assert not any(value.private_key_pem)
    assert not any(value.client_secret)
    assert not any(value.webhook_secret)


class _Response:
    status_code = 201

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "id": 123,
            "slug": "aurora-catalog-requester",
            "pem": "PRIVATE-MARKER",
            "client_secret": "CLIENT-MARKER",
            "webhook_secret": "WEBHOOK-MARKER",
        }


class _Http:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return _Response()


def test_exchange_uses_only_manifest_conversion_endpoint() -> None:
    http = _Http()
    conversion = exchange_manifest_code("c" * 24, http=http)
    assert http.calls == [
        (
            "https://api.github.com/app-manifests/cccccccccccccccccccccccc/conversions",
            {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                "timeout": (5, 20),
            },
        )
    ]
    assert conversion.app_id == 123
    assert conversion.private_key_pem == bytearray(b"PRIVATE-MARKER")


def test_exchange_rejects_malformed_or_oversized_code() -> None:
    for code in ("short", "a/b" * 12, "a" * 257):
        with pytest.raises(ValueError, match="MANIFEST_CODE_INVALID"):
            exchange_manifest_code(code, http=_Http())


def test_bootstrap_dependencies_are_exact_and_hash_locked() -> None:
    direct = (
        ROOT / "requirements/catalog-bootstrap.in"
    ).read_text("utf-8").splitlines()
    assert direct == [
        "cryptography==50.0.0",
        "pydantic==2.13.4",
        "requests==2.34.2",
    ]
    lock = (ROOT / "requirements/catalog-bootstrap-win-py314.lock").read_text(
        "utf-8"
    )
    packages = set(re.findall(r"(?m)^([a-z0-9][a-z0-9._-]*)==", lock))
    assert {"cryptography", "pydantic", "requests"} <= packages
    assert "pytest" not in packages
    assert not packages & {"playwright", "selenium", "pyautogui"}
    assert not re.search(r"(?im)(?:^|\s)(?:-e |--editable|https?://|git\+|--extra-index)", lock)
    blocks = re.split(r"(?m)(?=^[a-z0-9][a-z0-9._-]*==)", lock)
    assert all("--hash=sha256:" in block for block in blocks if "==" in block)


def test_loopback_server_serves_one_closed_manifest_and_callback() -> None:
    manifests = load_catalog_bootstrap_manifests(
        ROOT / "config/catalog_bootstrap_app_manifests_v1.json"
    )
    session = start_manifest_session("requester", now=NOW)
    with ManifestLoopbackServer(
        session,
        manifests.requester,
        clock=lambda: NOW,
    ) as server:
        with urllib.request.urlopen(server.start_url, timeout=3) as response:
            page = response.read().decode("utf-8")
            assert response.headers["Cache-Control"] == "no-store"
        assert "https://github.com/organizations/trading-optimizer-lab-org/settings/apps/new" in page
        assert "AURORA Catalog Requester f10c7b40e1" in page
        callback = (
            f"{server.callback_url}?code={'c' * 24}&state={session.state}"
        )
        with urllib.request.urlopen(callback, timeout=3) as response:
            assert response.status == 200
        accepted = server.wait(now=NOW, timeout_seconds=1)
        assert accepted.query["code"] == "c" * 24
        with pytest.raises(ValueError, match="CALLBACK_REPLAY"):
            server.wait(now=NOW, timeout_seconds=1)
