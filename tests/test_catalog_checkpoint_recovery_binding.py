from dataclasses import replace
import json

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_binding as binding
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1, canonical_cached_strategy_ids_sha256,
)
from tests.test_catalog_checkpoint_recovery_authority import _case
from tests.test_catalog_checkpoint_recovery_profile import _payload


def _fixture(tmp_path, monkeypatch):
    all_ids = tuple(f'SCV1-{index:05d}' for index in range(37258))
    cached = all_ids[:18630]
    payload = _payload()
    payload['cached_strategy_ids_sha256'] = canonical_cached_strategy_ids_sha256(cached)
    profile = CheckpointRecoveryProfileV1.model_validate(payload)
    proof = replace(_case()[3], profile_sha256=profile.profile_sha256,
                    source_request_sha256=profile.source_request_sha256)
    work = dict(schema_version='1', all_strategy_ids=all_ids, cached_strategy_ids=cached,
                pending_strategy_ids=all_ids[18630:], active_workers=60,
                validation_opened=False, locked_opened=False)
    work['manifest_sha256'] = canonical_sha256(work)
    run = dict(work_manifest_sha256=work['manifest_sha256'], cached_recipe_count=18630,
               pending_recipe_count=18628)
    controller = {'binding': {'checkpoint_recovery': binding.build_checkpoint_recovery_binding(profile, proof)}}
    for name, value in [('resume_work_manifest.json', work), ('run_plan.json', run),
                        ('controller_binding.json', controller)]:
        (tmp_path / name).write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(binding, 'verify_sealed_global_reuse_execution_plan',
                        lambda root: {'science_sha256': profile.science_sha256})
    return profile, proof


@pytest.mark.parametrize('defect', [None, 'missing', 'proof', 'cached', 'overlap', 'count', 'boundary'])
def test_recovery_plan_requires_exact_binding_and_partition(tmp_path, monkeypatch, defect):
    profile, proof = _fixture(tmp_path, monkeypatch)
    if defect in {'missing', 'proof'}:
        path = tmp_path / 'controller_binding.json'
        payload = json.loads(path.read_text())
        if defect == 'missing':
            payload['binding'].pop('checkpoint_recovery')
        else:
            payload['binding']['checkpoint_recovery']['owner_proof_sha256'] = 'f' * 64
        path.write_text(json.dumps(payload))
    elif defect == 'count':
        path = tmp_path / 'run_plan.json'
        payload = json.loads(path.read_text())
        payload['pending_recipe_count'] = 37258
        path.write_text(json.dumps(payload))
    elif defect in {'cached', 'overlap', 'boundary'}:
        path = tmp_path / 'resume_work_manifest.json'
        payload = json.loads(path.read_text())
        if defect == 'cached':
            payload['cached_strategy_ids'][0] = 'SCV1-foreign'
        elif defect == 'overlap':
            payload['pending_strategy_ids'][0] = payload['cached_strategy_ids'][0]
        else:
            payload['validation_opened'] = True
        payload['manifest_sha256'] = canonical_sha256({k: v for k, v in payload.items() if k != 'manifest_sha256'})
        path.write_text(json.dumps(payload))
    if defect:
        with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_'):
            binding.verify_checkpoint_recovery_plan(tmp_path, profile, proof)
    else:
        assert binding.verify_checkpoint_recovery_plan(tmp_path, profile, proof) is None
