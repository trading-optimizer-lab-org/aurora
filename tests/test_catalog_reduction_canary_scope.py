"""A qualification subset cannot silently relax normal selected-result coverage."""
import hashlib
import json

import pytest

from scripts import reduce_sp500_optimized_catalog_run as reducer
from scripts.build_catalog_fast_canary import write_canary_catalog
from tests.test_catalog_fast_canary import _catalog_rows, _eligible_evidence


def _fixture(tmp_path):
    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    root = tmp_path / 'catalog'
    write_canary_catalog(rows, output_dir=root, reference_recipe_hashes=reference,
        available_component_ids=components, data_contract_sha256='b' * 64,
        feature_contract_sha256='a' * 64, source_catalog_sha256='c' * 64)
    return root, hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()


def test_verified_eight_recipe_qualification_does_not_require_parent_auxiliaries(tmp_path):
    root, digest = _fixture(tmp_path)
    assert reducer.expected_selected_result_count(root / 'catalog.jsonl',
        expected_manifest_sha256=digest, qualification_only=True) == 0


def test_canary_scope_cannot_relax_a_normal_run(tmp_path):
    root, digest = _fixture(tmp_path)
    assert reducer.expected_selected_result_count(root / 'catalog.jsonl',
        expected_manifest_sha256=digest, qualification_only=False) == 13


def test_qualification_flag_alone_preserves_parent_auxiliary_requirement(tmp_path):
    root, _ = _fixture(tmp_path)
    coverage = json.loads((root / 'coverage.json').read_text())
    coverage.pop('scope')
    (root / 'coverage.json').write_text(json.dumps(coverage))
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['artifacts_sha256']['coverage.json'] = hashlib.sha256((root / 'coverage.json').read_bytes()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))
    digest = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
    assert reducer.expected_selected_result_count(root / 'catalog.jsonl',
        expected_manifest_sha256=digest, qualification_only=True) == 13


@pytest.mark.parametrize('mutation', ['manifest', 'coverage', 'catalog'])
def test_qualification_rejects_unbound_or_changed_catalog(tmp_path, mutation):
    root, digest = _fixture(tmp_path)
    filename = {'manifest': 'manifest.json', 'coverage': 'coverage.json', 'catalog': 'catalog.jsonl'}[mutation]
    with (root / filename).open('ab') as handle:
        handle.write(b' ')
    with pytest.raises(ValueError):
        reducer.expected_selected_result_count(root / 'catalog.jsonl',
            expected_manifest_sha256=digest, qualification_only=True)


def test_self_consistent_but_wrong_expected_ids_are_rejected(tmp_path):
    root, _ = _fixture(tmp_path)
    coverage = json.loads((root / 'coverage.json').read_text())
    coverage['expected_strategy_ids'][0] = 'unexpected'
    (root / 'coverage.json').write_text(json.dumps(coverage))
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['artifacts_sha256']['coverage.json'] = hashlib.sha256((root / 'coverage.json').read_bytes()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))
    digest = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='CANARY'):
        reducer.expected_selected_result_count(root / 'catalog.jsonl',
            expected_manifest_sha256=digest, qualification_only=True)
