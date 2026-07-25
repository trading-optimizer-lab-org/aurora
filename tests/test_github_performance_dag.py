from __future__ import annotations

from pathlib import Path

import pytest

from aurora.infra.github_performance.dag import (
    ComputationGraph,
    ComputationGraphBuilder,
    ComputationNode,
    GraphCycleError,
    SharedIntermediateConflict,
    SharedIntermediateStore,
)


POLICY_HASH = "a" * 64
SNAPSHOT_HASH = "b" * 64


def _builder() -> ComputationGraphBuilder:
    return ComputationGraphBuilder(
        policy_hash=POLICY_HASH,
        snapshot_hash=SNAPSHOT_HASH,
    )


def test_graph_builds_canonical_chain_and_preserves_candidates() -> None:
    builder = _builder()
    data = builder.add_node(
        operation="data",
        implementation_version="1",
        parameters={"dataset": "prices"},
        output_schema="prices-v1",
    )
    previous = data
    for operation in (
        "features",
        "signals",
        "positions",
        "returns",
        "metrics",
        "robustness",
    ):
        previous = builder.add_node(
            operation=operation,
            implementation_version="1",
            input_hashes=(previous.content_hash,),
            parameters={"window": 20},
            output_schema=f"{operation}-v1",
        )
    builder.bind_candidate("candidate-a", previous.content_hash)
    builder.bind_candidate("candidate-b", previous.content_hash)

    graph = builder.build()

    assert [node.operation for node in graph.topological_order()] == [
        "data",
        "features",
        "signals",
        "positions",
        "returns",
        "metrics",
        "robustness",
    ]
    assert dict(graph.candidate_terminal_hashes) == {
        "candidate-a": previous.content_hash,
        "candidate-b": previous.content_hash,
    }


def test_graph_deduplicates_only_exact_node_identity() -> None:
    builder = _builder()
    exact_a = builder.add_node(
        operation="features",
        implementation_version="3",
        parameters={"window": 20, "threshold": 1.0},
        output_schema="features-v2",
    )
    exact_b = builder.add_node(
        operation="features",
        implementation_version="3",
        parameters={"threshold": 1.0, "window": 20},
        output_schema="features-v2",
    )
    merely_close = builder.add_node(
        operation="features",
        implementation_version="3",
        parameters={"window": 20, "threshold": 1.0000000001},
        output_schema="features-v2",
    )

    graph = builder.build()

    assert exact_a.content_hash == exact_b.content_hash
    assert exact_a.content_hash != merely_close.content_hash
    assert len(graph.nodes) == 2


def test_node_hash_changes_for_every_scientific_identity_input() -> None:
    base = ComputationNode.create(
        operation="signals",
        implementation_version="1",
        input_hashes=("c" * 64,),
        parameters={"threshold": 2},
        policy_hash=POLICY_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        output_schema="signals-v1",
    )
    variants = (
        ComputationNode.create(
            operation="positions",
            implementation_version="1",
            input_hashes=("c" * 64,),
            parameters={"threshold": 2},
            policy_hash=POLICY_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            output_schema="signals-v1",
        ),
        ComputationNode.create(
            operation="signals",
            implementation_version="2",
            input_hashes=("c" * 64,),
            parameters={"threshold": 2},
            policy_hash=POLICY_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            output_schema="signals-v1",
        ),
        ComputationNode.create(
            operation="signals",
            implementation_version="1",
            input_hashes=("d" * 64,),
            parameters={"threshold": 2},
            policy_hash=POLICY_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            output_schema="signals-v1",
        ),
        ComputationNode.create(
            operation="signals",
            implementation_version="1",
            input_hashes=("c" * 64,),
            parameters={"threshold": 3},
            policy_hash=POLICY_HASH,
            snapshot_hash=SNAPSHOT_HASH,
            output_schema="signals-v1",
        ),
        ComputationNode.create(
            operation="signals",
            implementation_version="1",
            input_hashes=("c" * 64,),
            parameters={"threshold": 2},
            policy_hash="e" * 64,
            snapshot_hash=SNAPSHOT_HASH,
            output_schema="signals-v1",
        ),
        ComputationNode.create(
            operation="signals",
            implementation_version="1",
            input_hashes=("c" * 64,),
            parameters={"threshold": 2},
            policy_hash=POLICY_HASH,
            snapshot_hash="f" * 64,
            output_schema="signals-v1",
        ),
    )

    assert all(
        variant.content_hash != base.content_hash
        for variant in variants
    )


def test_graph_rejects_cycles_and_missing_dependencies() -> None:
    node_a = ComputationNode.model_construct(
        operation="a",
        implementation_version="1",
        input_hashes=("2" * 64,),
        parameters={},
        policy_hash=POLICY_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        output_schema="a-v1",
        content_hash="1" * 64,
    )
    node_b = ComputationNode.model_construct(
        operation="b",
        implementation_version="1",
        input_hashes=("1" * 64,),
        parameters={},
        policy_hash=POLICY_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        output_schema="b-v1",
        content_hash="2" * 64,
    )
    with pytest.raises(GraphCycleError):
        ComputationGraph(nodes=(node_a, node_b))

    builder = _builder()
    builder.add_node(
        operation="features",
        implementation_version="1",
        input_hashes=("9" * 64,),
        parameters={},
        output_schema="features-v1",
    )
    with pytest.raises(ValueError, match="missing dependency"):
        builder.build()


def test_shared_intermediate_store_is_atomic_and_fail_closed(
    tmp_path: Path,
) -> None:
    node = ComputationNode.create(
        operation="features",
        implementation_version="1",
        input_hashes=(),
        parameters={"window": 20},
        policy_hash=POLICY_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        output_schema="features-v1",
    )
    source = tmp_path / "features.parquet"
    source.write_bytes(b"exact-feature-bytes")
    store = SharedIntermediateStore(tmp_path / "store")

    first = store.publish(node, source)
    second = store.publish(node, source)

    assert first == second
    resolved = store.resolve(first)
    assert resolved.read_bytes() == b"exact-feature-bytes"
    assert node.content_hash in resolved.as_posix()

    conflicting = tmp_path / "conflicting.parquet"
    conflicting.write_bytes(b"different-feature-bytes")
    with pytest.raises(SharedIntermediateConflict):
        store.publish(node, conflicting)

    resolved.write_bytes(b"corrupt")
    with pytest.raises(SharedIntermediateConflict):
        store.resolve(first)
