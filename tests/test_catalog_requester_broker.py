from __future__ import annotations

from base64 import b64decode
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from uuid import RFC_4122, UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
import requests

from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_requester import (
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterProductionSealV1,
    CatalogRequesterReconcileHintV1,
    CatalogRequesterReceiptV1,
    build_registered_catalog_draft,
    submit_registered_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_requester_broker import (
    CatalogBrokerGithubClient,
    CatalogBrokerBootstrapSealV1,
    CatalogBrokerHttpResponse,
    CatalogBrokerProcessingRecordV1,
    CatalogBrokerTicketJournalV1,
    CatalogRequesterBrokerConfigV1,
    RequestsCatalogBrokerHttpTransport,
    advance_catalog_ticket_after_verified_terminal,
    claim_next_catalog_reconcile_hint,
    ensure_catalog_launch_tickets,
    claim_next_catalog_request,
    inventory_catalog_broker_inbox,
    load_claimed_catalog_draft,
    load_or_create_signed_processing_record,
    load_or_create_post_attempt,
    process_claimed_catalog_request,
    process_claimed_catalog_reconcile_hint,
    persist_catalog_requester_receipt,
    publish_catalog_broker_self_audit,
    publish_catalog_broker_capacity,
    quarantine_one_invalid_catalog_broker_entry,
    quarantine_invalid_claimed_catalog_request,
    reconcile_catalog_request_to_github,
    reconcile_active_catalog_campaign,
    reconstruct_catalog_campaign_journal_from_github,
    sign_catalog_request,
    submit_catalog_request_to_github,
)
from aurora.infra.sp500_megarun.catalog_run_request import (
    parse_catalog_run_request,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"


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


def _draft() -> CatalogRunIntentDraftV1:
    return CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        launch_ticket_sha256="1" * 64,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256="2" * 64,
        prompt_sha256="3" * 64,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )


@pytest.mark.parametrize(
    ("state", "submission_key_sha256", "request_sha256", "issue_number"),
    (
        ("available", None, "4" * 64, None),
        ("available", None, None, 77),
        ("consumed", "5" * 64, "4" * 64, None),
        ("consumed", "5" * 64, None, 77),
    ),
)
def test_non_active_ticket_journal_rejects_partial_github_identity(
    state: str,
    submission_key_sha256: str | None,
    request_sha256: str | None,
    issue_number: int | None,
) -> None:
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256="2" * 64,
        prompt_sha256="3" * 64,
        previous_terminal_request_sha256=None,
    )
    unsigned = CatalogBrokerTicketJournalV1.model_construct(
        schema_version="1",
        campaign_key=ticket.campaign_key,
        launch_generation=ticket.launch_generation,
        ticket=ticket,
        state=state,
        submission_key_sha256=submission_key_sha256,
        request_sha256=request_sha256,
        issue_number=issue_number,
        created_at=NOW,
        updated_at=NOW,
        journal_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="REQUESTER_TICKET_JOURNAL_INVALID"):
        CatalogBrokerTicketJournalV1.model_validate(
            unsigned.model_copy(
                update={"journal_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


def _config() -> CatalogRequesterBrokerConfigV1:
    return CatalogRequesterBrokerConfigV1.model_validate_json(
        (ROOT / "config/catalog_requester_v1.json").read_bytes()
    )


class _FakeHttp:
    def __init__(
        self,
        *,
        overprivileged: bool = False,
        uncertain_post: bool = False,
        issue_created_at: str = "2026-08-22T12:00:01Z",
    ):
        self.calls: list[tuple[str, str]] = []
        self.overprivileged = overprivileged
        self.uncertain_post = uncertain_post
        self.issue_created_at = issue_created_at
        self.issue_posts = 0
        self.created_title: str | None = None
        self.created_body: str | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        del headers
        self.calls.append((method, url))
        if url.endswith("/app/installations/123/access_tokens"):
            permissions = {"issues": "write", "metadata": "read"}
            if self.overprivileged:
                permissions["contents"] = "write"
            return CatalogBrokerHttpResponse(
                status_code=201,
                headers={},
                json_body={
                    "token": "opaque-installation-token",
                    "permissions": permissions,
                    "repositories": [{"full_name": "trading-optimizer-lab-org/aurora"}],
                },
            )
        if url.endswith("/repos/trading-optimizer-lab-org/aurora/issues") and method == "POST":
            self.issue_posts += 1
            assert json_body is not None
            self.created_title = str(json_body["title"])
            self.created_body = str(json_body["body"])
            if self.uncertain_post:
                raise TimeoutError("response lost after accept")
            return CatalogBrokerHttpResponse(
                status_code=201,
                headers={},
                json_body={"number": 77},
            )
        if url.endswith("/repos/trading-optimizer-lab-org/aurora/issues/77"):
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={},
                json_body={
                    "number": 77,
                    "title": self.created_title,
                    "body": self.created_body,
                    "state": "open",
                    "user": {"login": "aurora-catalog-requester[bot]"},
                    "created_at": self.issue_created_at,
                    "updated_at": self.issue_created_at,
                    "html_url": "https://github.com/trading-optimizer-lab-org/aurora/issues/77",
                },
            )
        if "/issues?" in url:
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={},
                json_body=[
                    {
                        "number": 77,
                        "title": self.created_title,
                        "body": self.created_body,
                        "state": "open",
                        "user": {"login": "aurora-catalog-requester[bot]"},
                        "created_at": self.issue_created_at,
                        "updated_at": self.issue_created_at,
                        "html_url": "https://github.com/trading-optimizer-lab-org/aurora/issues/77",
                    }
                ],
            )
        raise AssertionError((method, url, json_body))


def _client(fake: _FakeHttp, key: rsa.RSAPrivateKey) -> CatalogBrokerGithubClient:
    clock_reads = 0

    def advancing_clock() -> datetime:
        nonlocal clock_reads
        clock_reads += 1
        return NOW if clock_reads <= 2 else NOW + timedelta(seconds=5)

    return CatalogBrokerGithubClient(
        config=_config(),
        http=fake,
        app_id=42,
        installation_id=123,
        private_key_pem=_private_pem(key),
        expected_actor="aurora-catalog-requester[bot]",
        now=advancing_clock,
    )


def test_broker_signs_exact_title_and_body_before_any_post() -> None:
    key = _private_key()
    signed = sign_catalog_request(
        draft=_draft(),
        private_key_pem=_private_pem(key),
    )
    parsed = parse_catalog_run_request(
        signed.title,
        signed.body,
        trusted_public_key=_public_pem(key),
    )
    assert parsed.intent_sha256 == signed.intent_sha256
    assert parsed.request_sha256 == signed.request_sha256
    assert signed.processing_bytes == (
        json.dumps(
            signed.processing_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def test_github_second_precision_cannot_reject_a_valid_same_second_issue() -> None:
    key = _private_key()
    signed = sign_catalog_request(
        draft=_draft(),
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    fake = _FakeHttp(issue_created_at="2026-08-22T12:00:00Z")

    receipt = submit_catalog_request_to_github(
        signed=signed,
        client=_client(fake, key),
        post_lower_bound=NOW + timedelta(microseconds=900_000),
        post_upper_bound=NOW + timedelta(seconds=5, microseconds=100_000),
        installation_token="opaque-installation-token",
    )

    assert receipt.issue_number == 77
    assert fake.issue_posts == 1


def test_broker_uses_only_token_issue_post_and_exact_readback() -> None:
    key = _private_key()
    fake = _FakeHttp()
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    result = submit_catalog_request_to_github(
        signed=signed,
        client=_client(fake, key),
        post_lower_bound=NOW,
        post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
    )
    assert result.status == "submitted"
    assert result.issue_number == 77
    assert fake.calls == [
        (
            "POST",
            "https://api.github.com/app/installations/123/access_tokens",
        ),
        (
            "POST",
            "https://api.github.com/repos/trading-optimizer-lab-org/aurora/issues",
        ),
        (
            "GET",
            "https://api.github.com/repos/trading-optimizer-lab-org/aurora/issues/77",
        ),
    ]


def test_broker_rejects_overprivileged_installation_before_issue_post() -> None:
    key = _private_key()
    fake = _FakeHttp(overprivileged=True)
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    with pytest.raises(ValueError, match="REQUESTER_APP_OVERPRIVILEGED"):
        submit_catalog_request_to_github(
            signed=signed,
            client=_client(fake, key),
            post_lower_bound=NOW,
            post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
        )
    assert fake.issue_posts == 0


def test_uncertain_post_reconciles_before_any_retry() -> None:
    key = _private_key()
    fake = _FakeHttp(uncertain_post=True)
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    result = submit_catalog_request_to_github(
        signed=signed,
        client=_client(fake, key),
        post_lower_bound=NOW,
        post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
    )
    assert result.status == "submitted"
    assert result.issue_number == 77
    assert fake.issue_posts == 1
    assert sum(method == "POST" and url.endswith("/issues") for method, url in fake.calls) == 1


def test_complete_reconciliation_without_a_visible_issue_stays_retryable() -> None:
    class EmptyHistoryHttp(_FakeHttp):
        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json_body: dict[str, object] | None = None,
        ) -> CatalogBrokerHttpResponse:
            if "/issues?" in url:
                del headers, json_body
                self.calls.append((method, url))
                return CatalogBrokerHttpResponse(
                    status_code=200,
                    headers={},
                    json_body=[],
                )
            return super().request(
                method,
                url,
                headers=headers,
                json_body=json_body,
            )

    key = _private_key()
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    fake = EmptyHistoryHttp()

    with pytest.raises(
        ValueError,
        match="REQUESTER_POST_RECONCILIATION_RETRYABLE",
    ):
        reconcile_catalog_request_to_github(
            signed=signed,
            client=_client(fake, key),
            post_lower_bound=NOW,
            post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
            installation_token="opaque",
        )

    assert all(not (method == "POST" and url.endswith("/issues")) for method, url in fake.calls)


def test_processing_record_never_contains_key_token_or_jwt() -> None:
    key = _private_key()
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    record = CatalogBrokerProcessingRecordV1.model_validate(signed.processing_payload)
    encoded = record.model_dump_json()
    assert "PRIVATE KEY" not in encoded
    assert "opaque-installation-token" not in encoded
    assert not hasattr(record, "token")
    assert b64decode(record.request.requester_attestation_b64)


def test_broker_self_audit_is_secret_free_and_never_claims_unsealed_ready(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    (root / "config/production-enabled-v1.seal.json").unlink()
    key = _private_key()
    receipt = publish_catalog_broker_self_audit(
        broker_root=root,
        config=_config(),
        client=_client(_FakeHttp(), key),
        broker_application_sha256="a" * 64,
        acl_baseline_sha256="b" * 64,
        observed_at=NOW,
    )
    stored = (root / "receipts/broker-self-audit-v1.receipt.json").read_text(
        encoding="utf-8"
    )
    assert receipt.status == "qualification_only"
    assert receipt.production_seal_present is False
    assert receipt.requester_public_key_sha256 == (
        _client(_FakeHttp(), key).requester_public_key_sha256
    )
    assert "PRIVATE KEY" not in stored
    assert "opaque-installation-token" not in stored


def test_closed_http_state_machine_rejects_patch_delete_and_comments() -> None:
    key = _private_key()
    fake = _FakeHttp()
    client = _client(fake, key)
    for method, path in (
        ("PATCH", "/repos/trading-optimizer-lab-org/aurora/issues/1"),
        ("DELETE", "/repos/trading-optimizer-lab-org/aurora/issues/1"),
        ("POST", "/repos/trading-optimizer-lab-org/aurora/issues/1/comments"),
        ("POST", "/repos/trading-optimizer-lab-org/aurora/actions/workflows/x/dispatches"),
    ):
        with pytest.raises(ValueError, match="REQUESTER_GITHUB_ENDPOINT_FORBIDDEN"):
            client.request_fixed(method, path, token="opaque", json_body={})
    assert fake.calls == []


def test_requests_transport_ignores_environment_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 200
        headers = {"X-Test": "ok"}

        @staticmethod
        def json() -> dict[str, bool]:
            return {"ok": True}

    class FakeSession:
        def __init__(self) -> None:
            self.trust_env = True
            self.verify = False
            self.calls: list[dict[str, object]] = []

        def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return FakeResponse()

    fake = FakeSession()
    monkeypatch.setattr(
        "aurora.infra.sp500_megarun.catalog_requester_broker.requests.Session",
        lambda: fake,
    )
    transport = RequestsCatalogBrokerHttpTransport(timeout_seconds=30)
    response = transport.request(
        "GET",
        "https://api.github.com/fixed",
        headers={"Authorization": "Bearer opaque"},
    )
    assert response.status_code == 200
    assert fake.trust_env is False
    assert fake.verify is True
    assert fake.calls[0]["allow_redirects"] is False
    assert fake.calls[0]["timeout"] == (5, 30)


@pytest.mark.parametrize("failure", [503, requests.exceptions.ConnectionError("offline")])
def test_requests_transport_classifies_only_network_or_retryable_http_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: int | Exception,
) -> None:
    class FakeResponse:
        status_code = failure if isinstance(failure, int) else 200
        headers: dict[str, str] = {}

        @staticmethod
        def json() -> dict[str, bool]:
            return {"ok": True}

    class FakeSession:
        trust_env = True
        verify = False

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> FakeResponse:
            if isinstance(failure, Exception):
                raise failure
            return FakeResponse()

    monkeypatch.setattr(
        "aurora.infra.sp500_megarun.catalog_requester_broker.requests.Session",
        FakeSession,
    )
    transport = RequestsCatalogBrokerHttpTransport(timeout_seconds=30)

    with pytest.raises(ValueError, match="REQUESTER_GITHUB_TRANSIENT_FAILURE"):
        transport.request(
            "GET",
            "https://api.github.com/fixed",
            headers={"Authorization": "Bearer opaque"},
        )


@pytest.mark.parametrize(
    "headers",
    (
        {"Retry-After": "60"},
        {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1787400060"},
    ),
)
def test_requests_transport_retries_only_explicit_403_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    class FakeResponse:
        status_code = 403

        @staticmethod
        def json() -> dict[str, str]:
            return {"message": "rate limited"}

    response = FakeResponse()
    response.headers = headers

    class FakeSession:
        trust_env = True
        verify = False

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> FakeResponse:
            return response

    monkeypatch.setattr(
        "aurora.infra.sp500_megarun.catalog_requester_broker.requests.Session",
        FakeSession,
    )
    transport = RequestsCatalogBrokerHttpTransport(timeout_seconds=30)

    with pytest.raises(ValueError, match="REQUESTER_GITHUB_TRANSIENT_FAILURE"):
        transport.request(
            "GET",
            "https://api.github.com/fixed",
            headers={"Authorization": "Bearer opaque"},
        )


def test_requests_transport_preserves_github_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 429
        headers = {"Retry-After": "180"}

        @staticmethod
        def json() -> dict[str, str]:
            return {"message": "rate limited"}

    class FakeSession:
        trust_env = True
        verify = False

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        "aurora.infra.sp500_megarun.catalog_requester_broker.requests.Session",
        FakeSession,
    )
    transport = RequestsCatalogBrokerHttpTransport(timeout_seconds=30)

    with pytest.raises(ValueError, match="REQUESTER_GITHUB_TRANSIENT_FAILURE") as caught:
        transport.request(
            "GET",
            "https://api.github.com/fixed",
            headers={"Authorization": "Bearer opaque"},
        )

    assert getattr(caught.value, "retry_after_seconds", None) == 180


class _PaginatedUncertainHttp(_FakeHttp):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        if "/issues?" not in url:
            return super().request(
                method,
                url,
                headers=headers,
                json_body=json_body,
            )
        del headers, json_body
        self.calls.append((method, url))
        common = {
            "state": "open",
            "user": {"login": "aurora-catalog-requester[bot]"},
            "created_at": "2026-08-22T12:00:02Z",
            "updated_at": "2026-08-22T12:00:02Z",
        }
        if "&page=2" not in url:
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={
                    "Link": (
                        "<https://api.github.com/repos/trading-optimizer-lab-org/"
                        "aurora/issues?state=all&sort=created&direction=desc&"
                        'per_page=100&page=2>; rel="next"'
                    )
                },
                json_body=[
                    {
                        **common,
                        "number": 1_000 - index,
                        "title": f"newer-{index}",
                        "body": "unrelated",
                        "html_url": (
                            "https://github.com/trading-optimizer-lab-org/aurora/"
                            f"issues/{1_000 - index}"
                        ),
                    }
                    for index in range(100)
                ],
            )
        later = [
            {
                **common,
                "number": 900 - index,
                "title": f"newer-later-{index}",
                "body": "unrelated",
                "html_url": (
                    "https://github.com/trading-optimizer-lab-org/aurora/"
                    f"issues/{900 - index}"
                ),
            }
            for index in range(37)
        ]
        later.append(
            {
                "number": 77,
                "title": self.created_title,
                "body": self.created_body,
                "state": "open",
                "user": {"login": "aurora-catalog-requester[bot]"},
                "created_at": "2026-08-22T12:00:01Z",
                "updated_at": "2026-08-22T12:00:01Z",
                "html_url": (
                    "https://github.com/trading-optimizer-lab-org/aurora/issues/77"
                ),
            }
        )
        return CatalogBrokerHttpResponse(
            status_code=200,
            headers={},
            json_body=later,
        )


def test_uncertain_post_finds_exact_request_after_137_newer_issues() -> None:
    key = _private_key()
    fake = _PaginatedUncertainHttp(uncertain_post=True)
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    result = submit_catalog_request_to_github(
        signed=signed,
        client=_client(fake, key),
        post_lower_bound=NOW,
        post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
    )
    assert result.status == "submitted"
    assert result.issue_number == 77
    assert fake.issue_posts == 1
    listing_calls = [url for method, url in fake.calls if method == "GET" and "?" in url]
    assert len(listing_calls) == 2


class _ForeignPaginationHttp(_FakeHttp):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        if "/issues?" in url:
            del headers, json_body
            self.calls.append((method, url))
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={"Link": '<https://evil.invalid/issues?page=2>; rel="next"'},
                json_body=[],
            )
        return super().request(
            method,
            url,
            headers=headers,
            json_body=json_body,
        )


def test_uncertain_post_rejects_foreign_pagination_without_retry() -> None:
    key = _private_key()
    fake = _ForeignPaginationHttp(uncertain_post=True)
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))
    with pytest.raises(ValueError, match="REQUESTER_POST_RECONCILIATION_PENDING"):
        submit_catalog_request_to_github(
            signed=signed,
            client=_client(fake, key),
            post_lower_bound=NOW,
            post_upper_bound=datetime(2026, 8, 22, 12, 0, 5, tzinfo=UTC),
        )
    assert fake.issue_posts == 1


def test_uncertain_post_rejects_a_same_origin_page_skip() -> None:
    class SkippedPageHttp(_FakeHttp):
        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json_body: dict[str, object] | None = None,
        ) -> CatalogBrokerHttpResponse:
            if "/issues?" not in url:
                return super().request(
                    method,
                    url,
                    headers=headers,
                    json_body=json_body,
                )
            self.calls.append((method, url))
            common = {
                "state": "open",
                "user": {"login": "aurora-catalog-requester[bot]"},
                "created_at": "2026-08-22T12:00:02Z",
                "updated_at": "2026-08-22T12:00:02Z",
            }
            if "&page=3" not in url:
                return CatalogBrokerHttpResponse(
                    status_code=200,
                    headers={
                        "Link": (
                            "<https://api.github.com/repos/"
                            "trading-optimizer-lab-org/aurora/issues?state=all&"
                            "sort=created&direction=desc&per_page=100&page=3>; "
                            'rel="next"'
                        )
                    },
                    json_body=[
                        {
                            **common,
                            "number": 1_000 - index,
                            "title": f"unrelated-{index}",
                            "body": "unrelated",
                        }
                        for index in range(100)
                    ],
                )
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={},
                json_body=[
                    {
                        **common,
                        "number": 77,
                        "title": self.created_title,
                        "body": self.created_body,
                        "html_url": (
                            "https://github.com/trading-optimizer-lab-org/aurora/"
                            "issues/77"
                        ),
                    }
                ],
            )

    key = _private_key()
    fake = SkippedPageHttp(uncertain_post=True)
    signed = sign_catalog_request(draft=_draft(), private_key_pem=_private_pem(key))

    with pytest.raises(ValueError, match="REQUESTER_POST_RECONCILIATION_PENDING"):
        submit_catalog_request_to_github(
            signed=signed,
            client=_client(fake, key),
            post_lower_bound=NOW,
            post_upper_bound=NOW + timedelta(seconds=5),
        )
    assert fake.issue_posts == 1


def _broker_root(tmp_path: Path) -> Path:
    root = tmp_path / "broker"
    for relative in ("inbox", "processing", "receipts"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def test_broker_inventory_is_bounded_and_capacity_receipt_is_canonical(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    empty = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert empty.available is True
    receipt = publish_catalog_broker_capacity(
        broker_root=root,
        config=config,
        observed_at=NOW,
    )
    stored = (root / "receipts/broker-capacity-v1.receipt.json").read_bytes()
    assert stored == (
        json.dumps(
            receipt.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    for index in range(33):
        (root / "inbox" / f"{index:064x}.request.json").write_bytes(b"{}\n")
    full = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert full.available is False
    assert full.reason_code == "REQUEST_BROKER_CAPACITY_EXCEEDED"
    assert full.pending_entry_count == 33


def test_atomic_service_state_recovers_an_interrupted_temporary_write(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    target = tmp_path / "campaign.status.json"
    target.write_bytes(b"old\n")
    temporary = tmp_path / "campaign.status.json.service-tmp"
    temporary.write_bytes(b"partial")

    broker_module._atomic_replace(target, b"new\n")

    assert target.read_bytes() == b"new\n"
    assert not temporary.exists()
    abandoned = tuple(tmp_path.glob("campaign.status.json.abandoned-*.service-state"))
    assert len(abandoned) == 1
    assert abandoned[0].read_bytes() == b"partial"


def test_final_receipt_becomes_visible_only_after_its_bytes_are_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    draft = _draft()
    receipt = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=draft.launch_generation,
        issue_number=77,
        request_sha256="9" * 64,
        observed_at=NOW,
    )
    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    original_replace = broker_module.os.replace
    receipt_replace_seen = False

    def checked_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal receipt_replace_seen
        destination_path = Path(destination)
        if destination_path.name.endswith(".receipt.json"):
            receipt_replace_seen = True
            assert not destination_path.exists()
            assert Path(source).read_bytes() == canonical_model_bytes(receipt) + b"\n"
        original_replace(source, destination)

    monkeypatch.setattr(broker_module.os, "replace", checked_replace)
    persisted = persist_catalog_requester_receipt(
        broker_root=root,
        config=config,
        receipt=receipt,
    )
    assert persisted == receipt
    assert receipt_replace_seen is True


def test_broker_claims_only_one_regular_single_link_canonical_request(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    draft = _draft()
    request_path = root / "inbox" / f"{draft.submission_key_sha256}.request.json"
    request_path.write_bytes(
        json.dumps(
            draft.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    inventory = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert inventory.available is True, (request_path.stat().st_nlink, inventory)
    claimed = claim_next_catalog_request(broker_root=root, config=config)
    assert claimed == root / "processing" / request_path.name
    assert not request_path.exists()
    assert load_claimed_catalog_draft(claimed_path=claimed, config=config) == draft
    assert claim_next_catalog_request(broker_root=root, config=config) == claimed


def test_broker_rejects_hard_link_and_oversized_request_without_reading(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    oversized = root / "inbox" / f"{'a' * 64}.request.json"
    oversized.write_bytes(b"x" * 4_097)
    inventory = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert inventory.available is False
    assert inventory.reason_code == "REQUEST_BROKER_CAPACITY_UNPROVEN"
    assert claim_next_catalog_request(broker_root=root, config=config) is None
    quarantined = quarantine_one_invalid_catalog_broker_entry(
        broker_root=root,
        config=config,
    )
    assert quarantined is not None and quarantined.parent == root / "processing"
    assert not oversized.exists()
    assert inventory_catalog_broker_inbox(
        broker_root=root, config=config
    ).available is True

    original = root / "inbox" / f"{'b' * 64}.request.json"
    linked = root / "inbox" / f"{'c' * 64}.request.json"
    original.write_bytes(b"{}\n")
    try:
        os.link(original, linked)
    except OSError:
        pytest.skip("hard links unavailable on this filesystem")
    inventory = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert inventory.available is False
    assert all(entry.single_link is False for entry in inventory.entries)
    assert claim_next_catalog_request(broker_root=root, config=config) is None
    assert quarantine_one_invalid_catalog_broker_entry(
        broker_root=root, config=config
    ) is not None
    assert quarantine_one_invalid_catalog_broker_entry(
        broker_root=root, config=config
    ) is not None
    assert inventory_catalog_broker_inbox(
        broker_root=root, config=config
    ).available is True


def test_overflowing_unknown_entries_are_drained_without_replay_deadlock(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    for index in range(33):
        (root / "inbox" / f"unknown-{index:02d}.entry").write_bytes(b"x")

    inventory = inventory_catalog_broker_inbox(broker_root=root, config=config)
    assert inventory.reason_code == "REQUEST_BROKER_CAPACITY_EXCEEDED"
    first = quarantine_one_invalid_catalog_broker_entry(
        broker_root=root,
        config=config,
    )
    assert first is not None
    assert len(tuple((root / "inbox").iterdir())) == 32

    replay_name = "unknown-00.entry"
    (root / "inbox" / replay_name).write_bytes(b"x")
    second = quarantine_one_invalid_catalog_broker_entry(
        broker_root=root,
        config=config,
    )
    assert second is not None
    assert second != first


def test_invalid_entry_scan_is_strictly_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    for index in range(100):
        (root / "inbox" / f"{index:064x}.request.json").write_bytes(b"{}\n")

    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    original_lstat = broker_module.os.lstat
    calls = 0

    def counted_lstat(path: str | bytes | os.PathLike[str]) -> os.stat_result:
        nonlocal calls
        calls += 1
        return original_lstat(path)

    monkeypatch.setattr(broker_module.os, "lstat", counted_lstat)
    assert quarantine_one_invalid_catalog_broker_entry(
        broker_root=root,
        config=config,
    ) is None
    assert calls <= config.broker.maximum_pending_entries


def test_uuid7_fallback_is_rfc4122_and_uses_current_utc_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    monkeypatch.delattr(broker_module.uuid, "uuid7", raising=False)
    before_ms = time.time_ns() // 1_000_000
    first = broker_module._new_launch_ticket(
        campaign_key="sp500-optimized-catalog-v1",
        campaign_definition_sha256="2" * 64,
        prompt_sha256="3" * 64,
    )
    second = broker_module._new_launch_ticket(
        campaign_key="sp500-optimized-catalog-v1",
        campaign_definition_sha256="2" * 64,
        prompt_sha256="3" * 64,
    )
    after_ms = time.time_ns() // 1_000_000

    first_uuid = UUID(first.request_id)
    second_uuid = UUID(second.request_id)
    for parsed in (first_uuid, second_uuid):
        assert parsed.version == 7
        assert parsed.variant == RFC_4122
        assert before_ms <= parsed.int >> 80 <= after_ms
        assert (parsed.int >> 76) & 0xF == 0x7
        assert (parsed.int >> 62) & 0x3 == 0b10
    assert first.request_id != second.request_id


def test_restart_reuses_exact_persisted_signature_without_resigning(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    config = _config()
    key = _private_key()
    first = load_or_create_signed_processing_record(
        broker_root=root,
        config=config,
        draft=_draft(),
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    path = root / "processing" / f"{_draft().submission_key_sha256}.signed.json"
    exact_bytes = path.read_bytes()
    second = load_or_create_signed_processing_record(
        broker_root=root,
        config=config,
        draft=_draft(),
        private_key_pem=_private_pem(_private_key()),
        signed_at=datetime(2026, 8, 22, 12, 5, tzinfo=UTC),
    )
    assert second == first
    assert path.read_bytes() == exact_bytes == first.processing_bytes


def _installed_broker_tree(tmp_path: Path) -> Path:
    root = tmp_path / "installed-broker"
    for directory in (
        "config/catalog_campaign_definitions",
        "docs/runbooks",
        "inbox",
        "processing",
        "receipts",
        "launch-tickets",
        "campaign-status",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for relative in (
        "config/catalog_requester_v1.json",
        "config/catalog_campaign_registry_v1.json",
        "config/catalog_run_prompt_policy_v1.json",
        "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json",
        "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    ):
        shutil.copyfile(ROOT / relative, root / relative)
    bootstrap_key = _private_key()
    qualification_tickets = ensure_catalog_launch_tickets(
        broker_root=root,
        config=_config(),
        observed_at=NOW,
        client=_client(_HistoryHttp([]), bootstrap_key),
    )
    assert len(qualification_tickets) == 1
    _, qualification_draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key="controller-bootstrap-qualification-v1",
    )
    request_path = (
        root
        / "inbox"
        / f"{qualification_draft.submission_key_sha256}.request.json"
    )
    request_path.write_bytes(canonical_model_bytes(qualification_draft) + b"\n")
    claimed = claim_next_catalog_request(broker_root=root, config=_config())
    assert claimed is not None
    qualification_receipt = process_claimed_catalog_request(
        broker_root=root,
        config=_config(),
        claimed_path=claimed,
        private_key_pem=_private_pem(bootstrap_key),
        client=_client(_FakeHttp(), bootstrap_key),
        observed_at=NOW,
    )
    qualification_signed = CatalogBrokerProcessingRecordV1.model_validate_json(
        (
            root
            / "processing"
            / f"{qualification_draft.submission_key_sha256}.signed.json"
        ).read_bytes()
    )
    assert advance_catalog_ticket_after_verified_terminal(
        broker_root=root,
        config=_config(),
        signed=qualification_signed,
        issue=_terminal_issue(qualification_signed),
        expected_requester_actor="aurora-catalog-requester[bot]",
        observed_at=datetime(2026, 8, 22, 12, 5, tzinfo=UTC),
    ) is None
    bootstrap_seal = CatalogBrokerBootstrapSealV1.create(
        qualification_submission_key_sha256=(
            qualification_receipt.submission_key_sha256
        ),
        qualification_request_sha256=qualification_receipt.request_sha256
        or "0" * 64,
        qualification_issue_number=qualification_receipt.issue_number or 0,
        controller_receipt_sha256="7" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
    )
    (root / "config/bootstrap-qualified-v1.seal.json").write_bytes(
        canonical_model_bytes(bootstrap_seal) + b"\n"
    )
    final_bootstrap_receipt = b'{"result":"READY","schema_version":"1"}\n'
    (root / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(
        final_bootstrap_receipt
    )
    seal = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="1" * 40,
        bootstrap_receipt_sha256=hashlib.sha256(
            final_bootstrap_receipt
        ).hexdigest(),
        requester_client_application_sha256="3" * 64,
        requester_broker_application_sha256="4" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 7, tzinfo=UTC),
    )
    (root / "config/production-enabled-v1.seal.json").write_bytes(
        canonical_model_bytes(seal) + b"\n"
    )
    tickets = ensure_catalog_launch_tickets(
        broker_root=root,
        config=_config(),
        observed_at=NOW,
        client=_client(_HistoryHttp([]), bootstrap_key),
    )
    assert len(tickets) == 1
    return root


def test_production_requires_the_exact_final_bootstrap_receipt(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    receipt_path = root / "receipts/controller-bootstrap-v1.receipt.json"
    receipt_path.write_bytes(b'{"result":"BLOCKED","schema_version":"1"}\n')

    with pytest.raises(
        ValueError,
        match="REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID",
    ):
        build_registered_catalog_draft(
            broker_root=root,
            campaign_key="sp500-optimized-catalog-v1",
        )
    with pytest.raises(
        ValueError,
        match="REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID",
    ):
        ensure_catalog_launch_tickets(
            broker_root=root,
            config=_config(),
            observed_at=NOW,
            client=_client(_HistoryHttp([]), _private_key()),
        )


def test_matching_blocked_bootstrap_receipt_cannot_enable_production(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    blocked = b'{"result":"BLOCKED","schema_version":"1"}\n'
    (root / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(blocked)
    seal = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="1" * 40,
        bootstrap_receipt_sha256=hashlib.sha256(blocked).hexdigest(),
        requester_client_application_sha256="3" * 64,
        requester_broker_application_sha256="4" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 7, tzinfo=UTC),
    )
    (root / "config/production-enabled-v1.seal.json").write_bytes(
        canonical_model_bytes(seal) + b"\n"
    )

    with pytest.raises(
        ValueError,
        match="REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID",
    ):
        build_registered_catalog_draft(
            broker_root=root,
            campaign_key="sp500-optimized-catalog-v1",
        )


def test_sealed_qualification_retires_a_poll_left_by_a_crash(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    current = (
        root
        / "campaign-status/controller-bootstrap-qualification-v1.terminal-poll.json"
    )
    archived = (
        root
        / "campaign-status/controller-bootstrap-qualification-v1."
        "generation-0000000001.terminal-poll.json"
    )

    assert not current.exists()
    assert archived.exists()


def test_broker_self_audit_never_calls_an_unbound_seal_production_ready(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    (root / "receipts/controller-bootstrap-v1.receipt.json").unlink()

    with pytest.raises(
        ValueError,
        match="REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID",
    ):
        publish_catalog_broker_self_audit(
            broker_root=root,
            config=_config(),
            client=_client(_FakeHttp(), _private_key()),
            broker_application_sha256="4" * 64,
            acl_baseline_sha256="b" * 64,
            observed_at=NOW,
        )


def _claim_installed_draft(root: Path) -> tuple[CatalogRunIntentDraftV1, Path]:
    config = _config()
    _, draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key="sp500-optimized-catalog-v1",
    )
    path = root / "inbox" / f"{draft.submission_key_sha256}.request.json"
    path.write_bytes(canonical_model_bytes(draft) + b"\n")
    claimed = claim_next_catalog_request(broker_root=root, config=config)
    assert claimed is not None
    return draft, claimed


def test_full_claim_process_is_idempotent_after_receipt(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    key = _private_key()
    fake = _FakeHttp()
    client = _client(fake, key)
    first = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=client,
        observed_at=NOW,
    )
    calls_after_first = tuple(fake.calls)
    archived = root / "processing" / f"processed-{draft.submission_key_sha256}.request"
    os.rename(archived, claimed)
    second = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(_private_key()),
        client=client,
        observed_at=datetime(2026, 8, 22, 12, 10, tzinfo=UTC),
    )
    assert first == second
    assert first.submission_key_sha256 == draft.submission_key_sha256
    assert fake.issue_posts == 1
    assert tuple(fake.calls) == calls_after_first
    assert not claimed.exists()
    assert archived.is_file()
    assert not (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    ).exists()
    assert (
        root / "processing" / f"{draft.submission_key_sha256}.ticket.json"
    ).is_file()
    client_repeat = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key="sp500-optimized-catalog-v1",
        observed_at=datetime(2026, 8, 22, 12, 11, tzinfo=UTC),
    )
    assert client_repeat == first


def test_existing_receipt_must_match_the_complete_claimed_draft(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    conflicting = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key="different-campaign-v1",
        launch_generation=draft.launch_generation,
        issue_number=77,
        request_sha256="f" * 64,
        observed_at=NOW,
    )
    (
        root / "receipts" / f"{draft.submission_key_sha256}.receipt.json"
    ).write_bytes(canonical_model_bytes(conflicting) + b"\n")

    key = _private_key()
    with pytest.raises(ValueError, match="REQUESTER_RECEIPT_INVALID"):
        process_claimed_catalog_request(
            broker_root=root,
            config=config,
            claimed_path=claimed,
            private_key_pem=_private_pem(key),
            client=_client(_FakeHttp(), key),
            observed_at=NOW,
        )


def test_pending_service_receipt_cannot_retire_a_claimed_request(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    pending = CatalogRequesterReceiptV1.create(
        status="pending",
        reason_code="REQUEST_BROKER_PENDING",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=draft.launch_generation,
        observed_at=NOW,
    )
    (
        root / "receipts" / f"{draft.submission_key_sha256}.receipt.json"
    ).write_bytes(canonical_model_bytes(pending) + b"\n")
    key = _private_key()
    fake = _FakeHttp()

    with pytest.raises(ValueError, match="REQUESTER_RECEIPT_INVALID"):
        process_claimed_catalog_request(
            broker_root=root,
            config=config,
            claimed_path=claimed,
            private_key_pem=_private_pem(key),
            client=_client(fake, key),
            observed_at=NOW,
        )

    assert claimed.is_file()
    assert fake.issue_posts == 0


def test_dangling_service_receipt_blocks_before_any_issue_post(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    receipt_path = root / "receipts" / f"{draft.submission_key_sha256}.receipt.json"
    try:
        receipt_path.symlink_to(root / "receipts/missing-receipt.json")
    except OSError as exc:
        pytest.skip(f"file links unavailable: {exc}")
    key = _private_key()
    fake = _FakeHttp()

    with pytest.raises(ValueError, match="REQUESTER_RECEIPT_INVALID"):
        process_claimed_catalog_request(
            broker_root=root,
            config=config,
            claimed_path=claimed,
            private_key_pem=_private_pem(key),
            client=_client(fake, key),
            observed_at=NOW,
        )

    assert claimed.is_file()
    assert fake.issue_posts == 0


def test_completed_claim_is_archived_without_blocking_the_request_queue(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    original_request = claimed.read_bytes()
    key = _private_key()

    process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(_FakeHttp(), key),
        observed_at=NOW,
    )

    archived = root / "processing" / f"processed-{draft.submission_key_sha256}.request"
    assert not claimed.exists()
    assert archived.read_bytes() == original_request
    assert not tuple((root / "processing").glob("*.request.json"))


def test_restart_after_post_marker_can_only_reconcile_never_post(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    key = _private_key()
    from aurora.infra.sp500_megarun.catalog_requester_broker import (
        verify_and_consume_catalog_launch_ticket,
    )

    verify_and_consume_catalog_launch_ticket(
        broker_root=root,
        config=config,
        draft=draft,
    )
    signed = load_or_create_signed_processing_record(
        broker_root=root,
        config=config,
        draft=draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    attempt, created = load_or_create_post_attempt(
        broker_root=root,
        config=config,
        signed=signed,
        post_lower_bound=NOW,
    )
    assert created is True
    assert attempt.processing_record_sha256 == signed.processing_record_sha256
    fake = _FakeHttp()
    fake.created_title = signed.title
    fake.created_body = signed.body
    receipt = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(fake, key),
        observed_at=NOW,
    )
    assert receipt.status == "submitted"
    assert fake.issue_posts == 0
    assert all(not (method == "POST" and url.endswith("/issues")) for method, url in fake.calls)


def test_restart_after_ticket_consume_before_signature_recovers_once(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    from aurora.infra.sp500_megarun.catalog_requester_broker import (
        verify_and_consume_catalog_launch_ticket,
    )

    verify_and_consume_catalog_launch_ticket(
        broker_root=root,
        config=config,
        draft=draft,
    )
    key = _private_key()
    fake = _FakeHttp()
    receipt = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(fake, key),
        observed_at=NOW,
    )
    assert receipt.status == "submitted"
    assert fake.issue_posts == 1


def test_token_failure_before_issue_post_does_not_poison_the_request(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    key = _private_key()

    failing = _FakeHttp(overprivileged=True)
    with pytest.raises(ValueError, match="REQUESTER_APP_OVERPRIVILEGED"):
        process_claimed_catalog_request(
            broker_root=root,
            config=config,
            claimed_path=claimed,
            private_key_pem=_private_pem(key),
            client=_client(failing, key),
            observed_at=NOW,
        )

    attempt = (
        root
        / "processing"
        / f"{draft.submission_key_sha256}.post-attempt.json"
    )
    assert not attempt.exists()
    assert failing.issue_posts == 0

    succeeding = _FakeHttp()
    receipt = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(succeeding, key),
        observed_at=NOW,
    )
    assert receipt.status == "submitted"
    assert succeeding.issue_posts == 1


def test_request_post_window_starts_immediately_before_the_real_post(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    _draft_value, claimed = _claim_installed_draft(root)
    key = _private_key()
    fake = _FakeHttp(issue_created_at="2026-08-22T12:02:01Z")
    observed_times = iter(
        (
            datetime(2026, 8, 22, 12, 1, 59, tzinfo=UTC),
            datetime(2026, 8, 22, 12, 2, 0, tzinfo=UTC),
            datetime(2026, 8, 22, 12, 2, 5, tzinfo=UTC),
        )
    )
    client = CatalogBrokerGithubClient(
        config=config,
        http=fake,
        app_id=42,
        installation_id=123,
        private_key_pem=_private_pem(key),
        expected_actor="aurora-catalog-requester[bot]",
        now=lambda: next(observed_times),
    )

    receipt = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=client,
        observed_at=NOW,
    )
    assert receipt.status == "submitted"
    assert fake.issue_posts == 1


def test_qualification_ticket_is_unique_then_permanently_sealed_before_production(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    (root / "config/production-enabled-v1.seal.json").unlink()
    (root / "config/bootstrap-qualified-v1.seal.json").unlink()
    (root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json").unlink()
    (root / "campaign-status/sp500-optimized-catalog-v1.journal.json").unlink()
    for path in (root / "campaign-status").glob(
        "controller-bootstrap-qualification-v1.*"
    ):
        path.unlink()

    history_key = _private_key()
    first = ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=NOW,
        client=_client(_HistoryHttp([]), history_key),
    )
    second = ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
    )
    assert len(first) == len(second) == 1
    assert first[0] == second[0]
    assert first[0].campaign_key == "controller-bootstrap-qualification-v1"
    assert not (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    ).exists()

    _, draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key="controller-bootstrap-qualification-v1",
    )
    request = root / "inbox" / f"{draft.submission_key_sha256}.request.json"
    request.write_bytes(canonical_model_bytes(draft) + b"\n")
    claimed = claim_next_catalog_request(broker_root=root, config=config)
    assert claimed is not None
    key = _private_key()
    fake = _FakeHttp()
    receipt = process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(fake, key),
        observed_at=NOW,
    )
    signed = CatalogBrokerProcessingRecordV1.model_validate_json(
        (
            root
            / "processing"
            / f"{draft.submission_key_sha256}.signed.json"
        ).read_bytes()
    )
    qualification_successor = advance_catalog_ticket_after_verified_terminal(
        broker_root=root,
        config=config,
        signed=signed,
        issue=_terminal_issue(signed),
        expected_requester_actor="aurora-catalog-requester[bot]",
        observed_at=datetime(2026, 8, 22, 12, 5, tzinfo=UTC),
    )
    assert qualification_successor is None
    assert not (
        root
        / "launch-tickets/controller-bootstrap-qualification-v1.ticket.json"
    ).exists()
    assert ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
    ) == ()
    mismatched_bootstrap_seal = CatalogBrokerBootstrapSealV1.create(
        qualification_submission_key_sha256="9" * 64,
        qualification_request_sha256=receipt.request_sha256 or "0" * 64,
        qualification_issue_number=receipt.issue_number or 0,
        controller_receipt_sha256="8" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
    )
    (root / "config/bootstrap-qualified-v1.seal.json").write_bytes(
        canonical_model_bytes(mismatched_bootstrap_seal) + b"\n"
    )
    with pytest.raises(ValueError, match="REQUESTER_BOOTSTRAP_SEAL_CONTEXT_INVALID"):
        ensure_catalog_launch_tickets(
            broker_root=root,
            config=config,
            observed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
        )
    bootstrap_seal = CatalogBrokerBootstrapSealV1.create(
        qualification_submission_key_sha256=receipt.submission_key_sha256,
        qualification_request_sha256=receipt.request_sha256 or "0" * 64,
        qualification_issue_number=receipt.issue_number or 0,
        controller_receipt_sha256="8" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
    )
    (root / "config/bootstrap-qualified-v1.seal.json").write_bytes(
        canonical_model_bytes(bootstrap_seal) + b"\n"
    )
    duplicate = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key="controller-bootstrap-qualification-v1",
        observed_at=datetime(2026, 8, 22, 12, 2, tzinfo=UTC),
    )
    assert duplicate == receipt
    assert ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=NOW,
    ) == ()

    production_seal = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="1" * 40,
        bootstrap_receipt_sha256=hashlib.sha256(
            (root / "receipts/controller-bootstrap-v1.receipt.json").read_bytes()
        ).hexdigest(),
        requester_client_application_sha256="3" * 64,
        requester_broker_application_sha256="4" * 64,
        sealed_at=datetime(2026, 8, 22, 12, 7, tzinfo=UTC),
    )
    (root / "config/production-enabled-v1.seal.json").write_bytes(
        canonical_model_bytes(production_seal) + b"\n"
    )
    production = ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=NOW,
        client=_client(_HistoryHttp([]), history_key),
    )
    assert len(production) == 1
    assert production[0].campaign_key == "sp500-optimized-catalog-v1"


@pytest.mark.parametrize(
    ("seal_name", "reason_code"),
    (
        ("production-enabled-v1.seal.json", "REQUESTER_PRODUCTION_SEAL_UNPROVEN"),
        ("bootstrap-qualified-v1.seal.json", "REQUESTER_BOOTSTRAP_SEAL_INVALID"),
    ),
)
def test_dangling_seal_path_blocks_instead_of_reopening_qualification(
    tmp_path: Path,
    seal_name: str,
    reason_code: str,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    for path in (
        root / "config/production-enabled-v1.seal.json",
        root / "config/bootstrap-qualified-v1.seal.json",
        root / "launch-tickets/controller-bootstrap-qualification-v1.ticket.json",
        root / "campaign-status/controller-bootstrap-qualification-v1.journal.json",
        root / "campaign-status/controller-bootstrap-qualification-v1.status.json",
    ):
        path.unlink(missing_ok=True)
    for path in (root / "campaign-status").glob(
        "controller-bootstrap-qualification-v1.generation-*"
    ):
        path.unlink()
    seal_path = root / "config" / seal_name
    try:
        seal_path.symlink_to(root / "config/missing-seal-target.json")
    except OSError as exc:
        pytest.skip(f"file links unavailable: {exc}")

    with pytest.raises(ValueError, match=reason_code):
        ensure_catalog_launch_tickets(
            broker_root=root,
            config=config,
            observed_at=NOW,
            client=_client(_HistoryHttp([]), _private_key()),
        )

    assert not (
        root / "launch-tickets/controller-bootstrap-qualification-v1.ticket.json"
    ).exists()


def test_public_launch_ticket_becomes_visible_only_when_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    for path in (
        root / "config/production-enabled-v1.seal.json",
        root / "config/bootstrap-qualified-v1.seal.json",
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json",
        root / "campaign-status/sp500-optimized-catalog-v1.journal.json",
        root / "campaign-status/sp500-optimized-catalog-v1.status.json",
    ):
        path.unlink(missing_ok=True)
    for path in (root / "campaign-status").glob(
        "controller-bootstrap-qualification-v1.*"
    ):
        path.unlink()
    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    original_replace = broker_module.os.replace
    ticket_replace_seen = False

    def checked_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal ticket_replace_seen
        destination_path = Path(destination)
        if destination_path.name.endswith(".ticket.json"):
            ticket_replace_seen = True
            assert not destination_path.exists()
            CatalogLaunchTicketV1.model_validate_json(Path(source).read_bytes())
        original_replace(source, destination)

    monkeypatch.setattr(broker_module.os, "replace", checked_replace)
    tickets = ensure_catalog_launch_tickets(
        broker_root=root,
        config=config,
        observed_at=NOW,
        client=_client(_HistoryHttp([]), _private_key()),
    )
    assert len(tickets) == 1
    assert ticket_replace_seen is True


def _active_installed_request(
    tmp_path: Path,
) -> tuple[Path, CatalogRequesterBrokerConfigV1, CatalogBrokerProcessingRecordV1]:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    draft, claimed = _claim_installed_draft(root)
    key = _private_key()
    process_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        private_key_pem=_private_pem(key),
        client=_client(_FakeHttp(), key),
        observed_at=NOW,
    )
    signed = CatalogBrokerProcessingRecordV1.model_validate_json(
        (
            root
            / "processing"
            / f"{draft.submission_key_sha256}.signed.json"
        ).read_bytes()
    )
    return root, config, signed


def test_existing_active_request_still_requires_the_final_bootstrap_receipt(
    tmp_path: Path,
) -> None:
    root, _, signed = _active_installed_request(tmp_path)
    (root / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(
        b'{"result":"BLOCKED","schema_version":"1"}\n'
    )

    with pytest.raises(
        ValueError,
        match="REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID",
    ):
        submit_registered_catalog_campaign(
            broker_root=root,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=1),
            _wait_for_refresh=False,
        )


def _terminal_issue(
    signed: CatalogBrokerProcessingRecordV1,
    *,
    closed_by: str = "github-actions[bot]",
) -> dict[str, object]:
    return {
        "number": 77,
        "title": signed.title,
        "body": signed.body,
        "state": "closed",
        "state_reason": "completed",
        "user": {"login": "aurora-catalog-requester[bot]"},
        "closed_by": {"login": closed_by},
        "labels": [{"name": "catalog-run-terminal-v1"}],
        "created_at": "2026-08-22T12:00:01Z",
        "closed_at": "2026-08-22T12:04:00Z",
        "updated_at": "2026-08-22T12:04:00Z",
        "html_url": "https://github.com/trading-optimizer-lab-org/aurora/issues/77",
    }


def test_only_exact_controller_terminal_close_publishes_generation_two(
    tmp_path: Path,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    observed = datetime(2026, 8, 22, 12, 5, tzinfo=UTC)
    next_ticket = advance_catalog_ticket_after_verified_terminal(
        broker_root=root,
        config=config,
        signed=signed,
        issue=_terminal_issue(signed),
        expected_requester_actor="aurora-catalog-requester[bot]",
        observed_at=observed,
    )
    repeated = advance_catalog_ticket_after_verified_terminal(
        broker_root=root,
        config=config,
        signed=signed,
        issue=_terminal_issue(signed),
        expected_requester_actor="aurora-catalog-requester[bot]",
        observed_at=datetime(2026, 8, 22, 12, 6, tzinfo=UTC),
    )
    assert repeated == next_ticket
    assert next_ticket.launch_generation == 2
    assert next_ticket.previous_terminal_request_sha256 == signed.request_sha256
    _, next_draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key="sp500-optimized-catalog-v1",
    )
    assert next_draft.launch_generation == 2
    assert next_draft.previous_terminal_request_sha256 == signed.request_sha256


def test_manual_or_unmarked_close_never_advances_ticket(tmp_path: Path) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    with pytest.raises(ValueError, match="REQUESTER_TERMINAL_MARKER_INVALID"):
        advance_catalog_ticket_after_verified_terminal(
            broker_root=root,
            config=config,
            signed=signed,
            issue=_terminal_issue(signed, closed_by="gomez5757"),
            expected_requester_actor="aurora-catalog-requester[bot]",
            observed_at=datetime(2026, 8, 22, 12, 5, tzinfo=UTC),
        )
    assert not (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    ).exists()


class _TerminalPollHttp(_FakeHttp):
    def __init__(
        self,
        *,
        signed: CatalogBrokerProcessingRecordV1,
        terminal: bool,
        closed_by: str = "github-actions[bot]",
    ) -> None:
        super().__init__()
        self.created_title = signed.title
        self.created_body = signed.body
        self.signed = signed
        self.terminal = terminal
        self.closed_by = closed_by
        self.exact_get_headers: list[dict[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        if url.endswith("/repos/trading-optimizer-lab-org/aurora/issues/77"):
            self.calls.append((method, url))
            self.exact_get_headers.append(dict(headers))
            if self.terminal:
                if headers.get("If-None-Match") == '"terminal-v1"':
                    return CatalogBrokerHttpResponse(
                        status_code=304,
                        headers={"ETag": '"terminal-v1"'},
                        json_body=None,
                    )
                return CatalogBrokerHttpResponse(
                    status_code=200,
                    headers={"ETag": '"terminal-v1"'},
                    json_body=_terminal_issue(
                        signed=self.signed,
                        closed_by=self.closed_by,
                    ),
                )
            return CatalogBrokerHttpResponse(
                status_code=200,
                headers={"ETag": '"open-v1"'},
                json_body={
                    "number": 77,
                    "title": self.created_title,
                    "body": self.created_body,
                    "state": "open",
                    "user": {"login": "aurora-catalog-requester[bot]"},
                    "created_at": "2026-08-22T12:00:01Z",
                    "updated_at": "2026-08-22T12:00:01Z",
                    "html_url": (
                        "https://github.com/trading-optimizer-lab-org/aurora/issues/77"
                    ),
                },
            )
        return super().request(
            method,
            url,
            headers=headers,
            json_body=json_body,
        )

def _terminal_poll_http(
    signed: CatalogBrokerProcessingRecordV1,
    *,
    terminal: bool,
    closed_by: str = "github-actions[bot]",
) -> _TerminalPollHttp:
    return _TerminalPollHttp(
        signed=signed,
        terminal=terminal,
        closed_by=closed_by,
    )


def test_six_hour_open_request_uses_backoff_and_conditional_gets(
    tmp_path: Path,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    fake = _terminal_poll_http(signed, terminal=False)
    client = _client(fake, _private_key())
    for elapsed in range(0, 6 * 60 * 60 + 1, 2):
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(seconds=elapsed),
        )
    assert 1 < len(fake.exact_get_headers) < 40
    assert "If-None-Match" not in fake.exact_get_headers[0]
    assert all(
        headers.get("If-None-Match") == '"open-v1"'
        for headers in fake.exact_get_headers[1:]
    )


def test_one_valid_hint_triggers_at_most_one_eligible_terminal_get(
    tmp_path: Path,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    status_path = root / "campaign-status/sp500-optimized-catalog-v1.status.json"
    status = CatalogRequesterCampaignStatusV1.model_validate_json(
        status_path.read_bytes()
    )
    hint = CatalogRequesterReconcileHintV1.create(
        status=status,
        hinted_at=NOW + timedelta(minutes=5),
    )
    hint_path = root / "inbox/sp500-optimized-catalog-v1.reconcile-hint.json"
    hint_path.write_bytes(canonical_model_bytes(hint) + b"\n")
    claimed = claim_next_catalog_reconcile_hint(broker_root=root, config=config)
    assert claimed is not None
    fake = _terminal_poll_http(signed, terminal=True)
    result = process_claimed_catalog_reconcile_hint(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        client=_client(fake, _private_key()),
        observed_at=NOW + timedelta(minutes=5),
    )
    assert result is not None
    assert result.launch_generation == 2
    assert len(fake.exact_get_headers) == 1
    assert not claimed.exists()


def test_crash_after_terminal_get_cannot_poison_retry_with_terminal_etag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    fake = _terminal_poll_http(signed, terminal=True)
    client = _client(fake, _private_key())
    from aurora.infra.sp500_megarun import catalog_requester_broker as broker_module

    original_advance = broker_module.advance_catalog_ticket_after_verified_terminal
    attempts = 0

    def crash_once(**kwargs: object) -> CatalogLaunchTicketV1:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated crash before terminal transition")
        return original_advance(**kwargs)

    monkeypatch.setattr(
        broker_module,
        "advance_catalog_ticket_after_verified_terminal",
        crash_once,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=5),
        )

    next_ticket = reconcile_active_catalog_campaign(
        broker_root=root,
        config=config,
        client=client,
        campaign_key=signed.request.campaign_key,
        observed_at=NOW + timedelta(minutes=6),
    )
    assert next_ticket is not None
    assert next_ticket.launch_generation == 2
    assert len(fake.exact_get_headers) == 2
    assert fake.exact_get_headers[1].get("If-None-Match") != '"terminal-v1"'


def test_invalid_terminal_close_is_backed_off_without_persisting_its_etag(
    tmp_path: Path,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    fake = _terminal_poll_http(
        signed,
        terminal=True,
        closed_by="gomez5757",
    )
    client = _client(fake, _private_key())

    assert (
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=5),
        )
        is None
    )
    assert (
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=5, seconds=2),
        )
        is None
    )
    assert len(fake.exact_get_headers) == 1
    poll_state = json.loads(
        (
            root
            / "campaign-status/sp500-optimized-catalog-v1.terminal-poll.json"
        ).read_text(encoding="utf-8")
    )
    assert poll_state["etag"] != '"terminal-v1"'


def test_deleted_issue_isolated_to_its_campaign_with_bounded_backoff(
    tmp_path: Path,
) -> None:
    root, config, signed = _active_installed_request(tmp_path)

    class DeletedIssueHttp(_TerminalPollHttp):
        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json_body: dict[str, object] | None = None,
        ) -> CatalogBrokerHttpResponse:
            if url.endswith("/repos/trading-optimizer-lab-org/aurora/issues/77"):
                self.calls.append((method, url))
                self.exact_get_headers.append(dict(headers))
                return CatalogBrokerHttpResponse(
                    status_code=404,
                    headers={},
                    json_body={"message": "Not Found"},
                )
            return super().request(
                method,
                url,
                headers=headers,
                json_body=json_body,
            )

    fake = DeletedIssueHttp(signed=signed, terminal=False)
    client = _client(fake, _private_key())
    assert (
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=5),
        )
        is None
    )
    assert (
        reconcile_active_catalog_campaign(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=signed.request.campaign_key,
            observed_at=NOW + timedelta(minutes=5, seconds=2),
        )
        is None
    )
    assert len(fake.exact_get_headers) == 1
    journal = json.loads(
        (root / "campaign-status/sp500-optimized-catalog-v1.journal.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "active"


def test_duplicate_reconcile_hint_is_a_drained_local_noop(tmp_path: Path) -> None:
    root, config, signed = _active_installed_request(tmp_path)
    status = CatalogRequesterCampaignStatusV1.model_validate_json(
        (root / "campaign-status/sp500-optimized-catalog-v1.status.json").read_bytes()
    )
    hint = CatalogRequesterReconcileHintV1.create(
        status=status,
        hinted_at=NOW + timedelta(minutes=5),
    )
    hint_bytes = canonical_model_bytes(hint) + b"\n"
    inbox_hint = root / "inbox/sp500-optimized-catalog-v1.reconcile-hint.json"
    fake = _terminal_poll_http(signed, terminal=False)
    client = _client(fake, _private_key())

    inbox_hint.write_bytes(hint_bytes)
    first = claim_next_catalog_reconcile_hint(broker_root=root, config=config)
    assert first is not None
    process_claimed_catalog_reconcile_hint(
        broker_root=root,
        config=config,
        claimed_path=first,
        client=client,
        observed_at=NOW + timedelta(minutes=5),
    )

    inbox_hint.write_bytes(hint_bytes)
    second = claim_next_catalog_reconcile_hint(broker_root=root, config=config)
    assert second is not None
    result = process_claimed_catalog_reconcile_hint(
        broker_root=root,
        config=config,
        claimed_path=second,
        client=client,
        observed_at=NOW + timedelta(minutes=10),
    )
    assert result is None
    assert len(fake.exact_get_headers) == 1
    assert not second.exists()


def test_restart_recovers_one_already_claimed_reconcile_hint(
    tmp_path: Path,
) -> None:
    root, config, _signed = _active_installed_request(tmp_path)
    status = CatalogRequesterCampaignStatusV1.model_validate_json(
        (root / "campaign-status/sp500-optimized-catalog-v1.status.json").read_bytes()
    )
    hint = CatalogRequesterReconcileHintV1.create(
        status=status,
        hinted_at=NOW + timedelta(minutes=5),
    )
    (root / "inbox/sp500-optimized-catalog-v1.reconcile-hint.json").write_bytes(
        canonical_model_bytes(hint) + b"\n"
    )

    claimed_before_restart = claim_next_catalog_reconcile_hint(
        broker_root=root,
        config=config,
    )
    assert claimed_before_restart is not None
    assert claimed_before_restart.parent == root / "processing"

    claimed_after_restart = claim_next_catalog_reconcile_hint(
        broker_root=root,
        config=config,
    )
    assert claimed_after_restart == claimed_before_restart


def test_claim_selection_skips_busy_processing_files_without_starving_peers(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    processing = root / "processing"
    busy_request = processing / f"{'1' * 64}.request.json"
    ready_request = processing / f"{'2' * 64}.request.json"
    busy_hint = processing / "a.reconcile-hint.json"
    ready_hint = processing / "b.reconcile-hint.json"
    for path in (busy_request, ready_request, busy_hint, ready_hint):
        path.write_bytes(b"{}\n")

    assert claim_next_catalog_request(
        broker_root=root,
        config=config,
        excluded_processing_names=frozenset({busy_request.name}),
    ) == ready_request
    assert claim_next_catalog_reconcile_hint(
        broker_root=root,
        config=config,
        excluded_processing_names=frozenset({busy_hint.name}),
    ) == ready_hint


def test_malformed_claimed_request_is_quarantined_without_network_or_retry_loop(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    malformed = root / "inbox" / f"{'a' * 64}.request.json"
    malformed.write_bytes(b'{"broken":true}\n')
    claimed = claim_next_catalog_request(broker_root=root, config=config)
    assert claimed is not None
    with pytest.raises(ValueError, match="REQUESTER_BROKER_REQUEST_INVALID"):
        load_claimed_catalog_draft(claimed_path=claimed, config=config)
    quarantined = quarantine_invalid_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        reason_code="REQUESTER_BROKER_REQUEST_INVALID",
        observed_at=NOW,
    )
    assert quarantined.is_file()
    assert not claimed.exists()
    assert not tuple((root / "processing").glob("*.request.json"))


def test_raced_hard_link_claim_is_quarantined_without_following_or_deadlock(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    config = _config()
    claimed = root / "processing" / f"{'a' * 64}.request.json"
    retained_link = tmp_path / "retained-invalid-link.json"
    claimed.write_bytes(b'{"broken":true}\n')
    try:
        os.link(claimed, retained_link)
    except OSError:
        pytest.skip("hard links unavailable on this filesystem")

    quarantined = quarantine_invalid_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed,
        reason_code="REQUESTER_BROKER_CLAIM_ACL_INVALID",
        observed_at=NOW,
    )

    assert quarantined.is_file()
    assert not claimed.exists()
    assert retained_link.read_bytes() == b'{"broken":true}\n'


def _history_signed_requests(
    key: rsa.RSAPrivateKey,
    *,
    campaign_definition_sha256: str = "2" * 64,
    prompt_sha256: str = "3" * 64,
) -> tuple[CatalogBrokerProcessingRecordV1, CatalogBrokerProcessingRecordV1]:
    first_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=campaign_definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=None,
    )
    first_draft = CatalogRunIntentDraftV1(
        **_draft().model_copy(
            update={
                "launch_ticket_sha256": first_ticket.launch_ticket_sha256,
                "campaign_definition_sha256": campaign_definition_sha256,
                "prompt_sha256": prompt_sha256,
            }
        ).model_dump(mode="json")
    )
    first = sign_catalog_request(
        draft=first_draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    second_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id="018f47a2-6e91-7c34-8000-000000000002",
        campaign_key=first.request.campaign_key,
        launch_generation=2,
        campaign_definition_sha256=first.request.campaign_definition_sha256,
        prompt_sha256=first.request.prompt_sha256,
        previous_terminal_request_sha256=first.request_sha256,
    )
    second_draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=second_ticket.request_id,
        campaign_key=second_ticket.campaign_key,
        launch_generation=second_ticket.launch_generation,
        launch_ticket_sha256=second_ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=first.request_sha256,
        campaign_definition_sha256=second_ticket.campaign_definition_sha256,
        prompt_sha256=second_ticket.prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    second = sign_catalog_request(
        draft=second_draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW + timedelta(minutes=2),
    )
    return first, second


def _history_issue(
    signed: CatalogBrokerProcessingRecordV1,
    *,
    number: int,
    minute: int,
    terminal: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": number,
        "title": signed.title,
        "body": signed.body,
        "state": "closed" if terminal else "open",
        "state_reason": "completed" if terminal else None,
        "user": {"login": "aurora-catalog-requester[bot]"},
        "closed_by": {"login": "github-actions[bot]"} if terminal else None,
        "labels": [{"name": "catalog-run-terminal-v1"}] if terminal else [],
        "created_at": f"2026-08-22T12:{minute:02d}:01Z",
        "updated_at": f"2026-08-22T12:{minute + 1:02d}:00Z",
        "closed_at": f"2026-08-22T12:{minute + 1:02d}:00Z" if terminal else None,
        "html_url": (
            f"https://github.com/trading-optimizer-lab-org/aurora/issues/{number}"
        ),
    }
    return payload


class _HistoryHttp(_FakeHttp):
    def __init__(self, issues: list[dict[str, object]]) -> None:
        super().__init__()
        self.issues = issues

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        if "/issues?" not in url:
            return super().request(
                method,
                url,
                headers=headers,
                json_body=json_body,
            )
        self.calls.append((method, url))
        page = 2 if "&page=2" in url else 1
        start = (page - 1) * 100
        body = self.issues[start : start + 100]
        response_headers: dict[str, str] = {}
        if start + 100 < len(self.issues):
            response_headers["Link"] = (
                "<https://api.github.com/repos/trading-optimizer-lab-org/aurora/"
                "issues?state=all&sort=created&direction=desc&per_page=100&page=2>; "
                'rel="next"'
            )
        return CatalogBrokerHttpResponse(
            status_code=200,
            headers=response_headers,
            json_body=body,
        )


def test_terminal_qualification_history_can_never_reconstruct_generation_two(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    (root / "launch-tickets").mkdir()
    (root / "campaign-status").mkdir()
    config = _config()
    key = _private_key()
    campaign_key = config.bootstrap_qualification.campaign_key
    definition_sha256 = hashlib.sha256(
        canonical_model_bytes(config.bootstrap_qualification)
    ).hexdigest()
    prompt_sha256 = "3" * 64
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=campaign_key,
        launch_generation=1,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=None,
    )
    draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=ticket.request_id,
        campaign_key=ticket.campaign_key,
        launch_generation=1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    signed = sign_catalog_request(
        draft=draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    client = _client(
        _HistoryHttp([_history_issue(signed, number=77, minute=1, terminal=True)]),
        key,
    )

    reconstructed = reconstruct_catalog_campaign_journal_from_github(
        broker_root=root,
        config=config,
        client=client,
        campaign_key=campaign_key,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        observed_at=NOW + timedelta(minutes=10),
    )

    assert reconstructed is None
    assert not (root / f"launch-tickets/{campaign_key}.ticket.json").exists()
    journal = json.loads(
        (root / f"campaign-status/{campaign_key}.journal.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "terminal"
    assert journal["launch_generation"] == 1


def test_qualification_history_rejects_more_than_its_single_allowed_post(
    tmp_path: Path,
) -> None:
    root = _broker_root(tmp_path)
    (root / "launch-tickets").mkdir()
    (root / "campaign-status").mkdir()
    config = _config()
    key = _private_key()
    campaign_key = config.bootstrap_qualification.campaign_key
    definition_sha256 = canonical_sha256(config.bootstrap_qualification)
    prompt_sha256 = "3" * 64
    first_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=campaign_key,
        launch_generation=1,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=None,
    )
    first_draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=first_ticket.request_id,
        campaign_key=campaign_key,
        launch_generation=1,
        launch_ticket_sha256=first_ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    first_signed = sign_catalog_request(
        draft=first_draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW,
    )
    second_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id="018f47a2-6e91-7c34-8000-000000000002",
        campaign_key=campaign_key,
        launch_generation=2,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=first_signed.request_sha256,
    )
    second_draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=second_ticket.request_id,
        campaign_key=campaign_key,
        launch_generation=2,
        launch_ticket_sha256=second_ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=first_signed.request_sha256,
        campaign_definition_sha256=definition_sha256,
        prompt_sha256=prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    second_signed = sign_catalog_request(
        draft=second_draft,
        private_key_pem=_private_pem(key),
        signed_at=NOW + timedelta(minutes=2),
    )
    client = _client(
        _HistoryHttp(
            [
                _history_issue(second_signed, number=78, minute=3, terminal=True),
                _history_issue(first_signed, number=77, minute=1, terminal=True),
            ]
        ),
        key,
    )

    with pytest.raises(ValueError, match="REQUESTER_QUALIFICATION_HISTORY_INVALID"):
        reconstruct_catalog_campaign_journal_from_github(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=campaign_key,
            campaign_definition_sha256=definition_sha256,
            prompt_sha256=prompt_sha256,
            observed_at=NOW + timedelta(minutes=10),
        )

    assert not (root / f"campaign-status/{campaign_key}.journal.json").exists()
    assert not (root / f"launch-tickets/{campaign_key}.ticket.json").exists()


def test_missing_journal_rebuilds_only_one_contiguous_signed_history_across_pages(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    for path in (
        root / "campaign-status/sp500-optimized-catalog-v1.journal.json",
        root / "campaign-status/sp500-optimized-catalog-v1.status.json",
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json",
    ):
        path.unlink(missing_ok=True)
    key = _private_key()
    first, second = _history_signed_requests(key)
    unrelated = [
        {
            "number": 1_000 + offset,
            "title": f"unrelated-{offset}",
            "body": "not a catalog request",
            "state": "open",
            "user": {"login": "someone-else"},
            "created_at": "2026-08-22T12:10:00Z",
            "updated_at": "2026-08-22T12:10:00Z",
            "html_url": (
                "https://github.com/trading-optimizer-lab-org/aurora/issues/"
                f"{1_000 + offset}"
            ),
        }
        for offset in range(100)
    ]
    issues = [
        *unrelated,
        _history_issue(second, number=78, minute=4, terminal=True),
        _history_issue(first, number=77, minute=1, terminal=True),
    ]
    fake = _HistoryHttp(issues)
    next_ticket = reconstruct_catalog_campaign_journal_from_github(
        broker_root=root,
        config=_config(),
        client=_client(fake, key),
        campaign_key=first.request.campaign_key,
        campaign_definition_sha256=first.request.campaign_definition_sha256,
        prompt_sha256=first.request.prompt_sha256,
        observed_at=NOW + timedelta(minutes=10),
    )
    assert next_ticket is not None
    assert next_ticket.launch_generation == 3
    assert next_ticket.previous_terminal_request_sha256 == second.request_sha256
    assert sum("/issues?" in url for _, url in fake.calls) == 2
    assert fake.issue_posts == 0


def test_history_allows_sequential_issue_numbers_with_same_second_timestamp(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    for path in (
        root / "campaign-status/sp500-optimized-catalog-v1.journal.json",
        root / "campaign-status/sp500-optimized-catalog-v1.status.json",
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json",
    ):
        path.unlink(missing_ok=True)
    key = _private_key()
    first, second = _history_signed_requests(key)
    first_issue = _history_issue(first, number=77, minute=1, terminal=True)
    second_issue = _history_issue(second, number=78, minute=4, terminal=True)
    second_issue["created_at"] = first_issue["created_at"]
    fake = _HistoryHttp([second_issue, first_issue])

    next_ticket = reconstruct_catalog_campaign_journal_from_github(
        broker_root=root,
        config=_config(),
        client=_client(fake, key),
        campaign_key=first.request.campaign_key,
        campaign_definition_sha256=first.request.campaign_definition_sha256,
        prompt_sha256=first.request.prompt_sha256,
        observed_at=NOW + timedelta(minutes=10),
    )
    assert next_ticket is not None
    assert next_ticket.launch_generation == 3


def test_history_fork_blocks_without_ticket_or_issue_post(tmp_path: Path) -> None:
    root = _installed_broker_tree(tmp_path)
    for path in (
        root / "campaign-status/sp500-optimized-catalog-v1.journal.json",
        root / "campaign-status/sp500-optimized-catalog-v1.status.json",
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json",
    ):
        path.unlink(missing_ok=True)
    key = _private_key()
    first, second = _history_signed_requests(key)
    fork = sign_catalog_request(
        draft=second.request.intent,
        private_key_pem=_private_pem(key),
        signed_at=NOW + timedelta(minutes=3),
    )
    fake = _HistoryHttp(
        [
            _history_issue(fork, number=79, minute=5, terminal=False),
            _history_issue(second, number=78, minute=4, terminal=True),
            _history_issue(first, number=77, minute=1, terminal=True),
        ]
    )
    with pytest.raises(ValueError, match="REQUESTER_HISTORY_CHAIN_INVALID"):
        reconstruct_catalog_campaign_journal_from_github(
            broker_root=root,
            config=_config(),
            client=_client(fake, key),
            campaign_key=first.request.campaign_key,
            campaign_definition_sha256=first.request.campaign_definition_sha256,
            prompt_sha256=first.request.prompt_sha256,
            observed_at=NOW + timedelta(minutes=10),
        )
    assert not (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    ).exists()
    assert fake.issue_posts == 0


def test_restart_during_open_history_rebuild_repairs_missing_signed_state(
    tmp_path: Path,
) -> None:
    root = _installed_broker_tree(tmp_path)
    initial_ticket_path = (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    )
    initial_ticket = CatalogLaunchTicketV1.model_validate_json(
        initial_ticket_path.read_bytes()
    )
    for path in (
        root / "campaign-status/sp500-optimized-catalog-v1.journal.json",
        root / "campaign-status/sp500-optimized-catalog-v1.status.json",
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json",
    ):
        path.unlink(missing_ok=True)
    key = _private_key()
    first, second = _history_signed_requests(
        key,
        campaign_definition_sha256=initial_ticket.campaign_definition_sha256,
        prompt_sha256=initial_ticket.prompt_sha256,
    )
    issues = [
        _history_issue(second, number=78, minute=4, terminal=False),
        _history_issue(first, number=77, minute=1, terminal=True),
    ]
    fake = _HistoryHttp(issues)
    client = _client(fake, key)
    assert reconstruct_catalog_campaign_journal_from_github(
        broker_root=root,
        config=_config(),
        client=client,
        campaign_key=second.request.campaign_key,
        campaign_definition_sha256=second.request.campaign_definition_sha256,
        prompt_sha256=second.request.prompt_sha256,
        observed_at=NOW + timedelta(minutes=10),
    ) is None
    signed_path = (
        root
        / "processing"
        / f"{second.request.intent.submission_key_sha256}.signed.json"
    )
    os.rename(signed_path, signed_path.with_suffix(".simulated-crash"))

    recovered = ensure_catalog_launch_tickets(
        broker_root=root,
        config=_config(),
        observed_at=NOW + timedelta(minutes=11),
        client=client,
    )
    assert recovered == ()
    assert signed_path.is_file()
    assert fake.issue_posts == 0
