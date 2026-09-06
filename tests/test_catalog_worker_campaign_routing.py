from pathlib import Path

from aurora.infra.github_performance.preflight import load_github_yaml


def test_all_checkpoint_segments_use_verified_campaign_paths():
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / '.github/workflows/catalog-optimized-worker.yml')
    all_steps = [step for job in workflow['jobs'].values() for step in job.get('steps', [])]
    routing = [step for step in all_steps if step.get('id') == 'campaign_inputs']
    assert len(routing) == 1
    assert 'scripts/resolve_catalog_worker_inputs.py' in routing[0]['run']
    assert '--resolved-contract' in routing[0]['run']
    assert '--run-plan' in routing[0]['run']
    assert '--admission-token' in routing[0]['run']
    segments = [step for step in all_steps if step.get('id', '').startswith('compute_')]
    assert len(segments) == 8
    for step in segments:
        assert all_steps.index(routing[0]) < all_steps.index(step)
        assert step['env']['CATALOG_CAMPAIGN_CONTRACT'] == '${{ steps.campaign_inputs.outputs.campaign_contract_path }}'
        assert step['env']['CATALOG_DIRECTORY'] == '${{ steps.campaign_inputs.outputs.catalog_dir }}'
        assert step['env']['CATALOG_SELECTED_CONFIG'] == '${{ steps.campaign_inputs.outputs.selected_config_path }}'
        assert '--campaign-contract "$CATALOG_CAMPAIGN_CONTRACT"' in step['run']
        assert '--catalog-dir "$CATALOG_DIRECTORY"' in step['run']
        assert '--selected-config "$CATALOG_SELECTED_CONFIG"' in step['run']
        assert 'config/sp500_megarun_selected_dehb_13.json' not in step['run']
        assert 'config/sp500_megarun_strategy_catalog_v1' not in step['run']
