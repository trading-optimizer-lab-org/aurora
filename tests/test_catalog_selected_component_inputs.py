"""Exercise the real worker's input selection without scientific evaluation."""
import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_sp500_optimized_recipe_worker as worker

ROOT = Path(__file__).resolve().parents[1]
SELECTED = ROOT / 'config/sp500_megarun_selected_dehb_13.json'


def _worker_inputs(rows, shard, slot, selected_config=SELECTED):
    # Execute only the production input-selection statements before store open.
    main = ast.parse(inspect.getsource(worker.main)).body[0]
    def assigns(node, name):
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets)
    start = next(i for i, node in enumerate(main.body) if assigns(node, 'by_strategy_id'))
    stop = next(i for i, node in enumerate(main.body) if assigns(node, 'store'))
    scope = dict(vars(worker), rows=rows, assigned_ids=[row['strategy_id'] for row in rows],
                 args=SimpleNamespace(shard_index=shard, selected_config=selected_config),
                 checkpoint_slot_index=slot)
    exec(compile(ast.Module(body=main.body[start:stop], type_ignores=[]), 'worker-inputs', 'exec'), scope)
    return scope


def _assigned():
    return [{'strategy_id': 'pending', 'components': [
        {'configuration_sha256': '0' * 64}, {'configuration_sha256': '1' * 64},
        {'configuration_sha256': '0' * 64}]}]


def test_selected_thirteen_survive_exact_payload_filter(tmp_path):
    selected = json.loads(SELECTED.read_text('utf-8'))
    keys = {worker.configuration_sha256(str(row['lane_id']), dict(row['configuration']))
            for row in selected}
    assert len(keys) == 13
    assert 'a61fc3b8784df006578bd455dfac9a5422b9e8b36993b6f93d645337d6cd0bcc' in keys
    scope = _worker_inputs(_assigned(), 0, 1)
    required = scope['required_source_ids']
    assert set(required) == keys | {'0' * 64, '1' * 64}
    assert required == tuple(sorted(set(required)))
    assert scope['selected_rows'] == selected

    # All components are transported, but the production payload filters them.
    all_ids = sorted(keys | {'0' * 64, '1' * 64})
    identity = {'schema_version': '1', 'component_store_manifest_sha256': '2' * 64,
                'validation_opened': False, 'locked_opened': False,
                'components': [{'source_configuration_sha256': key} for key in all_ids]}
    (tmp_path / 'component_bundle_manifest.json').write_text(json.dumps(
        dict(identity, manifest_sha256=worker.canonical_sha256(identity))), encoding='utf-8')
    store = SimpleNamespace(root=tmp_path, manifest=SimpleNamespace(
        manifest_sha256='2' * 64,
        entries=[SimpleNamespace(component_id=key, result_sha256='3' * 64) for key in all_ids]),
        get=lambda key: key)
    payload = worker._ExactComponentPayload((store,), required_source_ids=required)
    assert {payload.get(key) for key in keys} == keys
    assert payload.get('0' * 64) == '0' * 64


@pytest.mark.parametrize('shard,slot', [(1, 1), (0, 2), (9, 4)])
def test_other_workers_and_slots_keep_assigned_only(tmp_path, shard, slot):
    scope = _worker_inputs(_assigned(), shard, slot, tmp_path / 'must-not-be-read.json')
    assert scope['required_source_ids'] == ('0' * 64, '1' * 64)


def test_selected_loop_reuses_rows_loaded_before_payload_open():
    main = ast.parse(inspect.getsource(worker.main)).body[0]
    reads = [node for node in ast.walk(main) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'read_text'
             and isinstance(node.func.value, ast.Attribute)
             and node.func.value.attr == 'selected_config']
    store = next(node for node in main.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'store' for target in node.targets))
    assert len(reads) == 1
    assert reads[0].lineno < store.lineno
