from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts import prepare_catalog_campaign as prepare
from scripts import finalize_catalog_preparation as finalize
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1, canonical_cached_strategy_ids_sha256,
)
from tests.test_catalog_checkpoint_recovery_profile import _payload
from tests.test_catalog_checkpoint_recovery_authority import _case


def _transport(tmp_path, monkeypatch):
    cached = ('strategy-000', 'strategy-002')
    # Small orchestration fixture; the production closed profile is tested separately.
    profile = CheckpointRecoveryProfileV1.model_validate(_payload()).model_copy(update={
        'expected_result_count': 2, 'expected_total_count': 5,
        'cached_strategy_ids_sha256': canonical_cached_strategy_ids_sha256(cached),
    })
    proof = replace(_case()[3], profile_sha256=profile.profile_sha256,
                    source_request_sha256=profile.source_request_sha256,
                    source_decision_sha256=profile.source_plan_bindings['decision_sha256'])
    root = tmp_path / 'checkpoint-recovery'
    (root / 'source-plan').mkdir(parents=True)
    (root / 'checkpoints').mkdir()
    (root / 'checkpoints' / 'bytes').write_bytes(b'original checkpoint')
    source = SimpleNamespace(
        resume_index=SimpleNamespace(strategy_ids=cached, index_sha256='a' * 64,
                                     physical_result_count=2, duplicate_result_count=0),
        plan_receipt_sha256=profile.source_plan_receipt_sha256,
        science_identity_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256, checkpoint_count=120,
    )
    monkeypatch.setattr(prepare, 'validate_exact_checkpoint_profile', lambda *args: profile)
    result = SimpleNamespace(profile=profile, proof=proof, source_validation=source,
                             checkpoint_root=root / 'checkpoints', source_plan_root=root / 'source-plan')
    calls = []
    state = prepare._checkpoint_recovery_state(repo_root=tmp_path, profile=profile,
        restore_root=root, restore=lambda: (calls.append('restore') or result))
    assert calls == ['restore']
    document = prepare._checkpoint_recovery_seed_document(state)
    return profile, source, document


def test_finalize_revalidates_local_transport_without_restoring(tmp_path, monkeypatch):
    profile, source, document = _transport(tmp_path, monkeypatch)
    monkeypatch.setattr(finalize, 'load_checkpoint_recovery_profile', lambda *args: profile, raising=False)
    monkeypatch.setattr(finalize, 'validate_exact_checkpoint_profile', lambda *args: profile, raising=False)
    calls = []
    def verify(*args):
        calls.append(args)
        return source
    monkeypatch.setattr(finalize, 'verify_checkpoint_recovery_source', verify, raising=False)
    monkeypatch.setattr(finalize, 'verify_checkpoint_recovery_plan', lambda *args: None, raising=False)
    state = finalize._load_checkpoint_recovery_seed(tmp_path, tmp_path, profile.campaign_key,
        {'checkpoint_recovery': document})
    assert state['cached_strategy_ids'] == source.resume_index.strategy_ids
    assert len(calls) == 1
    assert calls[0][0] == tmp_path / 'checkpoint-recovery/source-plan'
    assert calls[0][1] == tmp_path / 'checkpoint-recovery/checkpoints'


@pytest.mark.parametrize('defect', ['binding', 'bytes', 'path', 'missing'])
def test_finalize_rejects_changed_recovery_transport(tmp_path, monkeypatch, defect):
    profile, source, document = _transport(tmp_path, monkeypatch)
    monkeypatch.setattr(finalize, 'load_checkpoint_recovery_profile', lambda *args: profile, raising=False)
    monkeypatch.setattr(finalize, 'validate_exact_checkpoint_profile', lambda *args: profile, raising=False)
    monkeypatch.setattr(finalize, 'verify_checkpoint_recovery_source', lambda *args: source, raising=False)
    monkeypatch.setattr(finalize, 'verify_checkpoint_recovery_plan', lambda *args: None, raising=False)
    if defect == 'binding':
        document['binding']['owner_proof_sha256'] = 'f' * 64
    elif defect == 'bytes':
        (tmp_path / 'checkpoint-recovery/checkpoints/bytes').write_bytes(b'changed')
    elif defect == 'path':
        document['source_plan_relative'] = '../outside'
    context = {} if defect == 'missing' else {'checkpoint_recovery': document}
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_'):
        finalize._load_checkpoint_recovery_seed(tmp_path, tmp_path, profile.campaign_key, context)


def test_canary_does_not_restore(tmp_path):
    assert prepare._checkpoint_recovery_state(repo_root=tmp_path, profile=None,
        restore_root=tmp_path, restore=lambda: pytest.fail('unexpected restore')) is None


def test_ordinary_preparation_does_not_load_historical_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, 'load_checkpoint_recovery_profile',
                        lambda *args: pytest.fail('ordinary preparation loaded historical recovery'))
    assert prepare._preparation_checkpoint_profile(tmp_path, 'sp500-optimized-catalog-v1', None) is None


@pytest.mark.parametrize('generation', [10, 9, 8])
def test_explicit_recovery_selects_closed_profile_in_order(tmp_path, monkeypatch, generation):
    calls = []
    profile = object()
    def load(root, campaign, requested):
        calls.append(requested)
        return profile if requested == generation else None
    monkeypatch.setattr(prepare, 'load_checkpoint_recovery_profile', load)
    assert prepare._preparation_checkpoint_profile(tmp_path, 'sp500-optimized-catalog-v1', lambda: None) is profile
    assert calls == list(range(10, generation - 1, -1))


def test_ordinary_finalize_without_recovery_does_not_load_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(finalize, 'load_checkpoint_recovery_profile',
                        lambda *args: pytest.fail('ordinary finalization loaded historical recovery'))
    assert finalize._load_checkpoint_recovery_seed(tmp_path, tmp_path, 'sp500-optimized-catalog-v1', {}) is None


@pytest.mark.parametrize('kind', ['file', 'directory', 'broken_symlink'])
def test_ordinary_finalize_rejects_orphan_recovery_transport(tmp_path, monkeypatch, kind):
    path = tmp_path / 'checkpoint-recovery'
    if kind == 'file':
        path.write_bytes(b'orphan')
    elif kind == 'directory':
        path.mkdir()
    else:
        try:
            path.symlink_to(tmp_path / 'absent-target', target_is_directory=True)
        except OSError:
            pytest.skip('symlink creation unavailable')
    monkeypatch.setattr(finalize, 'load_checkpoint_recovery_profile', lambda *args: None)
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_UNEXPECTED'):
        finalize._load_checkpoint_recovery_seed(tmp_path, tmp_path, 'sp500-optimized-catalog-v1', {})


def test_durable_prepared_transport_compresses_with_bounded_composed_capacity():
    from pathlib import Path
    from aurora.infra.github_performance.preflight import load_github_yaml
    from aurora.infra.sp500_megarun.catalog_prepared_artifact import MAX_ARCHIVE_BYTES
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / '.github/workflows/catalog-prepare-one.yml')
    publishers = [step for job in workflow['jobs'].values() for step in job.get('steps', [])
                  if step.get('name') == 'Publish the PREPARED receipt and bundle as durable evidence']
    assert len(publishers) == 1
    assert publishers[0]['with']['compression-level'] == 6
    assert MAX_ARCHIVE_BYTES == 96 * 1024 * 1024


def test_seed_transports_recovery_source_and_verified_plan_to_finalize():
    from pathlib import Path
    from aurora.infra.github_performance.preflight import load_github_yaml
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / '.github/workflows/catalog-prepare-one.yml')
    publisher = next(step for step in workflow['jobs']['seed']['steps']
                     if step.get('name') == 'Publish only the material needed to finalize PREPARED')
    paths = publisher['with']['path'].splitlines()
    for directory in ('checkpoint-recovery', 'sealed-plan'):
        assert '${{ runner.temp }}/catalog-preparation-seed/' + directory in paths


def test_partial_sealed_plan_preserves_recovery_binding(tmp_path, monkeypatch):
    from scripts import plan_sp500_optimized_catalog_run as planner
    from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_binding import (
        build_checkpoint_recovery_binding, verify_checkpoint_recovery_plan,
    )
    from tests.test_catalog_partial_recipe_plan import (
        test_partial_recipe_plan_seals_and_verifies_coherent_work_inputs,
    )
    profile, _, document = _transport(tmp_path, monkeypatch)
    profile = profile.model_copy(update={'science_sha256': '7' * 64})
    proof = replace(prepare.CheckpointRecoveryOwnerProofV1(**document['owner_proof']),
                    profile_sha256=profile.profile_sha256)
    writer = planner.write_sealed_global_reuse_execution_plan
    def write(**kwargs):
        kwargs['controller_binding']['checkpoint_recovery'] = build_checkpoint_recovery_binding(profile, proof)
        return writer(**kwargs)
    monkeypatch.setattr(planner, 'write_sealed_global_reuse_execution_plan', write)
    test_partial_recipe_plan_seals_and_verifies_coherent_work_inputs(
        tmp_path, warm_components=False, fully_cached=False,
    )
    verify_checkpoint_recovery_plan(tmp_path / 'sealed', profile, proof)


def test_local_revalidation_uses_real_checkpoint_source_validator(tmp_path, monkeypatch):
    import shutil
    from tests.test_catalog_checkpoint_recovery_source import _build_fixture, _verify
    fixture = _build_fixture(tmp_path, monkeypatch)
    validated = _verify(fixture)
    root = tmp_path / 'checkpoint-recovery'
    root.mkdir()
    shutil.move(str(fixture['sealed_plan']), str(root / 'source-plan'))
    shutil.move(str(fixture['checkpoint_root']), str(root / 'checkpoints'))
    profile = CheckpointRecoveryProfileV1.model_validate(_payload()).model_copy(update={
        'expected_result_count': 120, 'expected_total_count': 240,
        'science_sha256': fixture['science'], 'catalog_manifest_sha256': fixture['catalog'],
        'source_plan_bindings': fixture['bindings'],
        'source_plan_receipt_sha256': validated.plan_receipt_sha256,
        'cached_strategy_ids_sha256': canonical_cached_strategy_ids_sha256(validated.resume_index.strategy_ids),
    })
    proof = replace(_case()[3], profile_sha256=profile.profile_sha256,
                    source_request_sha256=profile.source_request_sha256)
    monkeypatch.setattr(prepare, 'validate_exact_checkpoint_profile', lambda *args: profile)
    monkeypatch.setattr(finalize, 'validate_exact_checkpoint_profile', lambda *args: profile)
    monkeypatch.setattr(finalize, 'load_checkpoint_recovery_profile', lambda *args: profile)
    # The prior fixture tests source semantics; the target seal is exercised above.
    monkeypatch.setattr(finalize, 'verify_checkpoint_recovery_plan', lambda *args: None)
    state = prepare._checkpoint_recovery_state(repo_root=tmp_path, profile=profile,
        restore_root=root, restore=lambda: SimpleNamespace(profile=profile, proof=proof,
            source_validation=validated, source_plan_root=root / 'source-plan',
            checkpoint_root=root / 'checkpoints'))
    result = finalize._load_checkpoint_recovery_seed(tmp_path, tmp_path, profile.campaign_key,
        {'checkpoint_recovery': prepare._checkpoint_recovery_seed_document(state)})
    assert len(result['cached_strategy_ids']) == 120
    assert result['resume_index_sha256'] != state['resume_index_sha256']
