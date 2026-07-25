from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    RunSpec,
    canonical_sha256,
)
from aurora.infra.github_performance.execution_planner import (
    build_execution_plan,
    choose_job_count,
    write_execution_plan,
    write_pilot_result,
)
from aurora.infra.github_performance.shard_planner import (
    encode_matrix_outputs,
    split_matrices,
    weighted_lpt,
    write_work_unit_manifest,
)
from github_performance_helpers import (
    contract,
    high_setup_pilot,
    make_shard,
    make_unit,
    minimal_valid_spec,
    pilot,
)


def test_lpt_is_balanced_and_deterministic(tmp_path: Path) -> None:
    units = [
        make_unit(index, seconds=seconds)
        for index, seconds in enumerate([9, 8, 7, 6, 5, 4])
    ]
    first_manifest = write_work_unit_manifest(
        units,
        tmp_path / "first" / "work_units.parquet",
    )
    second_manifest = write_work_unit_manifest(
        reversed(units),
        tmp_path / "second" / "work_units.parquet",
    )
    first = weighted_lpt(first_manifest, jobs=2, output_dir=tmp_path / "a")
    second = weighted_lpt(
        second_manifest,
        jobs=2,
        output_dir=tmp_path / "b",
    )
    assert (
        first.assignment_manifest_sha256
        == second.assignment_manifest_sha256
    )
    assert max(shard.estimated_seconds for shard in first.shards) == 20


def test_assignment_catalog_contains_every_unit_once(tmp_path: Path) -> None:
    manifest = write_work_unit_manifest(
        (make_unit(index) for index in range(20)),
        tmp_path / "work_units.parquet",
    )
    plan = weighted_lpt(manifest, jobs=7, output_dir=tmp_path / "plan")
    table = pq.read_table(
        tmp_path / "plan" / "balanced_unit_assignments.parquet"
    )
    keys = table.column("unit_key").to_pylist()
    assert len(keys) == len(set(keys)) == 20
    assert sum(shard.unit_count for shard in plan.shards) == 20


def test_full_capacity_splits_256_and_104() -> None:
    shards = tuple(make_shard(index) for index in range(360))
    split = split_matrices(shards)
    assert len(split.matrix_a) == 256
    assert len(split.matrix_b) == 104


def test_matrix_output_is_compact() -> None:
    split = split_matrices(tuple(make_shard(index) for index in range(360)))
    outputs = encode_matrix_outputs(split)
    assert (
        sum(len(value.encode("utf-8")) for value in outputs.values())
        < 262_144
    )
    assert "unit_keys" not in "".join(outputs.values())


def test_small_workload_does_not_force_360_jobs(tmp_path: Path) -> None:
    manifest = write_work_unit_manifest(
        (make_unit(index, seconds=1) for index in range(20)),
        tmp_path / "work_units.parquet",
    )
    decision = choose_job_count(manifest, contract(), high_setup_pilot())
    assert decision.selected_jobs < 20


def test_large_path_runs_at_most_three_exact_lpt_calls(
    tmp_path: Path,
) -> None:
    manifest = write_work_unit_manifest(
        (
            make_unit(index, seconds=float((index % 7) + 1))
            for index in range(100)
        ),
        tmp_path / "work_units.parquet",
    )
    calls: list[int] = []

    def counted_lpt(manifest, jobs, output_dir):
        calls.append(jobs)
        return weighted_lpt(manifest, jobs, output_dir)

    large_contract = contract().model_copy(
        update={"planner_large_unit_threshold": 10}
    )
    choose_job_count(
        manifest,
        large_contract,
        pilot(),
        lpt_builder=counted_lpt,
    )
    assert 1 <= len(calls) <= 3


def test_execution_plan_is_complete_and_hash_stable(
    tmp_path: Path,
) -> None:
    run_spec = RunSpec.model_validate(minimal_valid_spec())
    work_units = tuple(make_unit(index) for index in range(20))
    first_manifest = write_work_unit_manifest(
        work_units,
        tmp_path / "first" / "work_units.parquet",
    )
    second_manifest = write_work_unit_manifest(
        reversed(work_units),
        tmp_path / "second" / "work_units.parquet",
    )
    first = build_execution_plan(
        run_spec,
        first_manifest,
        pilot(),
        tmp_path / "first-plan",
    )
    second = build_execution_plan(
        run_spec,
        second_manifest,
        pilot(),
        tmp_path / "second-plan",
    )
    assert canonical_sha256(first) == canonical_sha256(second)
    assert first.matrix_split.has_matrix_b == (
        first.job_count.selected_jobs > 256
    )
    paths = write_execution_plan(first, tmp_path)
    pilot_path = write_pilot_result(
        pilot(),
        tmp_path / "performance_pilot.json",
    )
    assert {path.name for path in paths} == {
        "performance_plan.json",
        "execution_plan.json",
        "balanced_shard_plan.json",
    }
    assert pilot_path.name == "performance_pilot.json"
    assert json.loads(paths[1].read_text())["numeric_threads"] == 1
