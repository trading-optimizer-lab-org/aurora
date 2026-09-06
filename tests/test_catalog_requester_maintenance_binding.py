"""An application update must not rewrite historical bootstrap success."""
from datetime import datetime, timezone
import hashlib

import pytest

from infra.sp500_megarun.catalog_bootstrap_finalizer import (
    CatalogBootstrapObservedProductionSealV1, canonical_ready_receipt_bytes,
    complete_sealed_bootstrap, finalize_bootstrap,
)
from infra.sp500_megarun.catalog_requester import CatalogRequesterProductionSealV1
from tests.test_catalog_bootstrap_end_to_end import complete_evidence, _production_seal


def _inputs():
    ready = finalize_bootstrap(complete_evidence())
    old = _production_seal(ready)
    new = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="f" * 40,
        bootstrap_receipt_sha256=hashlib.sha256(canonical_ready_receipt_bytes(ready)).hexdigest(),
        requester_client_application_sha256="3" * 64,
        requester_broker_application_sha256="4" * 64,
        sealed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )
    return ready, old, CatalogBootstrapObservedProductionSealV1.model_validate(new.model_dump(mode="json"))


def test_maintenance_binds_new_apps_without_fabricating_another_ready():
    from infra.sp500_megarun.catalog_bootstrap_finalizer import complete_requester_maintenance
    ready, old, new = _inputs()
    original = canonical_ready_receipt_bytes(ready)
    result = complete_requester_maintenance(
        ready, old, new, expected_commit_sha="f" * 40,
        client_application_sha256="3" * 64, broker_application_sha256="4" * 64,
    )
    assert result.result == "UPDATED"
    assert result.verification_scope == "APPLICATION_BINDING_ONLY"
    assert result.bootstrap_commit_sha == "a" * 40
    assert result.protected_commit_sha == "f" * 40
    assert result.previous_production_seal_sha256 == old.production_seal_sha256
    assert result.production_seal_sha256 == new.production_seal_sha256
    assert canonical_ready_receipt_bytes(ready) == original
    # The original bootstrap contract remains strict; this is NOT a new READY.
    with pytest.raises(ValueError, match="CATALOG_BOOTSTRAP_PRODUCTION_SEAL_INVALID"):
        complete_sealed_bootstrap(ready, new)


@pytest.mark.parametrize("fault", ["old_seal", "new_seal", "commit", "client", "broker", "bootstrap"])
def test_mismatching_maintenance_evidence_is_rejected(fault):
    from infra.sp500_megarun.catalog_bootstrap_finalizer import complete_requester_maintenance
    ready, old, new = _inputs()
    commit, client, broker = "f" * 40, "3" * 64, "4" * 64
    if fault == "old_seal":
        old = old.model_copy(update={"production_seal_sha256": "0" * 64})
    elif fault == "new_seal":
        new = new.model_copy(update={"production_seal_sha256": "0" * 64})
    elif fault == "commit":
        commit = "e" * 40
    elif fault == "client":
        client = "5" * 64
    elif fault == "broker":
        broker = "6" * 64
    else:
        ready = ready.model_copy(update={"protected_commit_sha": "b" * 40})
    with pytest.raises(ValueError):
        complete_requester_maintenance(ready, old, new, expected_commit_sha=commit,
                                      client_application_sha256=client, broker_application_sha256=broker)


def test_second_update_uses_only_last_protected_receipt_and_preserves_bootstrap():
    from infra.sp500_megarun.catalog_bootstrap_finalizer import complete_requester_maintenance
    ready, old, current = _inputs()
    previous = complete_requester_maintenance(ready, old, current, expected_commit_sha="f" * 40,
                                            client_application_sha256="3" * 64, broker_application_sha256="4" * 64)
    following = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="e" * 40, bootstrap_receipt_sha256=current.bootstrap_receipt_sha256,
        requester_client_application_sha256="5" * 64, requester_broker_application_sha256="6" * 64,
        sealed_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )
    next_seal = CatalogBootstrapObservedProductionSealV1.model_validate(following.model_dump(mode="json"))
    result = complete_requester_maintenance(ready, current, next_seal, expected_commit_sha="e" * 40,
                                          client_application_sha256="5" * 64, broker_application_sha256="6" * 64,
                                          previous_maintenance=previous)
    assert result.bootstrap_commit_sha == "a" * 40
    assert result.protected_commit_sha == "e" * 40
    assert result.previous_production_seal_sha256 == current.production_seal_sha256
    assert result.result == "UPDATED"
    with pytest.raises(ValueError, match="CATALOG_MAINTENANCE_RECEIPT_HASH_INVALID"):
        complete_requester_maintenance(ready, current, next_seal, expected_commit_sha="e" * 40,
                                      client_application_sha256="5" * 64, broker_application_sha256="6" * 64,
                                      previous_maintenance=previous.model_copy(update={"protected_commit_sha": "0" * 40}))
    with pytest.raises(ValueError, match="CATALOG_MAINTENANCE_PREDECESSOR_INVALID"):
        complete_requester_maintenance(ready, old, next_seal, expected_commit_sha="e" * 40,
                                      client_application_sha256="5" * 64, broker_application_sha256="6" * 64,
                                      previous_maintenance=previous)
