from datetime import datetime, timezone
import importlib
import importlib.util
import json
import pytest

from test_catalog_cloud_app import _make_repo, _private_key, _patch_transport, _SyntheticTransport


def test_qualification_signs_and_parses_without_publishing_science(tmp_path, monkeypatch):
    # A missing producer or any issue POST is a regression, not a fixture success.
    assert importlib.util.find_spec('scripts.qualify_catalog_cloud_origin') is not None
    producer = importlib.import_module('scripts.qualify_catalog_cloud_origin')
    root, private, _ = _make_repo(tmp_path, _private_key())
    transport = _SyntheticTransport()
    _patch_transport(monkeypatch, transport)
    receipt = producer.qualify_key(root=root, key=private, run_id=700, attempt=1,
        job_id=701, commit='a' * 40, actor_id=271768688,
        observed_at=datetime(2026, 9, 17, 16, tzinfo=timezone.utc))
    assert receipt.repository == 'trading-optimizer-lab-org/aurora'
    assert receipt.producer_run_id == 700
    assert len(receipt.signed_test_request_sha256) == 64
    assert all('/issues' not in url for _, url, _, _ in transport.calls)
    assert transport.calls[-1][0] == 'DELETE'
    assert 'PRIVATE KEY' not in receipt.model_dump_json()
    assert 'requester_attestation_b64' not in receipt.model_dump_json()


@pytest.mark.parametrize('field,value', [('GITHUB_EVENT_NAME', 'issues'),
    ('GITHUB_JOB', 'intake'), ('CATALOG_CLOUD_INTAKE_MODE', 'OPEN_REGISTERED'),
    ('GITHUB_ACTOR_ID', '123')])
def test_producer_rejects_wrong_origin_before_app_access(tmp_path, monkeypatch, field, value):
    producer = importlib.import_module('scripts.qualify_catalog_cloud_origin')
    root, _, _ = _make_repo(tmp_path, _private_key())
    (root / 'config/catalog_cloud_intake_policy_v1.json').write_text(json.dumps({
        'schema_version': '1', 'repository_id': 1232647748,
        'repository': 'trading-optimizer-lab-org/aurora', 'allowed_actor_ids': [271768688],
        'ttl_seconds': 86400, 'max_body_bytes': 1024}), encoding='utf-8')
    monkeypatch.setattr(producer, '_verify_actions_origin', lambda root, policy: 'a' * 40)
    for name, configured in {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_JOB': 'qualify',
            'CATALOG_CLOUD_INTAKE_MODE': 'OFF', 'GITHUB_ACTOR_ID': '271768688'}.items():
        monkeypatch.setenv(name, configured)
    monkeypatch.setenv(field, value)
    output = tmp_path / 'receipt.json'
    assert producer.main(['--repo-root', str(root), '--output', str(output)]) == 2
    assert not output.exists()


def test_runtime_gate_rejects_missing_locator(monkeypatch, tmp_path):
    from scripts.verify_catalog_cloud_qualification import require_cloud_qualification
    monkeypatch.delenv('CATALOG_CLOUD_QUALIFICATION_RUN_ID', raising=False)
    with pytest.raises(ValueError, match='CLOUD_QUALIFICATION_RUN_REQUIRED'):
        require_cloud_qualification(tmp_path, None, 'a' * 40)
