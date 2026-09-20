"""The protected producer/admission/writer must opt in together, in one job."""
from pathlib import Path
import shlex

from aurora.infra.github_performance.preflight import load_github_yaml


def test_gate_wires_private_handoff_only_before_reservation():
    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / '.github/workflows/catalog-fast-controller.yml')
    steps = workflow['jobs']['gate']['steps']
    selected = {step.get('id'): step for step in steps}
    commands = {
        'authority': 'scripts/verify_catalog_fast_authority.py',
        'admit': 'scripts/admit_catalog_fast_request.py',
        'write_authority': 'scripts/publish_catalog_fast_authority.py',
    }
    for step_id, script in commands.items():
        arguments = shlex.split(selected[step_id]['run'].replace('\\\n', ' '))
        start = arguments.index(script)
        assert '--gate-handoff' in arguments[start:], f'{step_id} must use the same-job boundary'
    # A later verification must authenticate the newly uploaded edition remotely.
    for step_id in ('inspect_publication', 'verify_authority'):
        assert '--gate-handoff' not in shlex.split(selected[step_id]['run'])
    for step in workflow['jobs']['finalize']['steps']:
        assert '--gate-handoff' not in shlex.split(step.get('run', ''))
    for step in steps:
        if 'uses' in step:
            assert '.catalog-fast-gate-handoff' not in str(step.get('with', {}))
