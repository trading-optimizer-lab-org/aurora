"""Exercise the actual recovery-action evidence expression for zero new work."""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from aurora.infra.github_performance.campaign import (
    CampaignPhase, initialize_campaign_state, transition_campaign_state,
)
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.recovery import RecoveryEvidenceError


NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _evidence(logical_count, evidence):
    initial = initialize_campaign_state(
        campaign_id='campaign-1', scientific_contract_sha256='1' * 64,
        logical_unit_manifest_sha256='2' * 64, logical_unit_count=logical_count,
        active_plan_sha256='3' * 64, authority_id='authority-1',
        request_sha256='4' * 64, protected_commit_sha='5' * 40,
        execution_protocol_sha256='6' * 64, controller_decision_sha256='7' * 64,
        component_store_manifest_sha256='8' * 64,
        failure_history_manifest_sha256=canonical_sha256([]), created_at=NOW,
    )
    state = transition_campaign_state(initial, phase=CampaignPhase.EXECUTING, created_at=NOW)
    action = yaml.safe_load((ROOT / '.github/actions/aurora-recovery-plan/action.yml').read_text('utf-8'))
    script = next(step['run'] for step in action['runs']['steps'] if step.get('id') == 'reconcile')
    body = ast.parse(script.split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]).body
    start = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'completed_unit_count'
                         for target in node.targets))
    end = next(i for i in range(start, len(body)) if isinstance(body[i], ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == 'completed_manifest_sha256'
                       for target in body[i].targets))
    namespace = dict(state=state, completed_unit_evidence=evidence,
                     canonical_sha256=canonical_sha256, RecoveryEvidenceError=RecoveryEvidenceError)
    exec(compile(ast.Module(body=body[start:end + 1], type_ignores=[]), str(ROOT / '.github/actions/aurora-recovery-plan/action.yml'), 'exec'), namespace)
    return state, namespace['completed_unit_count'], namespace['completed_manifest_sha256']


def _ready(state, count, manifest):
    return transition_campaign_state(state, phase=CampaignPhase.READY_TO_MERGE,
        completed_unit_count=count, completed_unit_manifest_sha256=manifest,
        pending_unit_count=state.logical_unit_count - count, created_at=NOW)


def test_zero_new_work_has_an_immutable_empty_manifest():
    state, count, manifest = _evidence(0, [])
    ready = _ready(state, count, manifest)
    assert ready.completed_unit_manifest_sha256 == canonical_sha256([])
    assert ready.logical_unit_count == ready.completed_unit_count == ready.pending_unit_count == 0


@pytest.mark.parametrize('logical_count,evidence', [
    (1, []), (2, [{'worker_id': 0, 'expected_strategy_count': 1}]),
])
def test_incomplete_nonempty_campaign_cannot_be_ready(logical_count, evidence):
    state, count, manifest = _evidence(logical_count, evidence)
    if not evidence:
        assert manifest is None
    with pytest.raises(ValueError, match='ready-to-merge requires every logical unit'):
        _ready(state, count, manifest)


def test_zero_new_work_rejects_unexpected_completed_units():
    with pytest.raises(RecoveryEvidenceError, match='RECOVERY_COMPLETED_EVIDENCE_EXCESS'):
        _evidence(0, [{'worker_id': 0, 'expected_strategy_count': 1}])


def test_nonempty_complete_manifest_keeps_its_hash():
    evidence = [{'worker_id': 0, 'expected_strategy_count': 1}]
    state, count, manifest = _evidence(1, evidence)
    assert _ready(state, count, manifest).completed_unit_manifest_sha256 == canonical_sha256(evidence)
