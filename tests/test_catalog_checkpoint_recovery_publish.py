from dataclasses import replace

import pytest

from aurora.infra.sp500_megarun import catalog_fast_authority_github as writer
from tests.test_catalog_checkpoint_recovery_authority import _case


@pytest.mark.parametrize('phase', ['intake-signed', 'gate'])
@pytest.mark.parametrize('proof_kind', ['valid', 'missing', 'wrong'])
def test_writer_rederives_recovery_transition_before_any_write(monkeypatch, phase, proof_kind):
    current, _, item, proof, lineage = _case()
    staged = current.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage)
    if phase == 'intake-signed':
        candidate = staged
        run_id, commit = item.producer_run_id, item.producer_commit
    else:
        current = staged.advance_emission(intent_id=item.intent_id, state='PUBLICACION_INCIERTA',
                                           post_run_id=700, post_run_attempt=1)
        current = current.advance_emission(intent_id=item.intent_id, state='PUBLICADO', issue_number=341)
        candidate = current.reserve_checkpoint_successor(request=item.request, issue_number=341,
            run_id=800, recovery_proof=proof, lineage_transition=lineage)
        run_id, commit = 800, 'a' * 40
    writes = []
    monkeypatch.setattr(writer, '_write_validated_authority', lambda **kwargs: writes.append(kwargs) or candidate)
    supplied = None if proof_kind == 'missing' else replace(proof, source_run_id=1) if proof_kind == 'wrong' else proof
    arguments = dict(current=current, candidate=candidate, expected_edit_id='edit', anchor={},
        run_id=run_id, run_attempt=1, job_id=900, phase=phase, commit=commit,
        read_edit=lambda: {}, write_body=lambda _: None, lineage_transition=lineage,
        recovery_proof=supplied)
    if proof_kind == 'valid':
        assert writer.write_current_fast_authority(**arguments) == candidate
        assert len(writes) == 1
    else:
        with pytest.raises(ValueError):
            writer.write_current_fast_authority(**arguments)
        assert not writes
