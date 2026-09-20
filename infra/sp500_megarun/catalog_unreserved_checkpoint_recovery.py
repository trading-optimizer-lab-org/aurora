"""GET-only proof of an expired checkpoint successor that never reserved.

The caller supplies authenticated current authority and must reauthenticate
under the authority writer lock/CAS. This proof is neither an owner proof nor
a scientific terminal, and does not itself archive, authorize, or publish.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.parse import urlencode

from pydantic import ConfigDict, Field, model_validator

from ..github_performance.contracts import canonical_sha256
from .catalog_checkpoint_recovery_auth import (
    _historical_owner_commit_approved, _load_controller_actors, _repository_root,
)
from .catalog_checkpoint_recovery_profile import CheckpointRecoveryProfileV1, validate_exact_checkpoint_profile
from .catalog_fast_path import REQUEST_MAX_AGE
from .catalog_fast_reservation import read_fast_gate_archive
from .catalog_github_snapshot import CatalogStableInventory
from .catalog_request_contract import FrozenModel, Sha256
from .catalog_run_request import parse_catalog_run_request

if TYPE_CHECKING:
    from .catalog_fast_authority import FastAuthorityStateV1

_REPOSITORY: Literal['trading-optimizer-lab-org/aurora'] = 'trading-optimizer-lab-org/aurora'
_WORKFLOW = '.github/workflows/catalog-fast-controller.yml'
_ERROR = 'CATALOG_UNRESERVED_CHECKPOINT_RECOVERY_INVALID'
_TTL = timedelta(minutes=5)


class _Reader(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...

    def stable_paginated(self, path: str, *, root: str) -> CatalogStableInventory: ...


class UnreservedCheckpointRecoveryProofV1(FrozenModel):
    """Closed observation, usable only with a fresh writer-side authentication."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)
    schema_version: Literal['1'] = '1'
    evidence_kind: Literal['expired_unreserved_checkpoint_successor'] = 'expired_unreserved_checkpoint_successor'
    repository: Literal['trading-optimizer-lab-org/aurora'] = _REPOSITORY
    campaign_key: Literal['sp500-optimized-catalog-v1']
    target_generation: Literal[8]
    authority_state_sha256: Sha256
    emission_sha256: Sha256
    failed_request_sha256: Sha256
    failed_issue_number: int = Field(ge=1)
    failed_run_id: int = Field(ge=1)
    failed_run_attempt: int = Field(ge=1, le=100)
    failed_protected_commit_sha: str = Field(pattern=r'^[0-9a-f]{40}$')
    source_owner_issue_number: int = Field(ge=1)
    source_owner_run_id: int = Field(ge=1)
    source_request_sha256: Sha256
    profile_sha256: Sha256
    runs_inventory_sha256: Sha256
    artifacts_inventory_sha256: Sha256
    attempts_sha256: Sha256
    observed_at: datetime
    expires_at: datetime
    request_expired_at: datetime

    @model_validator(mode='after')
    def _binding(self) -> 'UnreservedCheckpointRecoveryProofV1':
        times = (self.observed_at, self.expires_at, self.request_expired_at)
        if (any(t.utcoffset() != timedelta(0) for t in times)
                or self.observed_at <= self.request_expired_at
                or self.expires_at - self.observed_at != _TTL
                or self.failed_issue_number == self.source_owner_issue_number
                or self.failed_run_id == self.source_owner_run_id
                or self.failed_request_sha256 == self.source_request_sha256):
            raise ValueError(_ERROR)
        return self

    @property
    def evidence_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode='json'))


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(_ERROR)
    return value


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError(_ERROR)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(_ERROR)
    return parsed


def _inventory(client: _Reader, path: str, root: str, now: datetime) -> CatalogStableInventory:
    """Stable pagination alone cannot establish total_count or the runs cap."""
    page = path + ('&' if '?' in path else '?') + 'per_page=100'
    first, _ = client.get_json(page)
    inventory = client.stable_paginated(path, root=root)
    last, _ = client.get_json(page)
    first, last = _object(first), _object(last)
    count = first.get('total_count')
    if (type(count) is not int or count < 0 or count != last.get('total_count')
            or not isinstance(inventory, CatalogStableInventory)
            or inventory.stable is not True or inventory.collection.complete is not True
            or count != len(inventory.collection.rows)
            or first.get(root) != last.get(root)
            or first.get(root) != list(inventory.collection.rows[:100])
            or inventory.observed_at.utcoffset() != timedelta(0)
            or not now - timedelta(seconds=60) <= inventory.observed_at <= now + _TTL
            or (root == 'workflow_runs' and count >= 1000)):
        raise ValueError(_ERROR)
    ids = [row.get('id') for row in inventory.collection.rows]
    if (any(type(identifier) is not int or identifier < 1 for identifier in ids)
            or len(ids) != len(set(ids))):
        raise ValueError(_ERROR)
    return inventory


# Exact protected failure topology of the recovery writer, not the historical
# nonreserving verifier (which requires a successful gate and a skipped writer).
_GATE_STEPS = (
    (1, 'Set up job', 'success'),
    (2, 'Start the admission time budget', 'success'),
    (3, 'Check out the exact protected branch', 'success'),
    (4, 'Bind the gate to the checked-out commit', 'success'),
    (5, 'Use the controller Python family', 'success'),
    (6, 'Install only the locked controller dependencies', 'success'),
    (7, 'Fetch exactly one existing request issue', 'success'),
    (8, 'Authenticate and inspect the signed request once', 'success'),
    (9, 'Record an invalid shaped request without running anything', 'skipped'),
    (10, 'Verify the current protected authority before admission', 'success'),
    (11, 'Restore the exact current PREPARED bundle', 'success'),
    (12, 'Recover the exact verified PREPARED artifact on cache miss', 'skipped'),
    (13, 'Run the one live admission gate and materialize the hot plan', 'success'),
    (14, 'Terminate one unexpected admission failure without retrying it', 'skipped'),
    (15, 'Stage the small immutable gate evidence', 'success'),
    (16, 'Publish the one gate decision', 'success'),
    (17, 'Publish the already-materialized sealed plan', 'success'),
    (18, 'Publish authenticated checkpoint recovery PREPARED bundle', 'success'),
    (19, 'Write current authority edition', 'failure'),
    (20, 'Publish current authority edition', 'skipped'),
    (21, 'Check current authority publication', 'skipped'),
    (22, 'Recover missing authority publication', 'skipped'),
    (23, 'Verify the uploaded reservation before exposing QUEUED', 'skipped'),
    (24, 'Reserve the campaign atomically and expose QUEUED', 'skipped'),
    (25, 'Recover the original unlaunched terminal issue', 'skipped'),
    (26, 'Close one unexpected gate publication failure', 'failure'),
    (51, 'Post Use the controller Python family', 'skipped'),
    (52, 'Post Check out the exact protected branch', 'success'),
    (53, 'Complete job', 'success'),
)


def _jobs(rows: tuple[dict[str, Any], ...], run: Mapping[str, Any]) -> Mapping[str, Any]:
    if len(rows) != 3 or {row.get('name') for row in rows} != {'gate', 'engine', 'finalize'}:
        raise ValueError(_ERROR)
    gate: Mapping[str, Any] | None = None
    for row in rows:
        if (row.get('run_id') != run['id'] or row.get('run_attempt') != run['run_attempt']
                or row.get('head_sha') != run['head_sha'] or row.get('status') != 'completed'):
            raise ValueError(_ERROR)
        if row['name'] == 'gate':
            gate = row
            if row.get('conclusion') != 'failure' or not isinstance(row.get('steps'), list):
                raise ValueError(_ERROR)
            actual = tuple((step.get('number'), step.get('name'), step.get('conclusion')) for step in row['steps'])
            if actual != _GATE_STEPS or any(step.get('status') != 'completed' for step in row['steps']):
                raise ValueError(_ERROR)
        elif row.get('conclusion') != 'skipped' or row.get('steps') not in ([], None):
            raise ValueError(_ERROR)
    if gate is None:
        raise ValueError(_ERROR)
    return gate


def authenticate_unreserved_checkpoint_recovery(
    *, repo_root: Path, repository: str, protected_commit_sha: str,
    authority: FastAuthorityStateV1, profile: CheckpointRecoveryProfileV1,
    fetch_json: _Reader, download_artifact: Callable[[int], bytes], now: datetime,
) -> UnreservedCheckpointRecoveryProofV1:
    """Authenticate transport failure only; authority provenance belongs to caller.

    The current authority must be loaded through load_current_fast_authority.
    The serialized writer must repeat this read-only proof under its shared
    lock, then compare the edition/hash before publishing its archive. No
    comment, issue label, local digest, or absence of ZIP alone is authority.
    """
    from .catalog_fast_authority import FastAuthorityStateV1

    try:
        root = _repository_root(repo_root)
        if (repository != _REPOSITORY or fetch_json.repository != repository
                or not re.fullmatch(r'[0-9a-f]{40}', protected_commit_sha)
                or not isinstance(now, datetime) or now.utcoffset() != timedelta(0)):
            raise ValueError(_ERROR)
        protected = validate_exact_checkpoint_profile(root, profile)
        # Revalidate the hash and shape even when a caller used model_copy.
        current = FastAuthorityStateV1.model_validate_json(authority.model_dump_json())
        owners = [row for row in current.campaigns if row.request.campaign_key == protected.campaign_key]
        emissions = [row for row in current.emissions if row.request.campaign_key == protected.campaign_key]
        if len(owners) != 1 or len(emissions) != 1:
            raise ValueError(_ERROR)
        owner, emission = owners[0], emissions[0]
        request = emission.request
        if (owner.is_terminal or owner.generation != protected.source_generation
                or owner.owner_issue_number != protected.source_issue_number
                or owner.owner_run_id != protected.source_run_id
                or owner.request.request_sha256 != protected.source_request_sha256
                or emission.state != 'PUBLICADO' or emission.issue_number is None
                or request.launch_generation != protected.target_generation
                or request.previous_terminal_request_sha256 != owner.request.request_sha256
                or request.request_id == owner.request.request_id):
            raise ValueError(_ERROR)
        target = request.request_sha256
        visited: set[str] = set()
        recovery_hashes: set[str] = set()
        while True:
            links = [row for row in current.unreserved_superseded_intents
                     if row.successor_request_sha256 == target]
            if not links:
                break
            if len(links) != 1 or target in visited or len(visited) >= 128:
                raise ValueError(_ERROR)
            link = links[0]
            linked_request = link.emission.request
            if (link.recovery_profile_sha256 != protected.profile_sha256
                    or linked_request.campaign_key != request.campaign_key
                    or linked_request.launch_generation != request.launch_generation
                    or linked_request.previous_terminal_request_sha256 != request.previous_terminal_request_sha256):
                raise ValueError(_ERROR)
            visited.add(target)
            recovery_hashes.add(link.recovery_evidence_sha256)
            target = linked_request.request_sha256
        archives = [row for row in current.recovery_superseded_intents
                    if row.successor_request_sha256 == target]
        if (len(archives) != 1 or archives[0].emission.request != owner.request
                or archives[0].source_owner_issue_number != owner.owner_issue_number
                or archives[0].source_owner_run_id != owner.owner_run_id
                or archives[0].recovery_profile_sha256 != protected.profile_sha256
                or recovery_hashes - {archives[0].recovery_evidence_sha256}):
            raise ValueError(_ERROR)
        prefix = f'/repos/{repository}'
        issue_path = f'{prefix}/issues/{emission.issue_number}'
        issue_raw, _ = fetch_json.get_json(issue_path)
        issue = _object(issue_raw)
        actors, key = _load_controller_actors(root)
        if (type(issue.get('number')) is not int or issue['number'] != emission.issue_number
                or _object(issue.get('user')).get('login') not in actors or 'pull_request' in issue):
            raise ValueError(_ERROR)
        if parse_catalog_run_request(issue['title'], issue['body'], key) != request:
            raise ValueError(_ERROR)
        created = _time(issue.get('created_at'))
        expired = created + REQUEST_MAX_AGE
        if now <= expired:
            raise ValueError(_ERROR)
        query = urlencode({'created': '>='+issue['created_at']})
        runs_path = f'{prefix}/actions/workflows/catalog-fast-controller.yml/runs?{query}'
        runs = _inventory(fetch_json, runs_path, 'workflow_runs', now)
        candidates = []
        for row in runs.collection.rows:
            title = row.get('display_title')
            if (row.get('path') != _WORKFLOW or not isinstance(title, str)
                    or re.fullmatch(r'AURORA catalog request [1-9][0-9]*', title) is None):
                raise ValueError(_ERROR)
            if title == f'AURORA catalog request {emission.issue_number}':
                candidates.append(row)
        # Multiple controllers are ambiguous even if both currently look idle.
        if len(candidates) != 1:
            raise ValueError(_ERROR)
        indexed = candidates[0]
        run_path = f'{prefix}/actions/runs/{indexed["id"]}'
        run_raw, _ = fetch_json.get_json(run_path)
        run = _object(run_raw)
        identity = ('id', 'run_attempt', 'head_sha', 'head_branch', 'status', 'conclusion', 'path', 'event', 'display_title')
        if any(indexed.get(k) != run.get(k) for k in identity):
            raise ValueError(_ERROR)
        if (run.get('head_branch') != 'main' or run.get('status') != 'completed'
                or run.get('conclusion') != 'failure' or run.get('event') != 'issues'
                or type(run.get('run_attempt')) is not int or not 1 <= run['run_attempt'] <= 100
                or _time(run.get('created_at')) < created):
            raise ValueError(_ERROR)
        for field in ('repository', 'head_repository'):
            repo = _object(run.get(field))
            if repo.get('id') != emission.repository_id or repo.get('full_name') != repository:
                raise ValueError(_ERROR)
        commit = run['head_sha']
        if (not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit)
                or (commit != protected_commit_sha
                    and not _historical_owner_commit_approved(fetch_json, commit, protected_commit_sha))):
            raise ValueError(_ERROR)
        observations: list[tuple[str, str, CatalogStableInventory]] = [(runs_path, 'workflow_runs', runs)]
        attempts = []
        last_gate: Mapping[str, Any] = {}
        for attempt in range(1, run['run_attempt']+1):
            attempt_path = f'{run_path}/attempts/{attempt}'
            attempt_raw, _ = fetch_json.get_json(attempt_path)
            attempt_run = _object(attempt_raw)
            if (any(attempt_run.get(k) != run.get(k) for k in identity if k != 'run_attempt')
                    or attempt_run.get('run_attempt') != attempt):
                raise ValueError(_ERROR)
            jobs_path = attempt_path+'/jobs'
            jobs = _inventory(fetch_json, jobs_path, 'jobs', now)
            last_gate = _jobs(jobs.collection.rows, attempt_run)
            observations.append((jobs_path, 'jobs', jobs))
            attempts.append(dict(run=dict(attempt_run), jobs_sha256=jobs.collection.collection_sha256))
        artifacts_path = run_path+'/artifacts'
        artifacts = _inventory(fetch_json, artifacts_path, 'artifacts', now)
        observations.append((artifacts_path, 'artifacts', artifacts))
        gate_artifacts = []
        for artifact in artifacts.collection.rows:
            name = artifact.get('name')
            producer = _object(artifact.get('workflow_run'))
            if (producer.get('id') != run['id'] or producer.get('head_sha') != commit
                    or producer.get('head_branch') != 'main'
                    or producer.get('repository_id') != emission.repository_id
                    or producer.get('head_repository_id') != emission.repository_id
                    or not isinstance(name, str)):
                raise ValueError(_ERROR)
            if name == f'catalog-fast-gate-{emission.issue_number}':
                gate_artifacts.append(artifact)
            elif not name.startswith(('catalog-sealed-execution-plan-', 'catalog-checkpoint-recovery-prepared-')):
                raise ValueError(_ERROR)
        if len(gate_artifacts) != 1:
            raise ValueError(_ERROR)
        artifact = gate_artifacts[0]
        publisher = next(step for step in last_gate['steps'] if step['name'] == 'Publish the one gate decision')
        artifact_time = _time(artifact.get('created_at'))
        if (artifact.get('expired') is not False
                or type(artifact.get('size_in_bytes')) is not int or not 0 < artifact['size_in_bytes'] <= 2*1024*1024
                or not isinstance(artifact.get('digest'), str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
                or not _time(publisher.get('started_at')) <= artifact_time
                < _time(publisher.get('completed_at')) + timedelta(seconds=1)):
            raise ValueError(_ERROR)
        raw = download_artifact(artifact['id'])
        if not isinstance(raw, bytes) or len(raw) != artifact['size_in_bytes']:
            raise ValueError(_ERROR)
        decision = read_fast_gate_archive(raw, expected_sha256=artifact['digest'][7:],
            expected_request=request, expected_issue_number=emission.issue_number)
        if (not decision.launch_required or decision.existing_run_id is not None
                or decision.expires_at != expired or not created <= decision.decided_at < expired):
            raise ValueError(_ERROR)
        terminal_path = prefix+'/actions/artifacts?'+urlencode({'name': 'catalog-terminal-receipt-'+request.request_sha256})
        terminals = _inventory(fetch_json, terminal_path, 'artifacts', now)
        if terminals.collection.rows:
            raise ValueError(_ERROR)
        observations.append((terminal_path, 'artifacts', terminals))
        # Bracket the entire proof, not just individual pages: catch a rerun,
        # new controller, late artifact, or issue replacement during validation.
        for path, collection_root, before in observations:
            after = _inventory(fetch_json, path, collection_root, now)
            if after.collection.collection_sha256 != before.collection.collection_sha256:
                raise ValueError(_ERROR)
        after_run, _ = fetch_json.get_json(run_path)
        after_issue, _ = fetch_json.get_json(issue_path)
        if after_run != run_raw or after_issue != issue_raw:
            raise ValueError(_ERROR)
        return UnreservedCheckpointRecoveryProofV1(
            campaign_key=protected.campaign_key, target_generation=protected.target_generation,
            authority_state_sha256=current.state_sha256,
            emission_sha256=canonical_sha256(emission.model_dump(mode='json')),
            failed_request_sha256=request.request_sha256, failed_issue_number=emission.issue_number,
            failed_run_id=run['id'], failed_run_attempt=run['run_attempt'], failed_protected_commit_sha=commit,
            source_owner_issue_number=owner.owner_issue_number, source_owner_run_id=owner.owner_run_id,
            source_request_sha256=owner.request.request_sha256, profile_sha256=protected.profile_sha256,
            runs_inventory_sha256=runs.collection.collection_sha256,
            artifacts_inventory_sha256=canonical_sha256({
                'run_artifacts_sha256': artifacts.collection.collection_sha256,
                'terminal_artifacts_sha256': terminals.collection.collection_sha256,
            }),
            attempts_sha256=canonical_sha256({'attempts': attempts}), observed_at=now, expires_at=now+_TTL,
            request_expired_at=expired,
        )
    except (AttributeError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise ValueError(_ERROR) from exc


__all__ = ['UnreservedCheckpointRecoveryProofV1', 'authenticate_unreserved_checkpoint_recovery']
