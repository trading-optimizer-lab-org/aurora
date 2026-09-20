from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence


def _case():
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state='QUEUED', reason_code='CATALOG_FAST_PATH_ADMITTED',
        request_sha256='a' * 64, submission_key_sha256='b' * 64,
        campaign_key='sp500-optimized-catalog-v1', prepared_receipt_sha256='c' * 64,
        selected_workers=60, launch_required=True, existing_run_id=None,
        decided_at=now, expires_at=now + timedelta(minutes=30),
    )
    profile = SimpleNamespace(
        source_run_id=35504391586, source_run_attempt=1,
        source_protected_commit_sha='d12a374ab84bfb4e79bd5039343ffd5bd963c115',
        source_request_sha256='a' * 64, source_issue_number=339,
        campaign_key='sp500-optimized-catalog-v1', target_generation=8,
        profile_sha256='d' * 64,
        source_plan_bindings={'decision_sha256': decision.decision_sha256},
    )
    run = {'id': profile.source_run_id, 'run_attempt': 1,
           'head_sha': profile.source_protected_commit_sha, 'status': 'completed',
           'conclusion': 'failure', 'head_branch': 'main'}
    steps = [
        {'name': 'Fetch one bounded timing snapshot', 'status': 'completed', 'conclusion': 'failure'},
        *[{'name': name, 'status': 'completed', 'conclusion': 'skipped'} for name in (
            'Create exactly one terminal receipt',
            'Publish the terminal receipt before changing the issue',
            'Write current authority edition',
            'Publish current authority edition',
            'Verify the terminal publication before releasing the campaign',
            'Publish the terminal state and release the reservation',
        )],
    ]
    finalizer = {'id': 106062671367, 'name': 'finalize', 'run_id': profile.source_run_id,
                 'run_attempt': 1, 'head_sha': profile.source_protected_commit_sha,
                 'status': 'completed', 'conclusion': 'failure', 'steps': steps}
    return profile, FastGateOwnerEvidence(profile.source_run_id, run, decision, (finalizer,))


def _verify(profile, owner, terminal=None):
    name = 'aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner'
    assert importlib.util.find_spec(name) is not None, 'Recovery needs an explicit authenticated failure-owner boundary'
    module = importlib.import_module(name)
    return module.verify_checkpoint_failure_owner(profile=profile, owner=owner, terminal=terminal)


def test_checkpoint_owner_failure_proof_is_not_a_terminal():
    profile, owner = _case()
    proof = _verify(profile, owner)
    assert proof.source_run_id == 35504391586
    assert proof.source_run_attempt == 1
    assert proof.source_request_sha256 == 'a' * 64
    assert proof.profile_sha256 == 'd' * 64
    assert proof.evidence_kind == 'failed_owner_without_terminal'
    assert len(proof.evidence_sha256) == 64
    assert not hasattr(proof, 'terminal_receipt_sha256')
    assert _verify(profile, owner) == proof


@pytest.mark.parametrize('mutation', [
    'running', 'success', 'attempt', 'commit', 'foreign_run', 'terminal',
    'published', 'created', 'missing_step', 'duplicate_finalizer', 'finalizer_success',
    'wrong_decision', 'unlaunched',
])
def test_checkpoint_owner_failure_proof_rejects_other_states(mutation):
    profile, owner = _case()
    terminal = None
    if mutation == 'running':
        owner.run['status'] = 'in_progress'
    elif mutation == 'success':
        owner.run['conclusion'] = 'success'
    elif mutation == 'attempt':
        owner.run['run_attempt'] = 2
    elif mutation == 'commit':
        owner.run['head_sha'] = 'e' * 40
    elif mutation == 'foreign_run':
        owner.run['id'] += 1
    elif mutation == 'terminal':
        terminal = object()
    elif mutation in {'published', 'created'}:
        owner.jobs[0]['steps'][2 if mutation == 'published' else 1]['conclusion'] = 'success'
    elif mutation == 'missing_step':
        owner.jobs[0]['steps'].pop()
    elif mutation == 'duplicate_finalizer':
        owner = FastGateOwnerEvidence(owner.run_id, owner.run, owner.decision, owner.jobs * 2)
    elif mutation == 'finalizer_success':
        owner.jobs[0]['conclusion'] = 'success'
    elif mutation == 'wrong_decision':
        profile.source_plan_bindings['decision_sha256'] = 'f' * 64
    elif mutation == 'unlaunched':
        owner = FastGateOwnerEvidence(owner.run_id, owner.run, owner.decision, owner.jobs, True)
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_OWNER_INVALID'):
        _verify(profile, owner, terminal)


def test_checkpoint_owner_verification_runs_without_pyarrow():
    code = '''
import importlib.abc
import importlib.util
from pathlib import Path
import runpy
import sys
repo = Path.cwd()
class ControllerDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'pyarrow' or fullname.startswith('pyarrow.'):
            raise ModuleNotFoundError('pyarrow unavailable in controller', name=fullname)
        # A machine-wide editable install must not redirect this checkout test.
        if fullname.startswith('aurora.'):
            candidate = repo.joinpath(*fullname.split('.')[1:])
            if (candidate / '__init__.py').is_file():
                return importlib.util.spec_from_file_location(fullname, candidate / '__init__.py',
                    submodule_search_locations=[str(candidate)])
            if candidate.with_suffix('.py').is_file():
                return importlib.util.spec_from_file_location(fullname, candidate.with_suffix('.py'))
        return None
sys.meta_path.insert(0, ControllerDependencies())
spec = importlib.util.spec_from_file_location('aurora', repo / '__init__.py', submodule_search_locations=[str(repo)])
module = importlib.util.module_from_spec(spec)
sys.modules['aurora'] = module
spec.loader.exec_module(module)
fixture = runpy.run_path(str(repo / 'tests/test_catalog_checkpoint_recovery_owner.py'))
profile, owner = fixture['_case']()
proof = fixture['_verify'](profile, owner)
assert proof.evidence_kind == 'failed_owner_without_terminal'
assert Path(sys.modules['aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner'].__file__).resolve().is_relative_to(repo)
'''
    result = subprocess.run([sys.executable, '-c', code],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, check=False, timeout=60)
    assert result.returncode == 0, result.stderr
