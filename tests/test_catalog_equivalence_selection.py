"""Reference selection comes from the sealed plan, never observed successes."""
import hashlib
import json

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from scripts.verify_sp500_optimized_run import verify_equivalence
from scripts.verify_catalog_terminal_science import verify
from tests.test_verify_catalog_terminal_science import _fixture, _write_json


def _rows(path, ids):
    path.write_text(''.join(json.dumps({'strategy_id': key, 'result': {'objective': value}}) + '\n'
        for key, value in ids))


@pytest.mark.parametrize('observed, equivalent', [
    ([('a', 1)], True), ([], False), ([('a', 1), ('b', 2)], False), ([('a', 9)], False),
])
def test_subset_comparison_keeps_exact_requested_coverage(tmp_path, observed, equivalent):
    reference, output = tmp_path / 'reference.jsonl', tmp_path / 'output.jsonl'
    _rows(reference, [('a', 1), ('b', 2)])
    _rows(output, observed)
    report = verify_equivalence(output, reference, expected_strategy_ids=('a',))
    assert report['equivalent'] is equivalent
    assert report['expected_count'] == 1


@pytest.mark.parametrize('ids', [(), ('a', 'a'), ('missing',)])
def test_invalid_or_missing_requested_reference_never_passes(tmp_path, ids):
    reference, output = tmp_path / 'reference.jsonl', tmp_path / 'output.jsonl'
    _rows(reference, [('a', 1)])
    _rows(output, [('a', 1)])
    with pytest.raises(ValueError, match='REFERENCE_SELECTION'):
        verify_equivalence(output, reference, expected_strategy_ids=ids)


def test_default_comparison_still_requires_the_whole_reference(tmp_path):
    reference, output = tmp_path / 'reference.jsonl', tmp_path / 'output.jsonl'
    _rows(reference, [('a', 1), ('b', 2)])
    _rows(output, [('a', 1)])
    assert verify_equivalence(output, reference)['equivalent'] is False


def test_real_science_audit_uses_sealed_ids_with_a_larger_frozen_reference(tmp_path):
    final, reference, sealed = _fixture(tmp_path)
    with (reference / 'results.jsonl').open('a') as handle:
        handle.write(json.dumps({'strategy_id': 'outside-plan', 'result': {'objective': 3}}) + '\n')
    source = json.loads((sealed / 'source_artifacts.json').read_text())
    source.pop('content_sha256')
    entry = source['payload']['source_contract']['artifacts'][0]['files'][0]
    entry['bytes'] = (reference / 'results.jsonl').stat().st_size
    entry['sha256'] = hashlib.sha256((reference / 'results.jsonl').read_bytes()).hexdigest()
    _write_json(sealed / 'source_artifacts.json', {**source, 'content_sha256': canonical_sha256(source)})
    verify(final_root=final, reference_root=reference, sealed_plan=sealed, output_dir=tmp_path / 'audit')
    report = json.loads((tmp_path / 'audit/catalog_equivalence_receipt_v1.json').read_text())
    assert report['equivalent'] is True
    assert report['expected_count'] == report['observed_count'] == 2


def test_science_audit_consumes_the_real_flat_logical_document(tmp_path):
    from scripts.plan_sp500_optimized_catalog_run import _plan_document
    from types import SimpleNamespace

    final, reference, sealed = _fixture(tmp_path)
    logical = json.loads((sealed / 'logical_recipe_manifest.json').read_text())
    # The real writer only reads these four identity attributes here.
    identity = SimpleNamespace(**{key: logical[key] for key in (
        'campaign_id', 'authority_id', 'science_sha256', 'execution_plan_sha256')})
    document = _plan_document(identity, 'logical_recipe_manifest', logical['payload'])
    _write_json(sealed / 'logical_recipe_manifest.json', document)
    verify(final_root=final, reference_root=reference, sealed_plan=sealed, output_dir=tmp_path / 'audit')
    assert (tmp_path / 'audit/catalog_terminal_science_index_v1.json').is_file()
