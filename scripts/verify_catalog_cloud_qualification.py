"""Read-only origin gate. The configured run ID is a locator, not authority."""
import os
import re


def require_cloud_qualification(root, client, commit):
    from aurora.infra.sp500_megarun.catalog_cloud_qualification import verify_cloud_qualification
    from scripts.validate_catalog_cloud_intent import _load_policy, _strict_json_file
    run_id = os.environ.get('CATALOG_CLOUD_QUALIFICATION_RUN_ID', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run_id):
        raise ValueError('CLOUD_QUALIFICATION_RUN_REQUIRED')
    policy = _load_policy(root)
    actors = _strict_json_file(root / 'config/catalog_controller_actors_v1.json')
    return verify_cloud_qualification(client, run_id=int(run_id),
        expected_commit=commit,
        expected_public_key_sha256=actors['requester_public_key_sha256'],
        allowed_actor_ids=tuple(policy.allowed_actor_ids))
