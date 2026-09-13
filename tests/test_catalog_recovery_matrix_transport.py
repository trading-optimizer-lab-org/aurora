"""Recovery must consume the matrix files emitted by the sealed-plan writer."""

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from tests.test_catalog_prepared_materialization import prepared_transport_fixture


def test_recovery_job_resolves_source_package_without_an_installed_aurora(tmp_path):
    """The offline dependency runtime must find Aurora in the protected checkout."""
    repo = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(repo / ".github/workflows/catalog-recovery-wave.yml")
    job = workflow["jobs"]["reconcile"]
    # Mirror Actions' owner/repository checkout layout. Import the actual package
    # initializer, with site packages disabled so developer installs cannot help.
    workspace = tmp_path / "aurora" / "aurora"
    workspace.mkdir(parents=True)
    shutil.copyfile(repo / "__init__.py", workspace / "__init__.py")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    configured = job.get("env", {}).get("PYTHONPATH")
    if configured is not None:
        env["PYTHONPATH"] = configured.replace("${{ github.workspace }}", str(workspace))
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import aurora; print(aurora.__file__)"],
        cwd=workspace, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (workspace / "__init__.py").resolve()


@pytest.mark.parametrize("consumer", ["download", "reconcile"])
def test_recovery_reads_producer_matrices(tmp_path, monkeypatch, consumer):
    """A nonexistent matrix alias must fail before recovery can reuse results."""
    _, plan_root, _, _, _ = prepared_transport_fixture(tmp_path)
    action_path = Path(__file__).resolve().parents[1] / ".github/actions/aurora-recovery-plan/action.yml"
    steps = load_github_yaml(action_path)["runs"]["steps"]
    runner = tmp_path / "runner"
    monkeypatch.setenv("SEALED_PLAN_PATH", str(plan_root))
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    if consumer == "download":
        step = next(row for row in steps if row.get("name") ==
                    "Download exact original descriptor bundles selected by the plan")
        source = step["run"].split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        exec(compile(source, str(action_path), "exec"), {})
        artifacts = (runner / "catalog-recovery/original-descriptors/artifacts.txt").read_text("utf-8").splitlines()
        assert len(artifacts) == 1
        descriptors = list((plan_root / "payload_artifacts" / artifacts[0]).rglob("*.json"))
        assert sorted(json.loads(path.read_text("utf-8"))["worker_id"] for path in descriptors) == list(range(7))
    else:
        temp = runner / "catalog-recovery"
        shutil.copytree(plan_root / "payload_artifacts", temp / "original-descriptors")
        step = next(row for row in steps if row.get("id") == "reconcile")
        source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        tree = ast.parse(source)
        # Execute the contiguous route/descriptor loading boundary, including
        # its real file, digest, path and identity checks; no network or science.
        start = next(i for i, node in enumerate(tree.body)
                     if isinstance(node, ast.Assign) and any(
                         isinstance(t, ast.Name) and t.id == "original_rows" for t in node.targets))
        end = next(i for i, node in enumerate(tree.body)
                   if isinstance(node, ast.Assign) and any(
                       isinstance(t, ast.Name) and t.id == "completed_workers" for t in node.targets))
        namespace = {"plan_root": plan_root, "temp": temp,
                     "Path": Path, "json": json, "hashlib": hashlib}
        exec(compile(ast.Module(body=tree.body[start:end], type_ignores=[]), str(action_path), "exec"), namespace)
        descriptors = namespace["descriptor_by_worker"]
        assert sorted(descriptors) == list(range(7))
        assert sum(row["expected_strategy_count"] for row in descriptors.values()) == 24
        assert all(row["prior_checkpoint_chain_artifact"] == "" for row in descriptors.values())
