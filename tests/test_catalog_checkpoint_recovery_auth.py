from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_auth as auth
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1


REPOSITORY = "trading-optimizer-lab-org/aurora"
CAMPAIGN = "sp500-optimized-catalog-v1"
COMMIT = "d12a374ab84bfb4e79bd5039343ffd5bd963c115"
CURRENT_COMMIT = "e" * 40
ANCESTOR = "a" * 40
OTHER_COMMIT = "b" * 40
REQUEST_SHA = "db7838f228058a301bb369a02e7133096cc48846cf0be8d6dac79372152ba2e1"
RUN_ID = 35504391586
RUN_ATTEMPT = 1
ISSUE = 339

ROOT = Path(__file__).resolve().parents[1]


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        profile_sha256="c" * 64,
        campaign_key=CAMPAIGN,
        target_generation=8,
        source_generation=7,
        source_issue_number=ISSUE,
        source_run_id=RUN_ID,
        source_run_attempt=RUN_ATTEMPT,
        source_request_sha256=REQUEST_SHA,
        source_protected_commit_sha=COMMIT,
        source_plan_bindings={
            "request_sha256": REQUEST_SHA,
            "decision_sha256": "d" * 64,
            "authority_id": "authority-v1",
            "campaign_id": "sp500-optimized-catalog-v1",
            "science_sha256": "e" * 64,
            "execution_plan_sha256": "f" * 64,
            "execution_protocol_sha256": "1" * 64,
            "protected_commit_sha": COMMIT,
        },
    )


def _owner(
    profile: SimpleNamespace,
    *,
    submission_key_sha256: str = "2" * 64,
) -> FastGateOwnerEvidence:
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=profile.source_request_sha256,
        submission_key_sha256=submission_key_sha256,
        campaign_key=profile.campaign_key,
        prepared_receipt_sha256=None,
        selected_workers=1,
        launch_required=True,
        existing_run_id=None,
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    profile.source_plan_bindings["decision_sha256"] = decision.decision_sha256
    steps = [
        {
            "name": name,
            "status": "completed",
            "conclusion": conclusion,
        }
        for name, conclusion in (
            ("Fetch one bounded timing snapshot", "failure"),
            ("Create exactly one terminal receipt", "skipped"),
            ("Publish the terminal receipt before changing the issue", "skipped"),
            ("Write current authority edition", "skipped"),
            ("Publish current authority edition", "skipped"),
            ("Verify the terminal publication before releasing the campaign", "skipped"),
            ("Publish the terminal state and release the reservation", "skipped"),
        )
    ]
    run = {
        "id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": COMMIT,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "failure",
    }
    job = {
        "id": 9001,
        "name": "finalize",
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": COMMIT,
        "status": "completed",
        "conclusion": "failure",
        "steps": steps,
    }
    return FastGateOwnerEvidence(RUN_ID, run, decision, (job,))


class _InjectedClient:
    repository = REPOSITORY

    def __init__(self, *, actor: str, comparison: dict[str, object]) -> None:
        self.calls: list[str] = []
        self.actor = actor
        self.comparison = comparison

    def get_json(self, path: str) -> tuple[object, object]:
        self.calls.append(path)
        if path.endswith(f"/issues/{ISSUE}"):
            return {
                "number": ISSUE,
                "user": {"login": self.actor},
                "title": "ignored by the parser stub",
                "body": "ignored by the parser stub",
            }, None
        if "/compare/" in path:
            return self.comparison, None
        raise AssertionError(f"unexpected GET path: {path}")

    def stable_paginated(self, path: str, *, root: str) -> object:
        raise AssertionError(f"stable inventory should be supplied by the loader stub: {path} {root}")


def _request(*, request_sha: str = REQUEST_SHA, campaign: str = CAMPAIGN) -> SimpleNamespace:
    return SimpleNamespace(
        request_sha256=request_sha,
        campaign_key=campaign,
        launch_generation=7,
    )


def _base_kwargs(client: auth._ReadOnlyClient, profile: SimpleNamespace) -> dict[str, object]:
    return {
        "repo_root": ROOT,
        "repository": REPOSITORY,
        "protected_commit_sha": CURRENT_COMMIT,
        "profile": profile,
        "fetch_json": client,
        "download_artifact": lambda artifact_id: (_ for _ in ()).throw(
            AssertionError(f"unexpected artifact download {artifact_id}")
        ),
    }


def _patch_request_parser(monkeypatch: pytest.MonkeyPatch, request: SimpleNamespace) -> None:
    def parse(title: str, body: str, public_key: bytes) -> SimpleNamespace:
        assert title and body and public_key.startswith(b"-----BEGIN")
        return request

    monkeypatch.setattr(auth, "parse_catalog_run_request", parse)


def _patch_profile(monkeypatch: pytest.MonkeyPatch, profile: SimpleNamespace) -> None:
    seen: list[object] = []

    def validate(repo_root: Path, candidate: object) -> SimpleNamespace:
        assert repo_root == ROOT
        seen.append(candidate)
        return profile

    monkeypatch.setattr(auth, "validate_exact_checkpoint_profile", validate)


def _good_comparison() -> dict[str, object]:
    return {
        "status": "ahead",
        "base_commit": {"sha": COMMIT},
        "merge_base_commit": {"sha": COMMIT},
    }


def _real_request() -> CatalogRunRequestV1:
    return CatalogRunRequestV1.model_validate({
        "schema_version": "1",
        "request_id": "018f47a2-6e91-7c34-8000-000000000001",
        "campaign_key": CAMPAIGN,
        "launch_generation": 7,
        "launch_ticket_sha256": "8" * 64,
        "previous_terminal_request_sha256": "9" * 64,
        "campaign_definition_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "c" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 300,
    })


def _production_reader_fixture(
    profile: SimpleNamespace,
    request: CatalogRunRequestV1,
    comparison: dict[str, object],
) -> tuple[auth._ReadOnlyClient, Callable[[int], bytes], FastGateOwnerEvidence]:
    owner = _owner(profile, submission_key_sha256=request.submission_key_sha256)
    context = {
        "request": request.model_dump(mode="json"),
        "issue_number": ISSUE,
    }
    context["content_sha256"] = canonical_sha256(context)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("catalog-fast-request-context.json", json.dumps(context))
        archive.writestr("catalog-fast-decision-v1.json", owner.decision.model_dump_json())
    raw = archive_buffer.getvalue()
    artifact = {
        "id": 9101,
        "name": f"catalog-fast-gate-{ISSUE}",
        "expired": False,
        "size_in_bytes": len(raw),
        "created_at": "2026-01-01T00:00:02Z",
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "workflow_run": {
            "id": RUN_ID,
            "head_sha": COMMIT,
            "head_branch": "main",
            "repository_id": 123,
            "head_repository_id": 123,
        },
    }
    run = {
        **owner.run,
        "check_suite_id": 96135672007,
        "path": ".github/workflows/catalog-fast-controller.yml",
        "event": "issues",
        "repository": {"id": 123, "full_name": REPOSITORY, "private": False},
    }
    gate = {
        "id": 9102,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": COMMIT,
        "name": "gate",
        "status": "completed",
        "conclusion": "success",
        "steps": [
            {
                "name": "Publish the one gate decision",
                "number": 1,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:03Z",
            },
            {
                "name": "Reserve the campaign atomically and expose QUEUED",
                "number": 2,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-01-01T00:00:04Z",
                "completed_at": "2026-01-01T00:00:05Z",
            },
        ],
    }
    jobs = (gate, *owner.jobs)
    actor = json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text())[
        "request_actors"
    ][0]

    class Client:
        repository = REPOSITORY

        def __init__(self):
            self.inventory_paths = []
            self.job_reads = []
            self.control_jobs = {job['id']: {**job,
                'check_run_url': f"https://api.github.com/repos/{REPOSITORY}/check-runs/{job['id']}"
            } for job in jobs}
            self.checks = {
                job['name']: {
                    'id': job['id'], 'name': job['name'], 'head_sha': COMMIT,
                    'status': 'completed', 'conclusion': job['conclusion'],
                    'check_suite': {'id': 96135672007},
                    'app': {'id': 15368, 'slug': 'github-actions'},
                    'details_url': f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}/job/{job['id']}",
                } for job in jobs
            }

        def get_json(self, path: str) -> tuple[object, object]:
            if '/actions/jobs/' in path:
                identifier = int(path.rsplit('/', 1)[1])
                self.job_reads.append(identifier)
                return deepcopy(self.control_jobs[identifier]), None
            if path.endswith(f"/issues/{ISSUE}"):
                return {
                    "number": ISSUE,
                    "user": {"login": actor},
                    "title": "ignored by parser stub",
                    "body": "ignored by parser stub",
                }, None
            if path.endswith(f"/actions/runs/{RUN_ID}"):
                return run, None
            if "/compare/" in path:
                return comparison, None
            raise AssertionError(path)

        def stable_paginated(self, path: str, *, root: str) -> object:
            self.inventory_paths.append(path)
            for name, check in self.checks.items():
                if path == (f'/repos/{REPOSITORY}/check-suites/96135672007/'
                            f'check-runs?check_name={name}&filter=all'):
                    assert root == 'check_runs'
                    return SimpleNamespace(stable=True,
                        collection=SimpleNamespace(complete=True, rows=(check,)))
            if path.endswith(f"/actions/runs/{RUN_ID}/artifacts?name=catalog-fast-gate-{ISSUE}"):
                return SimpleNamespace(
                    stable=True,
                    collection=SimpleNamespace(complete=True, rows=(artifact,)),
                )
            if path.endswith(f"/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}/jobs"):
                return SimpleNamespace(
                    stable=True,
                    collection=SimpleNamespace(complete=True, rows=jobs),
                )
            if path.endswith(
                f"/actions/runs/{RUN_ID}/artifacts?name=catalog-terminal-receipt-{request.request_sha256}"
            ):
                return SimpleNamespace(
                    stable=True,
                    collection=SimpleNamespace(complete=True, rows=()),
                )
            raise AssertionError((path, root))

    def download(artifact_id: int) -> bytes:
        assert artifact_id == artifact["id"]
        return raw

    return Client(), download, owner


@pytest.mark.parametrize("comparison", (_good_comparison(), {
    "status": "behind",
    "base_commit": {"sha": OTHER_COMMIT},
    "merge_base_commit": {"sha": OTHER_COMMIT},
}))
def test_authentication_uses_real_owner_reader_for_current_merge_and_ancestor(
    monkeypatch: pytest.MonkeyPatch,
    comparison: dict[str, object],
) -> None:
    profile = _profile()
    request = _real_request()
    profile.source_request_sha256 = request.request_sha256
    profile.source_plan_bindings["request_sha256"] = request.request_sha256
    client, download, _ = _production_reader_fixture(profile, request, comparison)
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, request)

    if comparison["status"] == "behind":
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_SOURCE_UNAPPROVED"):
            auth.authenticate_checkpoint_recovery_owner(
                **{
                    **_base_kwargs(client, profile),
                    "download_artifact": download,
                }
            )
        return

    authenticated = auth.authenticate_checkpoint_recovery_owner(
        **{
            **_base_kwargs(client, profile),
            "download_artifact": download,
        }
    )
    assert CURRENT_COMMIT != profile.source_protected_commit_sha
    assert authenticated.owner.run_id == RUN_ID
    assert authenticated.proof.source_protected_commit_sha == COMMIT
    assert client.inventory_paths[0] == (
        f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts?name=catalog-fast-gate-{ISSUE}"
    )
    assert all('/actions/artifacts?' not in path for path in client.inventory_paths)


def test_checkpoint_authentication_never_downloads_all_worker_jobs(monkeypatch):
    """Large historical worker inventories must not sit in the live gate."""
    profile = _profile()
    request = _real_request()
    profile.source_request_sha256 = request.request_sha256
    profile.source_plan_bindings['request_sha256'] = request.request_sha256
    client, download, _ = _production_reader_fixture(profile, request, _good_comparison())
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, request)
    inventory = client.stable_paginated

    def read_inventory(path, *, root):
        if root == 'jobs':
            pytest.fail('Recovery must discover its two control jobs without the worker inventory')
        return inventory(path, root=root)

    monkeypatch.setattr(client, 'stable_paginated', read_inventory)
    authenticated = auth.authenticate_checkpoint_recovery_owner(
        **{**_base_kwargs(client, profile), 'download_artifact': download,
           'checkpoint_control_jobs': True})
    assert authenticated.proof.source_finalizer_job_id == 9001
    assert {job['name'] for job in authenticated.owner.jobs} == {'gate', 'finalize'}
    assert set(client.job_reads) == {9001, 9102}


def test_checkpoint_restore_authentication_keeps_full_publisher_inventory_by_default(monkeypatch):
    profile = _profile()
    request = _real_request()
    profile.source_request_sha256 = request.request_sha256
    profile.source_plan_bindings['request_sha256'] = request.request_sha256
    client, download, _ = _production_reader_fixture(profile, request, _good_comparison())
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, request)
    inventory = client.stable_paginated

    def read_inventory(path, *, root):
        result = inventory(path, root=root)
        if root == 'jobs':
            result.collection.rows += ({'id': 9300, 'name': 'engine / evaluate_a / evaluate'},)
        return result

    monkeypatch.setattr(client, 'stable_paginated', read_inventory)
    authenticated = auth.authenticate_checkpoint_recovery_owner(
        **{**_base_kwargs(client, profile), 'download_artifact': download})
    assert authenticated.owner.jobs[-1]['id'] == 9300
    assert client.job_reads == []
    assert not any('/check-suites/' in path for path in client.inventory_paths)


@pytest.mark.parametrize('case', [
    'duplicate', 'missing', 'incomplete', 'unstable', 'wrong_suite', 'wrong_app',
    'wrong_name', 'wrong_commit', 'wrong_run_url', 'wrong_repository_url',
    'wrong_job_attempt', 'wrong_job_run', 'wrong_job_commit', 'wrong_backlink',
    'changed_job', 'changed_run', 'private_repository',
])
def test_checkpoint_control_job_discovery_fails_closed(monkeypatch, case):
    profile = _profile()
    request = _real_request()
    profile.source_request_sha256 = request.request_sha256
    profile.source_plan_bindings['request_sha256'] = request.request_sha256
    client, download, _ = _production_reader_fixture(profile, request, _good_comparison())
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, request)
    inventory, get = client.stable_paginated, client.get_json
    gate_check = client.checks['gate']
    gate_job = client.control_jobs[9102]
    if case == 'wrong_suite':
        gate_check['check_suite'] = {'id': 1}
    elif case == 'wrong_app':
        gate_check['app'] = {'id': 1, 'slug': 'github-actions'}
    elif case == 'wrong_name':
        gate_check['name'] = 'another-gate'
    elif case == 'wrong_commit':
        gate_check['head_sha'] = OTHER_COMMIT
    elif case == 'wrong_run_url':
        gate_check['details_url'] = f'https://github.com/{REPOSITORY}/actions/runs/1/job/9102'
    elif case == 'wrong_repository_url':
        gate_check['details_url'] = f'https://github.com/other/repo/actions/runs/{RUN_ID}/job/9102'
    elif case == 'wrong_job_attempt':
        gate_job['run_attempt'] = 2
    elif case == 'wrong_job_run':
        gate_job['run_id'] = 1
    elif case == 'wrong_job_commit':
        gate_job['head_sha'] = OTHER_COMMIT
    elif case == 'wrong_backlink':
        gate_job['check_run_url'] = f'https://api.github.com/repos/{REPOSITORY}/check-runs/9001'

    run_reads = 0

    def read_json(path):
        nonlocal run_reads
        result, response = get(path)
        result = deepcopy(result)
        if path.endswith(f'/actions/runs/{RUN_ID}'):
            run_reads += 1
            if case == 'private_repository':
                result['repository']['private'] = True
            elif case == 'changed_run' and run_reads > 1:
                result['run_attempt'] = 2
        if case == 'changed_job' and path.endswith('/actions/jobs/9102') and len(client.job_reads) == 2:
            result['steps'] = []
        return result, response

    def read_inventory(path, *, root):
        if root == 'jobs':
            pytest.fail('Invalid compact provenance must not trigger a broad fallback')
        result = inventory(path, root=root)
        if root == 'check_runs':
            if case == 'duplicate':
                result.collection.rows *= 2
            elif case == 'missing':
                result.collection.rows = ()
            elif case == 'incomplete':
                result.collection.complete = False
            elif case == 'unstable':
                result.stable = False
        return result

    monkeypatch.setattr(client, 'get_json', read_json)
    monkeypatch.setattr(client, 'stable_paginated', read_inventory)
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_CONTROL_JOBS_INVALID'):
        auth.authenticate_checkpoint_recovery_owner(
            **{**_base_kwargs(client, profile), 'download_artifact': download,
               'checkpoint_control_jobs': True})


@pytest.mark.parametrize('case, error', [
    ('wrong_run', 'CATALOG_FAST_OWNER_PIN_MISMATCH'),
    ('duplicate', 'CATALOG_FAST_OWNER_AMBIGUOUS'),
    ('missing', 'CATALOG_CHECKPOINT_RECOVERY_OWNER_MISSING'),
    ('incomplete', 'CATALOG_FAST_OWNER_INVENTORY_INCOMPLETE'),
])
def test_pinned_recovery_owner_still_rejects_invalid_inventory(monkeypatch, case, error):
    profile = _profile()
    request = _real_request()
    profile.source_request_sha256 = request.request_sha256
    profile.source_plan_bindings['request_sha256'] = request.request_sha256
    client, download, _ = _production_reader_fixture(profile, request, _good_comparison())
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, request)
    original = client.stable_paginated

    def inventory(path, *, root):
        result = original(path, root=root)
        if path.endswith(f'/artifacts?name=catalog-fast-gate-{ISSUE}'):
            if case == 'wrong_run':
                artifact = result.collection.rows[0]
                result.collection.rows = ({**artifact, 'workflow_run': {
                    **artifact['workflow_run'], 'id': RUN_ID + 1}},)
            elif case == 'duplicate':
                result.collection.rows *= 2
            elif case == 'missing':
                result.collection.rows = ()
            else:
                result.collection.complete = False
        return result

    monkeypatch.setattr(client, 'stable_paginated', inventory)
    with pytest.raises(ValueError, match=error):
        auth.authenticate_checkpoint_recovery_owner(
            **{**_base_kwargs(client, profile), 'download_artifact': download})


@pytest.mark.parametrize('pin', [True, False, 0, -1, '35504391586'])
def test_owner_pin_rejects_invalid_values_before_io(pin):
    client = _InjectedClient(actor='unused', comparison={})
    with pytest.raises(ValueError, match='CATALOG_FAST_OWNER_LOOKUP_INVALID'):
        auth.load_fast_gate_owner(client=client, issue_number=ISSUE, request=_real_request(),
            approved_commits=frozenset({CURRENT_COMMIT}),
            download_archive=lambda _: pytest.fail('unexpected download'), pinned_owner_run_id=pin)
    assert client.calls == []


def test_authentication_returns_owner_and_stable_failure_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    client = _InjectedClient(
        actor=json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text())[
            "request_actors"
        ][0],
        comparison=_good_comparison(),
    )
    owner = _owner(profile)
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, _request())
    observed: dict[str, object] = {}

    def load_owner(**kwargs: object) -> FastGateOwnerEvidence:
        observed.update(kwargs)
        assert kwargs["approved_commits"] == frozenset({CURRENT_COMMIT})
        assert kwargs["terminal_owner_run_id"] == RUN_ID
        assert kwargs["pinned_owner_run_id"] == RUN_ID
        approve = kwargs["approve_historical_commit"]
        assert callable(approve) and approve(COMMIT) is True
        return owner

    monkeypatch.setattr(auth, "load_fast_gate_owner", load_owner)
    monkeypatch.setattr(auth, "load_owner_terminal_receipt", lambda **kwargs: None)

    authenticated = auth.authenticate_checkpoint_recovery_owner(
        **_base_kwargs(client, profile)
    )

    assert authenticated.owner is owner
    assert isinstance(authenticated.proof, CheckpointRecoveryOwnerProofV1)
    assert authenticated.proof.source_finalizer_job_id == 9001
    assert observed["issue_number"] == ISSUE
    assert CURRENT_COMMIT != COMMIT
    assert f"/repos/{REPOSITORY}/compare/{COMMIT}...{CURRENT_COMMIT}" in client.calls


@pytest.mark.parametrize(
    ("field", "value"),
    (("repository", "someone/else"), ("protected_commit_sha", "not-a-commit")),
)
def test_authentication_rejects_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    profile = _profile()
    client = _InjectedClient(actor="unused", comparison=_good_comparison())
    _patch_profile(monkeypatch, profile)
    kwargs = _base_kwargs(client, profile)
    kwargs[field] = value

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID"):
        auth.authenticate_checkpoint_recovery_owner(**kwargs)


def test_authentication_rejects_signed_request_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    client = _InjectedClient(
        actor=json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text())[
            "request_actors"
        ][0],
        comparison=_good_comparison(),
    )
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, _request(request_sha="9" * 64))

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_MISMATCH"):
        auth.authenticate_checkpoint_recovery_owner(**_base_kwargs(client, profile))


def test_authentication_rejects_non_ancestor_historical_owner_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    client = _InjectedClient(
        actor=json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text())[
            "request_actors"
        ][0],
        comparison={
            "status": "behind",
            "base_commit": {"sha": OTHER_COMMIT},
            "merge_base_commit": {"sha": OTHER_COMMIT},
        },
    )
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, _request())

    def load_owner(**kwargs: object) -> None:
        approve = kwargs["approve_historical_commit"]
        assert callable(approve) and approve(ANCESTOR) is False
        raise ValueError("CATALOG_FAST_OWNER_SOURCE_UNAPPROVED")

    monkeypatch.setattr(auth, "load_fast_gate_owner", load_owner)

    with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_SOURCE_UNAPPROVED"):
        auth.authenticate_checkpoint_recovery_owner(**_base_kwargs(client, profile))


def test_authentication_rejects_present_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    client = _InjectedClient(
        actor=json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text())[
            "request_actors"
        ][0],
        comparison=_good_comparison(),
    )
    _patch_profile(monkeypatch, profile)
    _patch_request_parser(monkeypatch, _request())
    owner = _owner(profile)
    monkeypatch.setattr(auth, "load_fast_gate_owner", lambda **kwargs: owner)
    monkeypatch.setattr(auth, "load_owner_terminal_receipt", lambda **kwargs: object())

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_TERMINAL_PRESENT"):
        auth.authenticate_checkpoint_recovery_owner(**_base_kwargs(client, profile))


def test_authentication_rejects_unapproved_issue_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    client = _InjectedClient(actor="not-the-requester-app", comparison=_good_comparison())
    _patch_profile(monkeypatch, profile)

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUESTER_INVALID"):
        auth.authenticate_checkpoint_recovery_owner(**_base_kwargs(client, profile))


def test_auth_module_does_not_import_pyarrow() -> None:
    script = """
import builtins
import sys
import types
from pathlib import Path

real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'pyarrow' or name.startswith('pyarrow.'):
        raise AssertionError('pyarrow imported')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
try:
    import __editable___aurora_1_5_0_finder as finder
    finder.MAPPING['aurora'] = str(Path.cwd())
except ImportError:
    pass
package = types.ModuleType('aurora')
package.__path__ = [str(Path.cwd())]
sys.modules['aurora'] = package
import aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
