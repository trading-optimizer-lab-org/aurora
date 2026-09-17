import pytest

from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_cloud_authority import emission
from tests.test_catalog_cloud_intake import _validate, INTENT_ID


def test_existing_intent_returns_exact_signed_bytes():
    intent = _validate()
    item = emission(intent_id=INTENT_ID)
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    assert resolve_cloud_replay(authority, intent) == item


@pytest.mark.parametrize("field,value", [
    ("intent_issue_number", 401), ("repository_id", 22), ("actor_id", 777),
])
def test_reused_id_from_another_identity_cannot_replay(field, value):
    item = emission(intent_id=INTENT_ID, **{field: value})
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    with pytest.raises(ValueError, match="INTENT_CONFLICT"):
        resolve_cloud_replay(authority, _validate())


def test_new_intent_does_not_create_authority_state():
    authority = FastAuthorityStateV1.bootstrap(campaigns=())
    assert resolve_cloud_replay(authority, _validate()) is None
    assert authority.revision == 1 and authority.emissions == ()


def test_unknown_resume_cannot_allocate_a_new_generation():
    authority = FastAuthorityStateV1.bootstrap(campaigns=())
    intent = _validate().model_copy(update={"is_resume": True})
    with pytest.raises(ValueError, match="RESUME_UNKNOWN"):
        resolve_cloud_replay(authority, intent)
