from __future__ import annotations

from pathlib import Path

import pytest

from aurora.infra.github_performance.adapter import (
    Phase1CompatibilityAdapter,
    StableWorkloadAdapter,
    adapt_workload,
)
from aurora.infra.github_performance.contracts import (
    PreparedInputs,
    RunSpec,
    WorkUnit,
)
from aurora.infra.github_performance.workload import WorkloadLoadError
from github_performance_helpers import minimal_valid_spec


class LegacyWorkload:
    def __init__(self) -> None:
        self.prepare_calls = 0

    def prepare(self, spec, output_dir):
        self.prepare_calls += 1
        return PreparedInputs(
            manifest_path=str(Path(output_dir) / "manifest.json"),
            manifest_sha256="1" * 64,
            snapshot_hash=str(spec.data["snapshot_hash"]),
            policy_hash=str(spec.policy["policy_hash"]),
            artifact_names=("manifest.json",),
        )

    def smoke(self, spec, prepared):
        raise NotImplementedError

    def pilot(self, spec, prepared):
        raise NotImplementedError

    def enumerate_units(self, spec, prepared, output_path):
        return "legacy-units"

    def run_shard(self, spec, shard, output_dir, checkpoint):
        return "legacy-attempt"

    def merge_group(self, inputs, output_dir):
        return Path(output_dir) / "legacy-merge.parquet"


class NativeWorkload:
    def describe_contract(self):
        return {
            "name": "native",
            "scientific_contract": {"causal": True},
        }

    def prepare_shared_inputs(self, spec, output_dir):
        return "native-prepared"

    def enumerate_units(self, spec, prepared, output_path):
        return "native-units"

    def estimate_unit_cost(self, spec, prepared, unit):
        return 3.5

    def execute_unit(self, spec, prepared, unit, output_dir):
        return "native-result"

    def verify_unit(self, spec, unit, result):
        return "native-verification"

    def merge_outputs(self, inputs, output_dir):
        return "native-merge"


class IdentityDroppingWorkload(NativeWorkload):
    def describe_contract(self):
        return {
            "name": "identity-dropping",
            "scientific_contract": {"causal": True},
            "original_candidate_id_preserved": False,
        }


def _spec() -> RunSpec:
    payload = minimal_valid_spec()
    payload["policy"]["policy_hash"] = "a" * 64
    payload["data"]["snapshot_hash"] = "b" * 64
    return RunSpec.model_validate(payload)


def _unit() -> WorkUnit:
    return WorkUnit(
        unit_key="unit-001",
        estimated_seconds=2.5,
        payload_ref='{"window":20}',
        payload_sha256="c" * 64,
    )


def test_phase1_workload_gets_stable_compatibility_adapter(
    tmp_path: Path,
) -> None:
    legacy = LegacyWorkload()
    adapter = adapt_workload(legacy)

    assert isinstance(adapter, Phase1CompatibilityAdapter)
    contract = adapter.describe_contract()
    assert contract.interface_kind == "phase1_compatibility"
    assert contract.adapter_version == "1"
    assert contract.original_candidate_id_preserved is True
    prepared = adapter.prepare_shared_inputs(_spec(), tmp_path)
    assert prepared.policy_hash == "a" * 64
    assert legacy.prepare_calls == 1
    assert adapter.estimate_unit_cost(_spec(), prepared, _unit()) == 2.5
    assert (
        adapter.enumerate_units(
            _spec(),
            prepared,
            tmp_path / "units.parquet",
        )
        == "legacy-units"
    )
    assert (
        adapter.merge_outputs((tmp_path / "a",), tmp_path)
        == tmp_path / "legacy-merge.parquet"
    )


def test_native_phase2_workload_delegates_every_stable_method(
    tmp_path: Path,
) -> None:
    adapter = adapt_workload(NativeWorkload())

    assert isinstance(adapter, StableWorkloadAdapter)
    assert not isinstance(adapter, Phase1CompatibilityAdapter)
    contract = adapter.describe_contract()
    assert contract.interface_kind == "phase2_native"
    assert contract.scientific_contract == {"causal": True}
    prepared = adapter.prepare_shared_inputs(_spec(), tmp_path)
    assert prepared == "native-prepared"
    assert (
        adapter.enumerate_units(
            _spec(),
            prepared,
            tmp_path / "units.parquet",
        )
        == "native-units"
    )
    assert adapter.estimate_unit_cost(
        _spec(),
        prepared,
        _unit(),
    ) == 3.5
    result = adapter.execute_unit(
        _spec(),
        prepared,
        _unit(),
        tmp_path,
    )
    assert result == "native-result"
    assert adapter.verify_unit(_spec(), _unit(), result) == (
        "native-verification"
    )
    assert adapter.merge_outputs((tmp_path / "a",), tmp_path) == (
        "native-merge"
    )


def test_native_phase2_workload_cannot_drop_candidate_identity() -> None:
    adapter = adapt_workload(IdentityDroppingWorkload())

    with pytest.raises(
        WorkloadLoadError,
        match="must preserve candidate identities",
    ):
        adapter.describe_contract()
