from dataclasses import replace
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import CatalogCampaignDefinitionEntryV1
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH, load_checkpoint_recovery_profile,
)
from scripts.catalog_cloud_intake import _require_checkpoint_definition
from tests.test_catalog_checkpoint_recovery_authority import _case
from tests.test_catalog_checkpoint_recovery_profile import _root_with_profile


@pytest.mark.parametrize('defect', [None, 'missing', 'hash', 'size', 'profile', 'campaign'])
def test_signed_definition_binds_exact_protected_checkpoint_profile(tmp_path, defect):
    root = _root_with_profile(tmp_path)
    profile = load_checkpoint_recovery_profile(root, 'sp500-optimized-catalog-v1', 8)
    proof = replace(_case()[3], profile_sha256=profile.profile_sha256)
    row = CatalogCampaignDefinitionEntryV1.from_bytes(
        path=CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH, role='configuration',
        content=(root / CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH).read_bytes(),
    )
    if defect == 'hash':
        row = row.model_copy(update={'sha256': '0' * 64})
    elif defect == 'size':
        row = row.model_copy(update={'size_bytes': row.size_bytes + 1})
    elif defect == 'profile':
        proof = replace(proof, profile_sha256='0' * 64)
    manifest = SimpleNamespace(
        campaign_key='catalog-fast-canary-v1' if defect == 'campaign' else profile.campaign_key,
        entries=() if defect == 'missing' else (row,),
    )
    if defect:
        with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_DEFINITION_INVALID'):
            _require_checkpoint_definition(root, manifest, proof)
    else:
        _require_checkpoint_definition(root, manifest, proof)
