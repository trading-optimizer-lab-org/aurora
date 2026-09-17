"""Real broker/parser consumers with synthetic network and durable storage."""

from datetime import timedelta

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_transport import deliver_cloud_emission
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_cloud_authority import emission
from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY
from tests.test_catalog_requester_broker import _FakeHttp, _client, _private_key, NOW


class Authority:
    def __init__(self, item):
        self.state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
        self.phases = []

    def read(self):
        return FastAuthorityStateV1.model_validate_json(self.state.model_dump_json())

    def publish(self, old, new, phase):
        assert old == self.state
        self.phases.append(phase)
        self.state = new


def deliver(authority, http, **changes):
    arguments = dict(
        intent_id=emission().intent_id, run_id=500, run_attempt=1,
        read=authority.read, publish=authority.publish,
        client=_client(http, _private_key()), trusted_public_key=REQUESTER_TEST_PUBLIC_KEY,
        post_lower_bound=NOW, post_upper_bound=NOW + timedelta(seconds=10),
    )
    arguments.update(changes)
    return deliver_cloud_emission(**arguments)


def test_publish_uncertainty_then_one_post_and_idempotent_replay():
    authority, http = Authority(emission()), _FakeHttp()
    item = deliver(authority, http)
    assert item.state == "PUBLICADO" and item.issue_number == 77
    assert authority.phases == ["intake-uncertain", "intake-published"]
    assert http.created_body == emission().body
    assert deliver(authority, http, run_attempt=2) == item
    assert http.issue_posts == 1


def test_timeout_after_accept_reconciles_exact_issue_without_second_post():
    authority, http = Authority(emission()), _FakeHttp(uncertain_post=True)
    assert deliver(authority, http).issue_number == 77
    assert http.issue_posts == 1


def test_crash_after_uncertainty_never_reposts_even_same_run_attempt():
    authority, http = Authority(emission()), _FakeHttp()
    authority.state = authority.state.advance_emission(
        intent_id=emission().intent_id, state="PUBLICACION_INCIERTA",
        post_run_id=500, post_run_attempt=1,
    )
    with pytest.raises(ValueError, match="RECONCILIATION_RETRYABLE"):
        deliver(authority, http)
    assert http.issue_posts == 0
    assert authority.state.emissions[0].state == "PUBLICACION_INCIERTA"


def test_failed_durable_publication_prevents_post():
    authority, http = Authority(emission()), _FakeHttp()
    def unavailable(*args):
        raise ValueError("PUBLICATION_UNAVAILABLE")
    with pytest.raises(ValueError, match="PUBLICATION_UNAVAILABLE"):
        deliver(authority, http, publish=unavailable)
    assert http.issue_posts == 0 and http.token_requests == []


def test_unpublished_readback_prevents_post():
    authority, http = Authority(emission()), _FakeHttp()
    with pytest.raises(ValueError, match="READBACK_MISMATCH"):
        deliver(authority, http, publish=lambda *args: None)
    assert http.issue_posts == 0


def test_publication_failure_after_post_recovers_without_resigning_or_reposting():
    authority, http = Authority(emission()), _FakeHttp()
    def fail_last(old, new, phase):
        if phase == "intake-published":
            raise ValueError("ARTIFACT_UNAVAILABLE")
        authority.publish(old, new, phase)
    with pytest.raises(ValueError, match="ARTIFACT_UNAVAILABLE"):
        deliver(authority, http, publish=fail_last)
    assert authority.state.emissions[0].state == "PUBLICACION_INCIERTA"
    assert deliver(authority, http, run_attempt=2).issue_number == 77
    assert http.issue_posts == 1


def test_overprivileged_app_token_cannot_post():
    authority, http = Authority(emission()), _FakeHttp(overprivileged=True)
    with pytest.raises(ValueError):
        deliver(authority, http)
    assert http.issue_posts == 0
