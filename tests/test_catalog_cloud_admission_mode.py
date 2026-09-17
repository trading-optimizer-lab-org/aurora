import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from scripts.admit_catalog_fast_request import _require_cloud_admission_mode
from tests.test_catalog_cloud_authority import emission, signed_request


@pytest.mark.parametrize("mode", [None, "", "OFF", "unknown", "CANARY_ONLY"])
def test_cloud_sp500_requires_explicit_open_registered(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("CATALOG_CLOUD_INTAKE_MODE", raising=False)
    else:
        monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", mode)
    item = emission()
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    with pytest.raises(ValueError, match="CLOUD_INTAKE_DISABLED"):
        _require_cloud_admission_mode(authority, item.request)


def test_mode_does_not_change_legacy_authority_semantics(monkeypatch):
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", "OFF")
    _require_cloud_admission_mode(FastAuthorityStateV1.bootstrap(campaigns=()), signed_request())


def test_canary_only_rejects_unadmitted_legacy_sp500(monkeypatch):
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", "CANARY_ONLY")
    with pytest.raises(ValueError, match="CLOUD_INTAKE_DISABLED"):
        _require_cloud_admission_mode(FastAuthorityStateV1.bootstrap(campaigns=()), signed_request())


@pytest.mark.parametrize("mode", ["CANARY_ONLY", "OPEN_REGISTERED"])
def test_canary_is_allowed_in_both_active_modes(monkeypatch, mode):
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", mode)
    item = emission(request=signed_request(campaign_key="catalog-fast-canary-v1"))
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    _require_cloud_admission_mode(state, item.request)
