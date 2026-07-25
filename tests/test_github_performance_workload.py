from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType

import pytest

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    PilotResult,
    PreparedInputs,
    RunSpec,
    SmokeResult,
)
from aurora.infra.github_performance.workload import (
    WorkloadLoadError,
    WorkloadPolicyMismatch,
    load_workload,
    prepare_with_canonical_services,
)
from github_performance_helpers import minimal_valid_spec


class _Recorder:
    witness = object()

    def set_output(self, output) -> None:
        self.output = output


class CompleteWorkload:
    def __init__(self) -> None:
        self.prepare_calls = 0

    def prepare(self, spec, output_dir):
        self.prepare_calls += 1
        return PreparedInputs(
            manifest_path="manifest.parquet",
            manifest_sha256="1" * 64,
            snapshot_hash=str(spec.data["snapshot_hash"]),
            policy_hash=str(spec.policy["policy_hash"]),
            artifact_names=("prepared-inputs",),
        )

    def smoke(self, spec, prepared):
        return SmokeResult(
            passed=True,
            output_sha256="2" * 64,
            reason_codes=(),
        )

    def pilot(self, spec, prepared):
        return PilotResult(
            queue_seconds=1,
            setup_seconds=1,
            transfer_fixed_seconds=1,
            transfer_per_wave_seconds=1,
            checkpoint_seconds=1,
            merge_fixed_seconds=1,
            merge_per_shard_seconds=1,
            verify_seconds=1,
            unit_seconds_p50=1,
            unit_seconds_p95=1,
            usable_parallelism=1,
        )

    def enumerate_units(self, spec, prepared, output_path):
        raise NotImplementedError

    def run_shard(self, spec, shard, output_dir, checkpoint):
        raise NotImplementedError

    def merge_group(self, inputs, output_dir):
        raise NotImplementedError


class FakeServices:
    def __init__(self, policy_hash: str) -> None:
        self.policy_hash = policy_hash
        self.calls: list[str] = []
        self.recorder = _Recorder()

    def runtime_output_dir(self, campaign_id):
        self.calls.append("runtime_paths")
        return Path("unused")

    def protocol_policy_hash(self):
        self.calls.append("policy")
        return self.policy_hash

    def snapshot_policy_hash(self, snapshot_hash):
        self.calls.append("snapshot")
        return self.policy_hash

    def feature_identities(self):
        self.calls.append("features")
        return (("feature", "1"),)

    def start_experiment(self, spec):
        self.calls.append("experiment_start")
        return "experiment"

    def finish_experiment(self, experiment_id, status):
        self.calls.append(f"experiment_finish:{status}")

    def witness_context(self, spec, feature_identities):
        self.calls.append("witness")
        return nullcontext(self.recorder)

    def persist_witness(self, recorder):
        self.calls.append("witness_persist")


def _resolved_spec() -> RunSpec:
    payload = minimal_valid_spec()
    payload["policy"]["policy_hash"] = "a" * 64
    payload["data"]["snapshot_hash"] = "b" * 64
    return RunSpec.model_validate(payload)


def test_load_workload_rejects_module_outside_aurora() -> None:
    with pytest.raises(WorkloadLoadError, match="aurora"):
        load_workload("tests.fake:WORKLOAD")


def test_load_workload_accepts_complete_aurora_object(
    monkeypatch,
) -> None:
    module = ModuleType("aurora.fake_github_workload")
    module.WORKLOAD = CompleteWorkload()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    loaded = load_workload(f"{module.__name__}:WORKLOAD")
    assert isinstance(loaded, CompleteWorkload)


def test_prepare_uses_each_canonical_service_once(tmp_path: Path) -> None:
    spec = _resolved_spec()
    services = FakeServices("a" * 64)
    workload = CompleteWorkload()
    prepared = prepare_with_canonical_services(
        workload,
        spec,
        tmp_path,
        services=services,
    )
    assert prepared.policy_hash == "a" * 64
    assert workload.prepare_calls == 1
    assert services.calls == [
        "policy",
        "snapshot",
        "runtime_paths",
        "features",
        "experiment_start",
        "witness",
        "witness_persist",
        "experiment_finish:completed",
    ]


def test_policy_mismatch_blocks_before_workload(tmp_path: Path) -> None:
    workload = CompleteWorkload()
    services = FakeServices("f" * 64)
    with pytest.raises(WorkloadPolicyMismatch, match="ProtocolPolicy"):
        prepare_with_canonical_services(
            workload,
            _resolved_spec(),
            tmp_path,
            services=services,
        )
    assert workload.prepare_calls == 0
    assert services.calls == ["policy"]
