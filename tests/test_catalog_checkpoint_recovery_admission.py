from types import SimpleNamespace

import pytest

from scripts import admit_catalog_fast_request as admission
from tests.test_catalog_checkpoint_recovery_authority import _case


@pytest.mark.parametrize('defect', [None, 'authentication', 'source', 'lineage'])
def test_checkpoint_admission_authenticates_before_excluding_failed_campaign(monkeypatch, tmp_path, defect):
    state, prior, item, proof, lineage = _case()
    state = state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage)
    state = state.advance_emission(intent_id=item.intent_id, state='PUBLICACION_INCIERTA',
                                   post_run_id=700, post_run_attempt=1)
    state = state.advance_emission(intent_id=item.intent_id, state='PUBLICADO', issue_number=341)
    marker = object()
    monkeypatch.setattr(admission, 'load_checkpoint_recovery_profile', lambda *args: marker)
    monkeypatch.setattr(admission, 'load_lineage_transition', lambda *args: None if defect == 'lineage' else lineage)
    calls = []

    def authenticate(**kwargs):
        calls.append(kwargs)
        if defect == 'authentication':
            raise ValueError('CATALOG_CHECKPOINT_RECOVERY_OWNER_INVALID')
        from dataclasses import replace
        return SimpleNamespace(proof=replace(proof, source_run_id=1) if defect == 'source' else proof)

    monkeypatch.setattr(admission, 'authenticate_checkpoint_recovery_owner', authenticate)
    arguments = dict(root=tmp_path, authority=state, request=item.request, issue_number=341,
                     run_id=800, client=SimpleNamespace(repository='trading-optimizer-lab-org/aurora'),
                     protected_commit='a' * 40, download_archive=lambda _: b'')
    if defect:
        with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_'):
            admission._reserve_new_fast_request(**arguments)
    else:
        profile, actual = admission._reserve_new_fast_request(**arguments)
        assert profile is marker and actual is proof
    assert len(calls) == 1
    assert calls[0]['profile'] is marker
    assert not state.campaigns[0].is_terminal
