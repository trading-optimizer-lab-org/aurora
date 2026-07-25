"""Exact content-addressed computation DAGs and shared intermediates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
    deep_freeze_json,
    deep_thaw_json,
)


class GraphCycleError(RuntimeError):
    """Raised when a computation graph is not acyclic."""


class SharedIntermediateConflict(RuntimeError):
    """Raised when content-addressed bytes are missing or inconsistent."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ComputationNode(FrozenModel):
    """One scientifically identified operation in the shared DAG."""

    operation: str = Field(min_length=1)
    implementation_version: str = Field(min_length=1)
    input_hashes: tuple[Sha256, ...] = ()
    parameters: Mapping[str, Any]
    policy_hash: Sha256
    snapshot_hash: Sha256
    output_schema: str = Field(min_length=1)
    content_hash: Sha256

    @field_validator("parameters", mode="after")
    @classmethod
    def _freeze_parameters(
        cls,
        value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return deep_freeze_json(value)

    @classmethod
    def create(
        cls,
        *,
        operation: str,
        implementation_version: str,
        parameters: Mapping[str, Any],
        policy_hash: str,
        snapshot_hash: str,
        output_schema: str,
        input_hashes: Sequence[str] = (),
    ) -> ComputationNode:
        """Create a node whose hash excludes all candidate aliases."""

        identity = {
            "operation": operation,
            "implementation_version": implementation_version,
            "input_hashes": list(input_hashes),
            "parameters": parameters,
            "policy_hash": policy_hash,
            "snapshot_hash": snapshot_hash,
            "output_schema": output_schema,
        }
        return cls(
            **identity,
            content_hash=canonical_sha256(identity),
        )


class ComputationGraph(FrozenModel):
    """A complete exact DAG with candidate-to-terminal traceability."""

    schema_version: Literal["1"] = "1"
    nodes: tuple[ComputationNode, ...]
    candidate_terminal_hashes: Mapping[str, Sha256] = Field(
        default_factory=dict
    )

    @field_validator("candidate_terminal_hashes", mode="after")
    @classmethod
    def _freeze_candidates(
        cls,
        value: Mapping[str, str],
    ) -> Mapping[str, str]:
        return deep_freeze_json(value)

    @model_validator(mode="after")
    def _validate_graph(self) -> ComputationGraph:
        node_hashes = [node.content_hash for node in self.nodes]
        if len(node_hashes) != len(set(node_hashes)):
            raise ValueError("computation graph contains duplicate node hashes")
        available = set(node_hashes)
        for node in self.nodes:
            missing = set(node.input_hashes).difference(available)
            if missing:
                raise ValueError(
                    "computation graph has missing dependency: "
                    + ",".join(sorted(missing))
                )
        missing_terminals = set(
            self.candidate_terminal_hashes.values()
        ).difference(available)
        if missing_terminals:
            raise ValueError(
                "candidate terminal is not present in graph: "
                + ",".join(sorted(missing_terminals))
            )
        self.topological_order()
        return self

    def topological_order(self) -> tuple[ComputationNode, ...]:
        """Return deterministic dependency order or fail on a cycle."""

        by_hash = {node.content_hash: node for node in self.nodes}
        indegree = {
            node.content_hash: len(node.input_hashes)
            for node in self.nodes
        }
        dependants: dict[str, list[str]] = {
            node_hash: [] for node_hash in by_hash
        }
        for node in self.nodes:
            for dependency in node.input_hashes:
                if dependency not in by_hash:
                    raise ValueError(
                        f"computation graph has missing dependency: {dependency}"
                    )
                dependants[dependency].append(node.content_hash)
        ready = sorted(
            node_hash
            for node_hash, count in indegree.items()
            if count == 0
        )
        ordered: list[ComputationNode] = []
        while ready:
            node_hash = ready.pop(0)
            ordered.append(by_hash[node_hash])
            for dependant in sorted(dependants[node_hash]):
                indegree[dependant] -= 1
                if indegree[dependant] == 0:
                    ready.append(dependant)
                    ready.sort()
        if len(ordered) != len(self.nodes):
            raise GraphCycleError("computation graph contains a cycle")
        return tuple(ordered)


class ComputationGraphBuilder:
    """Deduplicate only nodes with identical canonical identities."""

    def __init__(self, *, policy_hash: str, snapshot_hash: str) -> None:
        self._policy_hash = policy_hash
        self._snapshot_hash = snapshot_hash
        self._nodes: dict[str, ComputationNode] = {}
        self._candidates: dict[str, str] = {}

    def add_node(
        self,
        *,
        operation: str,
        implementation_version: str,
        parameters: Mapping[str, Any],
        output_schema: str,
        input_hashes: Sequence[str] = (),
    ) -> ComputationNode:
        node = ComputationNode.create(
            operation=operation,
            implementation_version=implementation_version,
            input_hashes=input_hashes,
            parameters=parameters,
            policy_hash=self._policy_hash,
            snapshot_hash=self._snapshot_hash,
            output_schema=output_schema,
        )
        existing = self._nodes.get(node.content_hash)
        if existing is not None and existing != node:
            raise RuntimeError("canonical computation hash collision")
        self._nodes[node.content_hash] = node
        return node

    def bind_candidate(
        self,
        candidate_id: str,
        terminal_hash: str,
    ) -> None:
        if not candidate_id:
            raise ValueError("candidate_id cannot be empty")
        existing = self._candidates.get(candidate_id)
        if existing is not None and existing != terminal_hash:
            raise ValueError(
                f"candidate already binds another terminal: {candidate_id}"
            )
        self._candidates[candidate_id] = terminal_hash

    def build(self) -> ComputationGraph:
        return ComputationGraph(
            nodes=tuple(
                self._nodes[node_hash]
                for node_hash in sorted(self._nodes)
            ),
            candidate_terminal_hashes=self._candidates,
        )


class SharedIntermediateManifest(FrozenModel):
    """Verified materialization of one exact computation node."""

    schema_version: Literal["1"] = "1"
    node_content_hash: Sha256
    operation: str
    output_schema: str
    relative_path: str
    payload_sha256: Sha256
    payload_bytes: int = Field(ge=0)


class SharedIntermediateStore:
    """Publish and reuse immutable node outputs under their exact hash."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _node_root(self, node_hash: str) -> Path:
        return self.root / node_hash[:2] / node_hash

    def _manifest_path(self, node_hash: str) -> Path:
        return self._node_root(node_hash) / "manifest.json"

    def _read_manifest(self, node_hash: str) -> SharedIntermediateManifest:
        path = self._manifest_path(node_hash)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return SharedIntermediateManifest.model_validate(payload)
        except (OSError, ValueError, TypeError) as exc:
            raise SharedIntermediateConflict(
                f"shared intermediate manifest is invalid: {node_hash}"
            ) from exc

    def publish(
        self,
        node: ComputationNode,
        source: Path,
    ) -> SharedIntermediateManifest:
        """Atomically publish bytes or verify an existing exact result."""

        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        source_sha256 = _sha256_file(source_path)
        source_bytes = source_path.stat().st_size
        destination = self._node_root(node.content_hash)
        if destination.exists():
            existing = self._read_manifest(node.content_hash)
            if (
                existing.node_content_hash != node.content_hash
                or existing.operation != node.operation
                or existing.output_schema != node.output_schema
                or existing.payload_sha256 != source_sha256
                or existing.payload_bytes != source_bytes
            ):
                raise SharedIntermediateConflict(
                    "existing shared intermediate conflicts with exact node"
                )
            self.resolve(existing)
            return existing

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{node.content_hash}.",
                dir=destination.parent,
            )
        )
        suffix = source_path.suffix or ".bin"
        temporary_payload = temporary / f"payload{suffix}"
        try:
            shutil.copyfile(source_path, temporary_payload)
            if (
                temporary_payload.stat().st_size != source_bytes
                or _sha256_file(temporary_payload) != source_sha256
            ):
                raise SharedIntermediateConflict(
                    "source changed while publishing shared intermediate"
                )
            relative_payload = (
                destination.relative_to(self.root) / temporary_payload.name
            )
            manifest = SharedIntermediateManifest(
                node_content_hash=node.content_hash,
                operation=node.operation,
                output_schema=node.output_schema,
                relative_path=relative_payload.as_posix(),
                payload_sha256=source_sha256,
                payload_bytes=source_bytes,
            )
            (temporary / "manifest.json").write_text(
                json.dumps(
                    deep_thaw_json(manifest),
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            try:
                os.replace(temporary, destination)
            except OSError:
                if not destination.exists():
                    raise
                shutil.rmtree(temporary, ignore_errors=True)
                existing = self._read_manifest(node.content_hash)
                if (
                    existing.payload_sha256 != source_sha256
                    or existing.payload_bytes != source_bytes
                ):
                    raise SharedIntermediateConflict(
                        "concurrent shared intermediate conflicts"
                    )
                self.resolve(existing)
                return existing
            return manifest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def resolve(
        self,
        manifest: SharedIntermediateManifest,
    ) -> Path:
        """Resolve only after manifest, size, and payload hash verification."""

        stored = self._read_manifest(manifest.node_content_hash)
        if stored != manifest:
            raise SharedIntermediateConflict(
                "shared intermediate manifest does not match stored evidence"
            )
        path = (self.root / stored.relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise SharedIntermediateConflict(
                "shared intermediate path escapes store root"
            ) from exc
        if (
            not path.is_file()
            or path.stat().st_size != stored.payload_bytes
            or _sha256_file(path) != stored.payload_sha256
        ):
            raise SharedIntermediateConflict(
                "shared intermediate payload is missing or corrupt"
            )
        return path
