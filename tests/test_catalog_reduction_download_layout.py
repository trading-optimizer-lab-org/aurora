from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.preflight import load_github_yaml
from scripts.reduce_sp500_optimized_catalog_run import (
    _verify_group_reduction_inputs,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-run.yml"
DOWNLOAD_ACTION = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
CATALOG_SHA = "c" * 64
WORK_SHA = "w" * 64


def _download_step() -> dict[str, Any]:
    workflow = dict(load_github_yaml(WORKFLOW))
    return next(
        step
        for step in workflow["jobs"]["reduce"]["steps"]
        if step.get("name") == "Download only bounded reduction groups"
    )


def _checkpoint_download_step() -> dict[str, Any]:
    workflow = dict(load_github_yaml(WORKFLOW))
    return next(
        step
        for step in workflow["jobs"]["reduce_groups"]["steps"]
        if step.get("name") == "Download only this sealed checkpoint group"
    )


def _layout_script(step_id: str = "reduction_download_layout") -> str:
    workflow = dict(load_github_yaml(WORKFLOW))
    job_id = "reduce_groups" if step_id == "checkpoint_download_layout" else "reduce"
    step = next(
        step
        for step in workflow["jobs"][job_id]["steps"]
        if step.get("id") == step_id
    )
    run = step["run"]
    marker = "python - <<'PY'\n"
    assert marker in run
    script = run.split(marker, 1)[1].split("\nPY", 1)[0]
    return textwrap.dedent(script)


def _run_layout(
    plan_path: Path,
    tmp_path: Path,
    *,
    step_id: str = "reduction_download_layout",
    group_id: int | None = None,
) -> subprocess.CompletedProcess[str]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    output_path = tmp_path / "github-output"
    output_path.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "REDUCTION_PLAN": str(plan_path),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output_path),
        }
    )
    if group_id is not None:
        environment["GROUP_ID"] = str(group_id)
    return subprocess.run(
        [sys.executable, "-c", _layout_script(step_id)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _layout_path(result: subprocess.CompletedProcess[str], tmp_path: Path) -> Path:
    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "github-output"
    values = dict(
        line.split("=", 1)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line
    )
    return Path(values["path"])


def _valid_plan(
    tmp_path: Path, artifact_names: tuple[str, ...]
) -> tuple[Path, dict[str, Any], dict[str, dict[str, bytes]]]:
    groups = [
        {
            "group_id": index,
            "worker_ids": [index],
            "checkpoint_artifacts": [f"checkpoint-{index}"],
            "checkpoint_artifact_pattern": f"checkpoint-{index}-*",
            "reduction_artifact": artifact,
        }
        for index, artifact in enumerate(artifact_names)
    ]
    common = {
        "campaign_id": "campaign",
        "authority_id": "authority",
        "science_sha256": "s" * 64,
        "execution_plan_sha256": "e" * 64,
    }
    eligibility = {"mode": "hierarchical", "reason": "synthetic"}
    central_eligibility = {
        **eligibility,
        "decision_sha256": canonical_sha256(eligibility),
    }
    nodes = []
    for group in groups:
        node_identity = {
            "node_id": f"l00-g{group['group_id']:03d}",
            "level": 0,
            "group_id": group["group_id"],
            "output_artifact": group["reduction_artifact"],
            **common,
            "resource_projection_p99": {
                field: 0.1
                for field in (
                    "timeout_fraction_p99",
                    "memory_fraction_p99",
                    "disk_fraction_p99",
                    "artifact_fraction_p99",
                    "download_fraction_p99",
                    "input_count_fraction_p99",
                )
            },
            "validation_opened": False,
            "locked_opened": False,
        }
        nodes.append(
            {
                **node_identity,
                "node_descriptor_sha256": canonical_sha256(node_identity),
            }
        )
    root_identity = {
        "node_id": "l01-g000",
        "level": 1,
        "group_id": 0,
        "direct_children": [
            {
                "child_id": node["node_id"],
                "artifact_ids": [node["output_artifact"]],
                "descriptor_sha256": node["node_descriptor_sha256"],
            }
            for node in nodes
        ],
        "output_artifact": "final-evidence",
        **common,
        "resource_projection_p99": {
            field: 0.1
            for field in (
                "timeout_fraction_p99",
                "memory_fraction_p99",
                "disk_fraction_p99",
                "artifact_fraction_p99",
                "download_fraction_p99",
                "input_count_fraction_p99",
            )
        },
        "validation_opened": False,
        "locked_opened": False,
    }
    plan = {
        "schema_version": "1",
        "document_type": "reduction_plan",
        "selected_mode": "hierarchical",
        "central_eligibility": central_eligibility,
        "groups": groups,
        "nodes": nodes,
        "root_node": {
            **root_identity,
            "node_descriptor_sha256": canonical_sha256(root_identity),
        },
        "final_evidence_artifact": "final-evidence",
        **common,
        "validation_opened": False,
        "locked_opened": False,
    }
    plan["content_sha256"] = canonical_sha256(plan)
    plan_path = tmp_path / "sealed-plan" / "reduction_plan.json"
    plan_path.parent.mkdir()
    plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")

    files_by_artifact: dict[str, dict[str, bytes]] = {}
    for group, node in zip(groups, nodes):
        result = f"result-{group['group_id']}\n".encode()
        result_sha256 = hashlib.sha256(result).hexdigest()
        receipt_identity = {
            "reduction_group_id": group["group_id"],
            "reduction_artifact": group["reduction_artifact"],
            "worker_ids": group["worker_ids"],
            "source_worker_receipt_count": len(group["worker_ids"]),
            "science_identity_sha256": common["science_sha256"],
            "catalog_manifest_sha256": CATALOG_SHA,
            "work_manifest_sha256": WORK_SHA,
            "reduction_plan_sha256": plan["content_sha256"],
            "node_descriptor_sha256": node["node_descriptor_sha256"],
            "validation_opened": False,
            "locked_opened": False,
            "result_sha256": result_sha256,
        }
        receipt = {
            **receipt_identity,
            "receipt_sha256": canonical_sha256(receipt_identity),
        }
        manifest = {
            "group_id": group["group_id"],
            "worker_ids": group["worker_ids"],
            "result_sha256": result_sha256,
            "reduction_plan_sha256": plan["content_sha256"],
            "node_descriptor_sha256": node["node_descriptor_sha256"],
            "checkpoint_receipt_manifest_sha256": None,
            "validation_opened": False,
            "locked_opened": False,
        }
        files_by_artifact[group["reduction_artifact"]] = {
            "receipt.json": (json.dumps(receipt, sort_keys=True) + "\n").encode(),
            "reduction_group_manifest.json": (
                json.dumps(manifest, sort_keys=True) + "\n"
            ).encode(),
            "results.parquet": result,
        }
    return plan_path, plan, files_by_artifact


def _materialize_download(
    destination: Path, files_by_artifact: dict[str, dict[str, bytes]]
) -> None:
    # This is the pinned action's merge-multiple:false path rule:
    # one selected artifact is extracted flat; multiple artifacts get names.
    for artifact, files in files_by_artifact.items():
        target = destination if len(files_by_artifact) == 1 else destination / artifact
        target.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (target / name).write_bytes(content)


def _verify_with_production_reader(
    input_root: Path, plan_path: Path, plan: dict[str, Any]
) -> None:
    _verify_group_reduction_inputs(
        input_root,
        reduction_plan_path=plan_path,
        pending_recipe_count=1,
        expected_science_identity_sha256=plan["science_sha256"],
        expected_catalog_manifest_sha256=CATALOG_SHA,
        expected_work_manifest_sha256=WORK_SHA,
    )


def test_download_step_is_pinned_and_uses_the_layout_output() -> None:
    step = _download_step()
    assert step["uses"] == DOWNLOAD_ACTION
    assert step["with"]["pattern"] == (
        "${{ needs.engine_verify_sealed_plan.outputs.reduction_artifact_pattern }}"
    )
    assert step["with"]["merge-multiple"] is False
    assert step["with"]["path"] == "${{ steps.reduction_download_layout.outputs.path }}"


def test_checkpoint_download_step_is_pinned_and_uses_the_layout_output() -> None:
    step = _checkpoint_download_step()
    assert step["uses"] == DOWNLOAD_ACTION
    assert step["with"]["pattern"] == "${{ matrix.checkpoint_artifact_pattern }}"
    assert step["with"]["merge-multiple"] is False
    assert step["with"]["path"] == "${{ steps.checkpoint_download_layout.outputs.path }}"


@pytest.mark.parametrize(
    ("artifact_names", "nested"),
    [
        (("catalog-reduction-group-plan-g00",), True),
        (("catalog-reduction-group-plan-g00", "catalog-reduction-group-plan-g01"), False),
    ],
)
def test_real_workflow_python_matches_pinned_layout_and_reader(
    tmp_path: Path, artifact_names: tuple[str, ...], nested: bool
) -> None:
    plan_path, plan, files = _valid_plan(tmp_path, artifact_names)
    layout = _run_layout(plan_path, tmp_path)
    destination = _layout_path(layout, tmp_path)
    expected_root = tmp_path / "runner-temp" / "reduction-groups"
    expected_destination = expected_root / artifact_names[0] if nested else expected_root
    assert destination == expected_destination

    _materialize_download(destination, files)
    for artifact, artifact_files in files.items():
        artifact_root = expected_root / artifact
        for name, content in artifact_files.items():
            assert (artifact_root / name).read_bytes() == content
    _verify_with_production_reader(expected_root, plan_path, plan)


@pytest.mark.parametrize(
    ("checkpoint_artifacts", "nested"),
    [
        (("catalog-checkpoint-plan-g00-w00-s01",), True),
        (
            (
                "catalog-checkpoint-plan-g00-w00-s01",
                "catalog-checkpoint-plan-g00-w00-s02",
            ),
            False,
        ),
    ],
)
def test_real_checkpoint_workflow_python_matches_pinned_layout_and_metadata(
    tmp_path: Path, checkpoint_artifacts: tuple[str, ...], nested: bool
) -> None:
    plan_path = tmp_path / "sealed-plan" / "reduction_plan.json"
    plan_path.parent.mkdir()
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_id": 0,
                        "checkpoint_artifacts": list(checkpoint_artifacts),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    layout = _run_layout(plan_path, tmp_path, step_id="checkpoint_download_layout", group_id=0)
    destination = _layout_path(layout, tmp_path)
    expected_root = tmp_path / "runner-temp" / "checkpoint-group"
    expected_destination = expected_root / checkpoint_artifacts[0] if nested else expected_root
    assert destination == expected_destination

    files = {
        artifact: {
            "receipt.json": f"receipt-{artifact}".encode(),
            "checkpoint_chain_manifest.json": f"chain-{artifact}".encode(),
        }
        for artifact in checkpoint_artifacts
    }
    _materialize_download(destination, files)
    for artifact, artifact_files in files.items():
        artifact_root = expected_root / artifact
        for name, content in artifact_files.items():
            assert (artifact_root / name).read_bytes() == content


@pytest.mark.parametrize(
    "actual_names",
    [
        ("catalog-reduction-group-plan-g00", "catalog-reduction-group-plan-g01", "extra"),
        ("catalog-reduction-group-plan-g00", "unexpected"),
    ],
    ids=["extra", "unexpected"],
)
def test_production_reader_rejects_extra_or_unexpected_downloads(
    tmp_path: Path, actual_names: tuple[str, ...]
) -> None:
    expected_names = (
        "catalog-reduction-group-plan-g00",
        "catalog-reduction-group-plan-g01",
    )
    plan_path, plan, expected_files = _valid_plan(tmp_path, expected_names)
    layout = _run_layout(plan_path, tmp_path)
    destination = _layout_path(layout, tmp_path)
    actual_files = {
        name: expected_files[expected_names[0]] if name not in expected_files else expected_files[name]
        for name in actual_names
    }
    _materialize_download(destination, actual_files)
    with pytest.raises(SystemExit, match="OPTIMIZED_REDUCTION_INPUT_SET_INVALID"):
        _verify_with_production_reader(destination, plan_path, plan)


@pytest.mark.parametrize("bad_name", ["", ".", "..", "../escape", r"..\escape"])
def test_real_workflow_python_rejects_non_basename_artifacts(
    tmp_path: Path, bad_name: str
) -> None:
    plan_path = tmp_path / "reduction_plan.json"
    plan_path.write_text(
        json.dumps({"groups": [{"reduction_artifact": bad_name}]}),
        encoding="utf-8",
    )
    result = _run_layout(plan_path, tmp_path)
    assert result.returncode != 0
    assert "CATALOG_REDUCTION_DOWNLOAD_ARTIFACT_NAME_INVALID" in (
        result.stdout + result.stderr
    )


@pytest.mark.parametrize("bad_name", ["", ".", "..", "../escape", r"..\escape"])
def test_real_checkpoint_workflow_python_rejects_non_basename_artifacts(
    tmp_path: Path, bad_name: str
) -> None:
    plan_path = tmp_path / "reduction_plan.json"
    plan_path.write_text(
        json.dumps(
            {"groups": [{"group_id": 0, "checkpoint_artifacts": [bad_name]}]}
        ),
        encoding="utf-8",
    )
    result = _run_layout(
        plan_path,
        tmp_path,
        step_id="checkpoint_download_layout",
        group_id=0,
    )
    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_DOWNLOAD_ARTIFACT_NAME_INVALID" in (
        result.stdout + result.stderr
    )
