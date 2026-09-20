from __future__ import annotations

import json
from pathlib import Path
import textwrap

import pytest
import yaml


def _steps():
    workflow = yaml.safe_load(Path('.github/workflows/catalog-optimized-worker.yml').read_text())
    return next(job['steps'] for job in workflow['jobs'].values() if 'steps' in job)


def _run(step):
    code = textwrap.dedent(step['run'].split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0])
    exec(compile(code, 'actual-recipe-download-step', 'exec'), {})


@pytest.mark.parametrize('component_count,prior', [(1, False), (96, False), (96, True), (2, False)])
def test_recipe_download_uses_exact_runtime_transport(tmp_path, monkeypatch, component_count, prior):
    steps = _steps()
    selector = next((step for step in steps if step.get('id') == 'recipe_transports'), None)
    assert selector is not None, 'Recipe payload must avoid per-artifact REST downloads'
    descriptor = {
        'assignment_artifact': 'assignment.001' if component_count == 2 else 'assignment-001',
        'data_partition_artifacts': ['data-001'],
        'component_bundle_artifacts': [f'component-{i:03d}' for i in range(component_count)],
        'prior_checkpoint_chain_artifact': 'checkpoint-s02' if prior else '',
    }
    root = tmp_path / 'descriptor-bundle'
    root.mkdir()
    (root / 'recipe-descriptor.json').write_text(json.dumps(descriptor))
    output = tmp_path / 'output'
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    _run(selector)
    outputs = dict(line.split('=', 1) for line in output.read_text().splitlines())
    expected = [descriptor['assignment_artifact'], 'data-001', *descriptor['component_bundle_artifacts']]
    if prior:
        expected.append('checkpoint-s02')
    assert outputs['pattern'] == '{' + ','.join(expected) + '}'
    download = next(step for step in steps if step.get('id') == 'recipe_download')
    assert download['with']['pattern'] == '${{ steps.recipe_transports.outputs.pattern }}'
    assert 'github-token' not in download['with']
    assert download['with'].get('merge-multiple', False) is False
    payloads = tmp_path / 'recipe-payloads'
    for name in expected:
        (payloads / name).mkdir(parents=True)
        (payloads / name / 'sentinel').write_text(name)
    stage = next(step for step in steps if step.get('id') == 'stage_recipe_transports')
    _run(stage)
    assert (tmp_path / 'assignment/sentinel').read_text() == descriptor['assignment_artifact']
    assert (tmp_path / 'data/data-001/sentinel').read_text() == 'data-001'
    assert sorted(p.name for p in (tmp_path / 'components').iterdir()) == descriptor['component_bundle_artifacts']
    if prior:
        assert (tmp_path / 'prior/sentinel').read_text() == 'checkpoint-s02'


@pytest.mark.parametrize('invalid', ['*', '../escape', 'a,b', '{a,b}', 'x\ny', '', 'data-001'])
def test_recipe_download_rejects_unsafe_or_duplicate_names(tmp_path, monkeypatch, invalid):
    selector = next((step for step in _steps() if step.get('id') == 'recipe_transports'), None)
    assert selector is not None
    root = tmp_path / 'descriptor-bundle'
    root.mkdir()
    (root / 'recipe-descriptor.json').write_text(json.dumps({
        'assignment_artifact': 'assignment-001',
        'data_partition_artifacts': ['data-001'],
        'component_bundle_artifacts': [invalid],
        'prior_checkpoint_chain_artifact': '',
    }))
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    with pytest.raises(SystemExit, match='RECIPE_PAYLOAD_ARTIFACT_SET_INVALID'):
        _run(selector)


@pytest.mark.parametrize('prior', [None, False, [], 0])
def test_recipe_download_rejects_non_string_prior_checkpoint(tmp_path, monkeypatch, prior):
    selector = next(step for step in _steps() if step.get('id') == 'recipe_transports')
    root = tmp_path / 'descriptor-bundle'
    root.mkdir()
    (root / 'recipe-descriptor.json').write_text(json.dumps({
        'assignment_artifact': 'assignment-001',
        'data_partition_artifacts': ['data-001'],
        'component_bundle_artifacts': ['component-001'],
        'prior_checkpoint_chain_artifact': prior,
    }))
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    with pytest.raises(SystemExit, match='RECIPE_PAYLOAD_ARTIFACT_SET_INVALID'):
        _run(selector)


@pytest.mark.parametrize('case', ['missing', 'extra', 'flattened', 'file'])
def test_recipe_download_rejects_incomplete_or_foreign_payloads(tmp_path, monkeypatch, case):
    stage = next(step for step in _steps() if step.get('id') == 'stage_recipe_transports')
    root = tmp_path / 'descriptor-bundle'
    root.mkdir()
    (root / 'recipe-descriptor.json').write_text(json.dumps({
        'assignment_artifact': 'assignment-001',
        'data_partition_artifacts': ['data-001'],
        'component_bundle_artifacts': ['component-001'],
        'prior_checkpoint_chain_artifact': '',
    }))
    payloads = tmp_path / 'recipe-payloads'
    payloads.mkdir()
    names = ['assignment-001', 'data-001', 'component-001']
    if case == 'missing':
        names.pop()
    elif case == 'extra':
        names.append('foreign')
    elif case == 'flattened':
        names = ['manifest.json']
    for name in names:
        if case in {'file', 'flattened'}:
            (payloads / name).write_text('invalid')
        else:
            (payloads / name).mkdir()
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    with pytest.raises(SystemExit, match='RECIPE_PAYLOAD_INCOMPLETE'):
        _run(stage)
    assert not (tmp_path / 'assignment').exists()
