"""Runtime-checkable workload protocol and canonical Aurora service bridge."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, runtime_checkable

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointManifest,
    PilotResult,
    PreparedInputs,
    RunSpec,
    ShardDefinition,
    SmokeResult,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)


class WorkloadLoadError(RuntimeError):
    """Raised when a workload reference is unsafe or incomplete."""


class WorkloadPolicyMismatch(RuntimeError):
    """Raised before workload code runs when policy lineage conflicts."""


@runtime_checkable
class GithubWorkload(Protocol):
    def prepare(self, spec: RunSpec, output_dir: Path) -> PreparedInputs: ...

    def smoke(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> SmokeResult: ...

    def pilot(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> PilotResult: ...

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        output_path: Path,
    ) -> WorkUnitManifest: ...

    def run_shard(
        self,
        spec: RunSpec,
        shard: ShardDefinition,
        output_dir: Path,
        checkpoint: CheckpointManifest | None,
    ) -> AttemptManifest: ...

    def merge_group(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path: ...


REQUIRED_WORKLOAD_METHODS = (
    "prepare",
    "smoke",
    "pilot",
    "enumerate_units",
    "run_shard",
    "merge_group",
)


def _resolve_object(module: ModuleType, object_path: str) -> Any:
    value: Any = module
    for component in object_path.split("."):
        if not component or component.startswith("_"):
            raise WorkloadLoadError("workload object path is invalid")
        try:
            value = getattr(value, component)
        except AttributeError as exc:
            raise WorkloadLoadError(
                f"workload object does not exist: {object_path}"
            ) from exc
    return value


def load_workload(reference: str) -> GithubWorkload:
    """Load only explicit ``aurora.*:OBJECT`` workload references."""

    module_name, separator, object_path = reference.partition(":")
    if (
        not separator
        or not module_name.startswith("aurora.")
        or not object_path
    ):
        raise WorkloadLoadError(
            "workload reference must be aurora.package.module:OBJECT"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise WorkloadLoadError(
            f"cannot import workload module: {module_name}"
        ) from exc
    value = _resolve_object(module, object_path)
    if isinstance(value, type):
        try:
            value = value()
        except TypeError as exc:
            raise WorkloadLoadError(
                "workload classes must have a zero-argument constructor"
            ) from exc
    missing = tuple(
        name for name in REQUIRED_WORKLOAD_METHODS
        if not callable(getattr(value, name, None))
    )
    if missing or not isinstance(value, GithubWorkload):
        raise WorkloadLoadError(
            "workload does not implement required methods: "
            + ", ".join(missing)
        )
    return value


class CanonicalServiceHooks(Protocol):
    def runtime_output_dir(self, campaign_id: str) -> Path: ...

    def protocol_policy_hash(self) -> str: ...

    def snapshot_policy_hash(self, snapshot_hash: str) -> str | None: ...

    def feature_identities(self) -> tuple[tuple[str, str], ...]: ...

    def start_experiment(self, spec: RunSpec) -> str: ...

    def finish_experiment(self, experiment_id: str, status: str) -> None: ...

    def witness_context(
        self,
        spec: RunSpec,
        feature_identities: tuple[tuple[str, str], ...],
    ) -> AbstractContextManager[Any]: ...

    def persist_witness(self, recorder: Any) -> None: ...


@dataclass
class AuroraCanonicalServices:
    """Thin adapter over Aurora's existing stores; it creates no new format."""

    policy: Any
    snapshot_store: Any
    feature_store: Any
    experiment_tracker: Any
    runtime_paths: Any
    witness_recorder_type: Any
    witness_writer: Any

    @classmethod
    def create(cls) -> AuroraCanonicalServices:
        from aurora.core import runtime_paths
        from aurora.core.feature_store import FeatureStore
        from aurora.core.protocol_policy import ProtocolPolicy
        from aurora.core.snapshots import SnapshotStore
        from aurora.core.witness import WitnessRecorder, write_witness
        from aurora.registry.experiments import ExperimentTracker

        return cls(
            policy=ProtocolPolicy.load(),
            snapshot_store=SnapshotStore(
                root_dir=str(runtime_paths.snapshot_root())
            ),
            feature_store=FeatureStore(),
            experiment_tracker=ExperimentTracker(
                root=str(runtime_paths.cache_dir() / "experiments")
            ),
            runtime_paths=runtime_paths,
            witness_recorder_type=WitnessRecorder,
            witness_writer=write_witness,
        )

    def runtime_output_dir(self, campaign_id: str) -> Path:
        path = (
            self.runtime_paths.cache_dir()
            / "github_performance"
            / campaign_id
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def protocol_policy_hash(self) -> str:
        return str(self.policy.policy_hash)

    def snapshot_policy_hash(self, snapshot_hash: str) -> str | None:
        for snapshot in self.snapshot_store.list_snapshots():
            if snapshot.sha256 == snapshot_hash:
                return snapshot.policy_hash
        raise FileNotFoundError(f"snapshot not found: {snapshot_hash}")

    def feature_identities(self) -> tuple[tuple[str, str], ...]:
        return tuple(self.feature_store.list_features())

    def start_experiment(self, spec: RunSpec) -> str:
        return self.experiment_tracker.start_experiment(
            name=str(spec.identity["campaign_id"]),
            optimizer="github_performance",
            strategy_class=str(spec.identity["run_type"]),
            asset=",".join(str(item) for item in spec.data["required_datasets"]),
            period_start=str(spec.policy["train_start"]),
            period_end=str(spec.policy["validation_end"]),
            config=deep_thaw_json(spec),
            seed=int(spec.execution["global_seed"]),
        )

    def finish_experiment(self, experiment_id: str, status: str) -> None:
        self.experiment_tracker.finish_experiment(
            experiment_id,
            status=status,
        )

    def witness_context(
        self,
        spec: RunSpec,
        feature_identities: tuple[tuple[str, str], ...],
    ) -> AbstractContextManager[Any]:
        return self.witness_recorder_type(
            kind="github_prepare",
            seed=int(spec.execution["global_seed"]),
            policy_hash=str(spec.policy["policy_hash"]),
            snapshot_ids=(
                [str(spec.data["snapshot_hash"])]
                if spec.data["snapshot_hash"]
                else []
            ),
            input_obj={
                "spec": deep_thaw_json(spec),
                "features": feature_identities,
            },
            run_id=str(spec.identity["campaign_id"]),
        )

    def persist_witness(self, recorder: Any) -> None:
        if recorder.witness is None:
            raise RuntimeError("witness context did not produce evidence")
        self.witness_writer(
            recorder.witness,
            self.runtime_paths.audit_log_path(),
        )


def prepare_with_canonical_services(
    workload: GithubWorkload,
    spec: RunSpec,
    output_dir: Path | None = None,
    *,
    services: CanonicalServiceHooks | None = None,
) -> PreparedInputs:
    """Prepare once while enforcing Aurora's existing lineage services."""

    active_services = services or AuroraCanonicalServices.create()
    active_policy = active_services.protocol_policy_hash()
    requested_policy = str(spec.policy["policy_hash"])
    if requested_policy and requested_policy != active_policy:
        raise WorkloadPolicyMismatch(
            "spec.policy_hash does not match ProtocolPolicy"
        )
    effective_payload = deep_thaw_json(spec)
    effective_payload["policy"]["policy_hash"] = active_policy
    effective_spec = RunSpec.model_validate(effective_payload)
    snapshot_hash = str(spec.data["snapshot_hash"])
    if snapshot_hash:
        snapshot_policy = active_services.snapshot_policy_hash(snapshot_hash)
        if snapshot_policy != active_policy:
            raise WorkloadPolicyMismatch(
                "snapshot.policy_hash does not match spec.policy_hash"
            )
    canonical_root = active_services.runtime_output_dir(
        str(spec.identity["campaign_id"])
    )
    features = active_services.feature_identities()
    experiment_id = active_services.start_experiment(effective_spec)
    root = output_dir or canonical_root
    try:
        with active_services.witness_context(
            effective_spec,
            features,
        ) as recorder:
            prepared = workload.prepare(effective_spec, Path(root))
            if prepared.policy_hash != active_policy:
                raise WorkloadPolicyMismatch(
                    "prepared inputs policy hash does not match spec"
                )
            if snapshot_hash and prepared.snapshot_hash != snapshot_hash:
                raise WorkloadPolicyMismatch(
                    "prepared inputs snapshot hash does not match spec"
                )
            recorder.set_output(deep_thaw_json(prepared))
        active_services.persist_witness(recorder)
        active_services.finish_experiment(experiment_id, "completed")
        return prepared
    except BaseException:
        active_services.finish_experiment(experiment_id, "failed")
        raise


def run_shard_with_lineage_check(
    workload: GithubWorkload,
    spec: RunSpec,
    shard: ShardDefinition,
    output_dir: Path,
    checkpoint: CheckpointManifest | None,
    *,
    expected_attempt_id: str | None = None,
    expected_artifact_name: str | None = None,
) -> AttemptManifest:
    """Block mismatched shard evidence before it can enter reconciliation."""

    attempt = workload.run_shard(
        spec,
        shard,
        Path(output_dir),
        checkpoint,
    )
    expected = {
        "spec_hash": canonical_sha256(spec),
        "policy_hash": str(spec.policy["policy_hash"]),
        "snapshot_hash": str(spec.data["snapshot_hash"]),
        "code_sha": str(spec.identity["code_sha"]),
        "dependency_lock_sha256": str(
            spec.execution["dependency_lock_sha256"]
        ),
        "capacity_profile_sha256": str(
            spec.performance["capacity_profile_sha256"]
        ),
    }
    observed = {
        "spec_hash": attempt.spec_hash,
        "policy_hash": attempt.policy_hash,
        "snapshot_hash": attempt.snapshot_hash,
        "code_sha": attempt.code_sha,
        "dependency_lock_sha256": attempt.dependency_lock_sha256,
        "capacity_profile_sha256": attempt.capacity_profile_sha256,
    }
    mismatched = tuple(
        field
        for field, value in expected.items()
        if value and observed[field] != value
    )
    if mismatched:
        raise WorkloadPolicyMismatch(
            "attempt lineage mismatch: " + ", ".join(mismatched)
        )
    if (
        expected_attempt_id is not None
        and attempt.attempt_id != expected_attempt_id
    ):
        raise WorkloadPolicyMismatch("attempt_id does not match execution plan")
    if (
        expected_artifact_name is not None
        and attempt.artifact_name != expected_artifact_name
    ):
        raise WorkloadPolicyMismatch(
            "artifact_name does not match execution plan"
        )
    return attempt
