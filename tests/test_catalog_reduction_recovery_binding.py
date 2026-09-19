import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun import catalog_reduction_recovery_profile as recovery
from aurora.infra.sp500_megarun.catalog_prepared_bundle import materialize_prepared_catalog_plan
from aurora.tests.test_catalog_prepared_materialization import prepared_transport_fixture


@pytest.mark.parametrize("mutation", ["none", "ordinary", "profile_bytes", "missing_profile", "wrong_request"])
def test_current_sealed_profile_is_bound_to_admission(tmp_path, mutation):
    reader = getattr(recovery, "read_sealed_reduction_recovery_profile", None)
    assert callable(reader), "sealed recovery profile reader missing"
    root = Path(__file__).resolve().parents[1]
    profile = recovery.load_reduction_recovery_profiles(root)[0]
    bundle, _template, _plan, identity, _prepared = prepared_transport_fixture(tmp_path)
    target = tmp_path / "admitted"
    materialize_prepared_catalog_plan(
        bundle_dir=bundle, expected_identity=identity, request_sha256="a" * 64,
        decision_sha256="b" * 64, output_dir=target,
        reduction_recovery=None if mutation == "ordinary" else profile.model_dump(mode="json"),
    )
    if mutation == "profile_bytes":
        payload = json.loads((target / "reduction_recovery.json").read_text("utf-8"))
        payload["source_run_id"] += 1
        (target / "reduction_recovery.json").write_text(json.dumps(payload), "utf-8")
    elif mutation == "missing_profile":
        (target / "reduction_recovery.json").unlink()
    bindings = {"request_sha256": "c" * 64 if mutation == "wrong_request" else "a" * 64}
    if mutation in {"profile_bytes", "missing_profile", "wrong_request"}:
        with pytest.raises(ValueError, match="CATALOG_"):
            reader(root, target, expected_bindings=bindings)
    else:
        assert reader(root, target, expected_bindings=bindings) == (None if mutation == "ordinary" else profile)
