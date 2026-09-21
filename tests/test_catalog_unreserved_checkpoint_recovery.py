"""The failed writer is not a reservation, terminal, or source-owner proof."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, GitHubGetResponse
from tests.test_catalog_checkpoint_recovery_authority import _case
from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY


REPO = "trading-optimizer-lab-org/aurora"
COMMIT = "d90ab8b63492c69a9727d9ce558a678907c15621"
RUN = 35521360637
NOW = datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc)
CREATED = "2026-09-20T18:00:00Z"
ROOT = Path(__file__).resolve().parents[1]

# Independent GitHub topology observed on run35521360637/attempt1.
STEPS = (
    (1, "Set up job", "success"),
    (2, "Start the admission time budget", "success"),
    (3, "Check out the exact protected branch", "success"),
    (4, "Bind the gate to the checked-out commit", "success"),
    (5, "Use the controller Python family", "success"),
    (6, "Install only the locked controller dependencies", "success"),
    (7, "Fetch exactly one existing request issue", "success"),
    (8, "Authenticate and inspect the signed request once", "success"),
    (9, "Record an invalid shaped request without running anything", "skipped"),
    (10, "Verify the current protected authority before admission", "success"),
    (11, "Restore the exact current PREPARED bundle", "success"),
    (12, "Recover the exact verified PREPARED artifact on cache miss", "skipped"),
    (13, "Run the one live admission gate and materialize the hot plan", "success"),
    (14, "Terminate one unexpected admission failure without retrying it", "skipped"),
    (15, "Stage the small immutable gate evidence", "success"),
    (16, "Publish the one gate decision", "success"),
    (17, "Publish the already-materialized sealed plan", "success"),
    (18, "Publish authenticated checkpoint recovery PREPARED bundle", "success"),
    (19, "Write current authority edition", "failure"),
    (20, "Publish current authority edition", "skipped"),
    (21, "Check current authority publication", "skipped"),
    (22, "Recover missing authority publication", "skipped"),
    (23, "Verify the uploaded reservation before exposing QUEUED", "skipped"),
    (24, "Reserve the campaign atomically and expose QUEUED", "skipped"),
    (25, "Recover the original unlaunched terminal issue", "skipped"),
    (26, "Close one unexpected gate publication failure", "failure"),
    (51, "Post Use the controller Python family", "skipped"),
    (52, "Post Check out the exact protected branch", "success"),
    (53, "Complete job", "success"),
)


class Transport:
    def __init__(self, item):
        self.calls = []
        self.issue = dict(number=342, id=12342, node_id="I_342", user={"login": item.origin.requester_actor},
                          title=item.title, body=item.body, created_at=CREATED, updated_at=CREATED)
        self.run = dict(id=RUN, run_attempt=1, head_sha=COMMIT, head_branch="main", status="completed",
                        conclusion="failure", path=".github/workflows/catalog-fast-controller.yml",
                        event="issues", display_title="AURORA catalog request 342", created_at=CREATED,
                        repository={"id": item.repository_id, "full_name": REPO},
                        head_repository={"id": item.repository_id, "full_name": REPO})
        self.runs = [self.run]
        self.jobs = {1: [dict(id=9000+i, name=name, run_id=RUN, run_attempt=1, head_sha=COMMIT,
                             status="completed", conclusion=conclusion, steps=steps)
                        for i, (name, conclusion, steps) in enumerate([
                            ("gate", "failure", [dict(number=n, name=name, status="completed", conclusion=c,
                                                      started_at="2026-09-20T18:01:00Z", completed_at="2026-09-20T18:02:00Z")
                                                 for n, name, c in STEPS]),
                            ("engine", "skipped", []), ("finalize", "skipped", [])]) ]}
        request = item.request
        decision = CatalogFastLaunchDecisionV1.create(
            state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED", request_sha256=request.request_sha256,
            submission_key_sha256=request.submission_key_sha256, campaign_key=request.campaign_key,
            prepared_receipt_sha256="a"*64, selected_workers=30, launch_required=True, existing_run_id=None,
            decided_at=datetime(2026, 9, 20, 18, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 9, 20, 18, 30, tzinfo=timezone.utc))
        context = dict(request=request.model_dump(mode="json"), issue_number=342)
        context["content_sha256"] = canonical_sha256(context)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("catalog-fast-request-context.json", json.dumps(context))
            z.writestr("catalog-fast-decision-v1.json", decision.model_dump_json())
        self.raw = buf.getvalue()
        self.artifacts = [dict(id=8000, name="catalog-fast-gate-342", expired=False,
            size_in_bytes=len(self.raw), digest="sha256:"+hashlib.sha256(self.raw).hexdigest(),
            created_at="2026-09-20T18:01:30Z", workflow_run=dict(id=RUN, head_sha=COMMIT, head_branch="main",
                repository_id=item.repository_id, head_repository_id=item.repository_id))]
        self.artifacts += [dict(self.artifacts[0], id=identifier, name=name+'0d72ad5b-1823-52c4-b161-b3c669172509')
                           for identifier, name in [(8002, 'catalog-sealed-execution-plan-'),
                                                    (8003, 'catalog-checkpoint-recovery-prepared-')]]
        self.terminal = []
        self.total_override = None
        self.race = False
        self.run_reads = 0
        self.ancestor = True
        self.jobs_total_override = None

    def get(self, url, headers):
        self.calls.append(url)
        parsed = urlparse(url)
        suffix = parsed.path.removeprefix('/repos/'+REPO)
        query = parse_qs(parsed.query)
        if suffix == '/issues/342':
            payload = self.issue
        elif suffix == '/actions/workflows/catalog-fast-controller.yml/runs':
            assert query.get('created') == ['>='+CREATED]
            assert 'status' not in query and 'event' not in query
            payload = dict(total_count=len(self.runs) if self.total_override is None else self.total_override, workflow_runs=self.runs)
        elif suffix == f'/actions/runs/{RUN}':
            self.run_reads += 1
            payload = dict(self.run)
            if self.race and self.run_reads > 1:
                payload.update(run_attempt=2, status='in_progress', conclusion=None)
        elif suffix.startswith(f'/actions/runs/{RUN}/attempts/'):
            attempt = int(suffix.split('/')[5])
            if suffix.endswith('/jobs'):
                payload = dict(total_count=len(self.jobs[attempt]) if self.jobs_total_override is None else self.jobs_total_override,
                               jobs=self.jobs[attempt])
            else:
                payload = dict(self.run, run_attempt=attempt)
        elif suffix == f'/actions/runs/{RUN}/artifacts':
            payload = dict(total_count=len(self.artifacts), artifacts=self.artifacts)
        elif suffix == '/actions/artifacts':
            assert query.get('name', [''])[0].startswith('catalog-terminal-receipt-')
            payload = dict(total_count=len(self.terminal), artifacts=self.terminal)
        elif suffix.startswith('/compare/'):
            source = suffix.split('/')[2].split('...')[0]
            payload = dict(status='ahead' if self.ancestor else 'diverged',
                           base_commit={'sha': source}, merge_base_commit={'sha': source})
        else:
            raise AssertionError('Unexpected GET '+url)
        body = json.dumps(payload, sort_keys=True).encode()
        return GitHubGetResponse(200, url, url,
            {'Date': 'Sun, 20 Sep 2026 20:00:00 GMT', 'ETag': hashlib.sha256(body).hexdigest()}, body)


@pytest.fixture
def case(monkeypatch):
    module = importlib.import_module('aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery')
    state, prior, item, sourceproof, lineage = _case()
    state = state.stage_checkpoint_emission(item, recovery_proof=sourceproof, lineage_transition=lineage)
    state = state.advance_emission(intent_id=item.intent_id, state='PUBLICACION_INCIERTA', post_run_id=700, post_run_attempt=1)
    state = state.advance_emission(intent_id=item.intent_id, state='PUBLICADO', issue_number=342)
    profile = SimpleNamespace(profile_sha256=sourceproof.profile_sha256, campaign_key=sourceproof.campaign_key,
        source_generation=7, target_generation=8, source_issue_number=339, source_run_id=35504391586,
        source_request_sha256=prior.request.request_sha256)
    monkeypatch.setattr(module, 'validate_exact_checkpoint_profile', lambda root, p: p)
    monkeypatch.setattr(module, '_load_controller_actors', lambda root: ((item.origin.requester_actor,), REQUESTER_TEST_PUBLIC_KEY))
    transport = Transport(state.emissions[0])
    kwargs = dict(repo_root=ROOT, repository=REPO, protected_commit_sha=COMMIT, authority=state,
                  profile=profile, fetch_json=CatalogGitHubReadOnlyClient(REPO, 'test-only', transport=transport),
                  now=NOW, download_artifact=lambda artifact_id: transport.raw if artifact_id == 8000 else b'')
    return module, transport, kwargs


def test_unreserved_auth_api_exists():
    from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_auth
    spec = importlib.util.find_spec('aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery')
    assert spec is not None, 'Missing read-only unreserved authenticator'
    assert catalog_checkpoint_recovery_auth.__file__.startswith(str(ROOT))


def test_authenticates_failed_writer_without_creating_terminal_or_sourceproof(case):
    module, transport, kwargs = case
    before = kwargs['authority'].model_dump_json()
    proof = module.authenticate_unreserved_checkpoint_recovery(**kwargs)
    assert proof.failed_issue_number == 342 and proof.failed_run_id == RUN and proof.failed_run_attempt == 1
    assert proof.source_owner_issue_number == 339 and proof.target_generation == 8
    assert proof.request_expired_at == datetime(2026, 9, 20, 18, 30, tzinfo=timezone.utc)
    assert proof.observed_at == NOW and proof.expires_at == NOW + timedelta(minutes=5)
    assert proof.authority_state_sha256 == kwargs['authority'].state_sha256
    assert proof.emission_sha256 == canonical_sha256(kwargs['authority'].emissions[0].model_dump(mode='json'))
    assert kwargs['authority'].model_dump_json() == before
    assert not any('/comments' in path for path in transport.calls)
    assert module.UnreservedCheckpointRecoveryProofV1.model_validate_json(proof.model_dump_json()) == proof
    assert len(proof.evidence_sha256) == 64


@pytest.mark.parametrize('mutation', ['signature', 'actor', 'unexpired', 'owner', 'active', 'race',
    'missing_step', 'reservation', 'engine', 'finalize', 'unknown_job', 'terminal', 'authority_artifact',
    'total_count', 'cap1000', 'foreign_commit', 'foreign_repo', 'artifact_digest', 'previous_attempt', 'alternative'])
def test_rejects_unproven_or_executed_requests(case, mutation):
    module, t, kw = case
    if mutation == 'signature': t.issue['body'] = t.issue['body'].replace('"automatic_recovery":true', '"automatic_recovery":false')
    elif mutation == 'actor': t.issue['user']['login'] = 'untrusted[bot]'
    elif mutation == 'unexpired': kw['now'] = datetime(2026, 9, 20, 18, 20, tzinfo=timezone.utc)
    elif mutation == 'owner': kw['authority'] = kw['authority'].model_copy(update={'campaigns': ()})
    elif mutation == 'active': t.run.update(status='in_progress', conclusion=None)
    elif mutation == 'race': t.race = True
    elif mutation == 'missing_step': t.jobs[1][0]['steps'].pop(23)
    elif mutation == 'reservation': t.jobs[1][0]['steps'][23]['conclusion'] = 'success'
    elif mutation in {'engine', 'finalize'}: t.jobs[1][1 if mutation == 'engine' else 2]['conclusion'] = 'success'
    elif mutation == 'unknown_job': t.jobs[1].append(dict(t.jobs[1][1], id=9999, name='engine / evaluate'))
    elif mutation == 'terminal': t.terminal = [dict(t.artifacts[0], name='catalog-terminal-receipt-'+kw['authority'].emissions[0].request.request_sha256)]
    elif mutation == 'authority_artifact': t.artifacts.append(dict(t.artifacts[0], id=8001, name='catalog-fast-authority-v1'))
    elif mutation == 'total_count': t.total_override = 2
    elif mutation == 'cap1000': t.total_override = 1000
    elif mutation == 'foreign_commit': t.run['head_sha'] = 'invalid'
    elif mutation == 'foreign_repo': t.run['head_repository']['id'] = 9
    elif mutation == 'artifact_digest': t.artifacts[0]['digest'] = 'sha256:'+'0'*64
    elif mutation == 'previous_attempt':
        t.run['run_attempt'] = 2
        t.jobs[2] = [dict(row, id=row['id']+100, run_attempt=2) for row in deepcopy(t.jobs[1])]
        t.jobs[1][0]['steps'][23]['conclusion'] = 'success'
    elif mutation == 'alternative': t.runs.append(dict(t.run, id=RUN+1, status='queued', conclusion=None))
    with pytest.raises((ValueError, RuntimeError)):
        module.authenticate_unreserved_checkpoint_recovery(**kw)


def test_proof_rejects_extra_coercion_and_naive_clock(case):
    module, _, kwargs = case
    proof = module.authenticate_unreserved_checkpoint_recovery(**kwargs)
    for updates in ({'failed_issue_number': '342'}, {'terminal': 'fake'}, {'observed_at': NOW.replace(tzinfo=None)}):
        with pytest.raises(ValueError):
            module.UnreservedCheckpointRecoveryProofV1.model_validate({**proof.model_dump(), **updates})


def test_all_attempts_are_checked_and_live_ancestor_is_accepted(case):
    module, t, kw = case
    kw['protected_commit_sha'] = 'e'*40
    t.run['run_attempt'] = 2
    t.jobs[2] = [dict(row, id=row['id']+100, run_attempt=2) for row in deepcopy(t.jobs[1])]
    proof = module.authenticate_unreserved_checkpoint_recovery(**kw)
    assert proof.failed_run_attempt == 2 and proof.failed_protected_commit_sha == COMMIT
    assert any('/attempts/1/jobs' in path for path in t.calls)
    assert any('/attempts/2/jobs' in path for path in t.calls)


def test_nonancestor_is_rejected(case):
    module, t, kw = case
    kw['protected_commit_sha'] = 'e'*40
    t.ancestor = False
    with pytest.raises(ValueError):
        module.authenticate_unreserved_checkpoint_recovery(**kw)


def test_incomplete_jobs_count_is_rejected_even_when_stable(case):
    module, t, kw = case
    t.jobs_total_override = 4
    with pytest.raises(ValueError):
        module.authenticate_unreserved_checkpoint_recovery(**kw)


def test_profile_must_exist_in_protected_config(case, monkeypatch, tmp_path):
    module, _, kw = case
    from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import validate_exact_checkpoint_profile
    monkeypatch.setattr(module, 'validate_exact_checkpoint_profile', validate_exact_checkpoint_profile)
    kw['repo_root'] = tmp_path
    with pytest.raises(ValueError):
        module.authenticate_unreserved_checkpoint_recovery(**kw)


def test_gate_artifact_cannot_be_replayed_from_another_attempt(case):
    module, t, kw = case
    t.artifacts[0]['created_at'] = '2026-09-20T17:00:00Z'
    with pytest.raises(ValueError):
        module.authenticate_unreserved_checkpoint_recovery(**kw)


@pytest.mark.parametrize('broken_link', [False, True])
def test_second_replacement_requires_intact_bounded_archive_chain(case, broken_link):
    module, _, kw = case
    from aurora.infra.sp500_megarun.catalog_fast_authority import UnreservedCheckpointSupersededIntentV1
    from tests.test_catalog_cloud_authority import emission, signed_request
    state = kw['authority']
    old = state.recovery_superseded_intents[0]
    intermediate = emission(request=signed_request(
        campaign_key=state.emissions[0].request.campaign_key, launch_generation=8,
        previous_terminal_request_sha256=old.emission.request.request_sha256,
        request_id='018f47a2-6e91-7c34-8000-000000000009'),
        intent_id='e844851d-11dd-4408-96c5-3dd7dd08eac2').advance(
            'PUBLICACION_INCIERTA', post_run_id=999, post_run_attempt=1).advance('PUBLICADO', issue_number=340)
    observation = module.authenticate_unreserved_checkpoint_recovery(**kw)
    historical_proof = module.UnreservedCheckpointRecoveryProofV1.model_validate({
        **observation.model_dump(), 'emission_sha256': canonical_sha256(intermediate.model_dump(mode='json')),
        'failed_request_sha256': intermediate.request.request_sha256, 'failed_issue_number': 340})
    link = UnreservedCheckpointSupersededIntentV1(emission=intermediate,
        authority_state_sha256=state.state_sha256, proof=historical_proof,
        recovery_profile_sha256=old.recovery_profile_sha256,
        recovery_evidence_sha256='d'*64 if broken_link else old.recovery_evidence_sha256,
        successor_request_sha256=state.emissions[0].request.request_sha256)
    values = state.model_dump(exclude={'state_sha256'})
    values['recovery_superseded_intents'] = (old.model_copy(update={'successor_request_sha256': intermediate.request.request_sha256}),)
    values['unreserved_superseded_intents'] = (link,)
    kw['authority'] = state._create(**values)
    if broken_link:
        with pytest.raises(ValueError):
            module.authenticate_unreserved_checkpoint_recovery(**kw)
    else:
        proof = module.authenticate_unreserved_checkpoint_recovery(**kw)
        assert proof.authority_state_sha256 == kw['authority'].state_sha256
