#!/usr/bin/env python3
"""Qualify the existing App and signer without publishing a scientific request."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.infra.sp500_megarun.catalog_cloud_app import cloud_app_session
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1, CatalogRunIntentDraftV1, canonical_model_bytes, canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_requester_broker import sign_catalog_request
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.validate_catalog_cloud_intent import _load_policy, _verify_actions_origin, _output_target


def qualify_key(*, root, key, run_id, attempt, job_id, commit, actor_id, observed_at):
    from aurora.infra.sp500_megarun.catalog_cloud_qualification import CloudQualificationReceiptV1
    # This unregistered namespace and fixed test UUID never enter authority or
    # the broker journal. Neither signed bytes nor the signature leave memory.
    digest = hashlib.sha256(b'AURORA cloud origin qualification; NOT SCIENCE').hexdigest()
    ticket = CatalogLaunchTicketV1(schema_version='1',
        request_id='00000000-0000-7000-8000-000000000001',
        campaign_key='cloud-origin-qualification-v1', launch_generation=1,
        campaign_definition_sha256=digest, prompt_sha256=digest,
        previous_terminal_request_sha256=None)
    draft = CatalogRunIntentDraftV1(**ticket.model_dump(),
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        authorization='USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN',
        free_resources_only=True, automatic_recovery=True, max_same_failure_count=3)
    with cloud_app_session(root, key) as (app, _token, public_key):
        signed = sign_catalog_request(draft=draft, private_key_pem=key)
        if parse_catalog_run_request(signed.title, signed.body, public_key) != signed.request:
            raise ValueError('CLOUD_QUALIFICATION_SIGNATURE_INVALID')
        fields = dict(schema_version='1', repository=app.config.repository,
            repository_id=1232647748, producer_run_id=run_id,
            producer_run_attempt=attempt, producer_job_id=job_id,
            producer_commit=commit, actor_id=actor_id, app_id=app.app_id,
            installation_id=app.installation_id,
            requester_public_key_sha256=app.requester_public_key_sha256,
            permissions=tuple(sorted(app.config.required_installation_permissions.items())),
            signed_test_request_sha256=signed.request.request_sha256,
            observed_at=observed_at, receipt_sha256='0' * 64)
    unsigned = CloudQualificationReceiptV1.model_construct(**fields)
    fields['receipt_sha256'] = canonical_sha256(unsigned)
    return CloudQualificationReceiptV1.model_validate(fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.repo_root.resolve(strict=True)
        policy = _load_policy(root)
        commit = _verify_actions_origin(root, policy)
        if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
                or os.environ.get('GITHUB_JOB') != 'qualify'
                or os.environ.get('CATALOG_CLOUD_INTAKE_MODE', 'OFF') not in ('', 'OFF')):
            raise ValueError('CLOUD_QUALIFICATION_ORIGIN_INVALID')
        actor = int(os.environ['GITHUB_ACTOR_ID'])
        if actor not in policy.allowed_actor_ids:
            raise ValueError('CLOUD_QUALIFICATION_ACTOR_INVALID')
        run_id, attempt = int(os.environ['GITHUB_RUN_ID']), int(os.environ['GITHUB_RUN_ATTEMPT'])
        client = CatalogGitHubReadOnlyClient(policy.repository, os.environ['GH_TOKEN'])
        run, _ = client.get_json(f'/repos/{policy.repository}/actions/runs/{run_id}/attempts/{attempt}')
        if (run.get('head_sha') != commit or run.get('head_branch') != 'main'
                or run.get('event') != 'workflow_dispatch'
                or run.get('path') != '.github/workflows/catalog-cloud-qualification.yml'
                or run.get('repository', {}).get('id') != policy.repository_id
                or run.get('actor', {}).get('id') != actor
                or run.get('triggering_actor', {}).get('id') not in policy.allowed_actor_ids):
            raise ValueError('CLOUD_QUALIFICATION_RUN_INVALID')
        jobs, _ = client.get_json(f'/repos/{policy.repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
        candidates = [row for row in jobs.get('jobs', []) if row.get('name') == 'qualify']
        if (jobs.get('total_count', 101) > 100 or len(candidates) != 1
                or candidates[0].get('head_sha') != commit
                or candidates[0].get('run_id') != run_id
                or candidates[0].get('run_attempt') != attempt):
            raise ValueError('CLOUD_QUALIFICATION_JOB_INVALID')
        _, output = _output_target(args.output)
        if output.name != 'catalog-cloud-qualification-v1.json':
            raise ValueError('CLOUD_QUALIFICATION_OUTPUT_INVALID')
        if client.observed_at is None:
            raise ValueError('CLOUD_QUALIFICATION_OBSERVATION_TIME_INVALID')
        key = os.environ.get('CATALOG_REQUESTER_PRIVATE_KEY', '').encode('utf-8')
        receipt = qualify_key(root=root, key=key, run_id=run_id, attempt=attempt,
            job_id=candidates[0]['id'], commit=commit, actor_id=actor,
            observed_at=client.observed_at)
        with output.open('xb') as stream:
            stream.write(canonical_model_bytes(receipt) + b'\n')
        print('CLOUD_QUALIFICATION_PUBLIC_RECEIPT_WRITTEN')
        return 0
    except Exception as exc:
        reason = str(exc).split(':', 1)[0]
        if not re.fullmatch(r'(?:CATALOG_|CLOUD_)[A-Z0-9_]+', reason):
            reason = 'CLOUD_QUALIFICATION_FAILED'
        print(reason, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
