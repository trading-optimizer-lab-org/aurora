from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from aurora.infra.sp500_megarun.catalog_component_store import (
    CatalogComponentStore,
    ComponentStoreWriter,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import RunOptimizationContractV1
from scripts.verify_sp500_component_store import seal_component_bundle


@pytest.mark.parametrize("case", ["shared", "single", "missing", "duplicate", "expired", "empty", "invalid"])
def test_component_download_selects_exact_ids_from_shared_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/catalog-optimized-run.yml").read_text())
    steps = workflow["jobs"]["verify_component_store"]["steps"]
    selector = next((step for step in steps if step.get("id") == "component_transports"), None)
    assert selector is not None, "Shared-run download must select the sealed plan's exact artifacts"
    download = next(step for step in steps if step["name"] == "Download every current-run exact component transport")
    assert download["with"]["artifact-ids"] == "${{ steps.component_transports.outputs.artifact_ids }}"
    assert "pattern" not in download["with"]
    plan = tmp_path / "sealed-plan"
    plan.mkdir()
    names = ["catalog-component-transport-canary-cached-000", "catalog-component-transport-canary-new-001"]
    rows = [{"id": 11, "name": names[0], "expired": False},
            {"id": 22, "name": names[1], "expired": False},
            {"id": 33, "name": "catalog-component-transport-sp500-cached-000", "expired": False}]
    if case == "single":
        names = names[:1]
    elif case == "missing":
        rows.pop(1)
    elif case == "duplicate":
        rows.append({"id": 44, "name": names[0], "expired": False})
    elif case == "expired":
        rows[0]["expired"] = True
    elif case == "empty":
        names = []
    elif case == "invalid":
        names = ["../foreign"]
    (plan / "component_store_input_manifest.json").write_text(json.dumps({
        "bundles": [{"component_transport_artifact": name} for name in names],
    }))
    output = tmp_path / "output"
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "test/aurora")

    def inventory(command, **kwargs):
        assert command == ["gh", "api", "repos/test/aurora/actions/runs/123/artifacts?per_page=100", "--paginate", "--slurp"]
        return json.dumps([{"artifacts": rows[:1]}, {"artifacts": rows[1:]}])

    monkeypatch.setattr(subprocess, "check_output", inventory)
    code = textwrap.dedent(selector["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0])
    if case in {"shared", "single"}:
        exec(compile(code, "actual-component-selector", "exec"), {})
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert outputs["artifact_ids"] == ("11" if case == "single" else "11,22")
        path = download["with"]["path"].replace("${{ runner.temp }}", str(tmp_path))
        for key, value in outputs.items():
            path = path.replace("${{ steps.component_transports.outputs." + key + " }}", value)
        ids = set(map(int, outputs["artifact_ids"].split(",")))
        selected = [row for row in rows if row["id"] in ids]
        # Pinned action extracts a singleton directly at path; multiple IDs
        # retain artifact-name directories when merge-multiple is false.
        observed = [Path(path) if len(selected) == 1 else Path(path) / str(row["name"]) for row in selected]
        assert observed == [tmp_path / "component-transports" / name for name in names]
    else:
        with pytest.raises(SystemExit, match="COMPONENT_TRANSPORT_"):
            exec(compile(code, "actual-component-selector", "exec"), {})
        assert not output.exists()


@pytest.fixture
def sealed_bundle(tmp_path: Path):
    policy = json.loads(Path("config/sp500_catalog_optimization_policy_v1.json").read_text())
    policy.pop("numeric_profile")
    policy.pop("workload_estimates")
    policy.update(
        infrastructure_sha256="a" * 64,
        science={
            "evaluator_sha256": "a" * 64,
            "data_snapshot_sha256": "b" * 64,
            "catalog_manifest_sha256": "c" * 64,
            "train_end": "2010-12-31",
            "validation_opened": False,
            "locked_opened": False,
            "numeric_profile": "test",
        },
        workload={
            "requested_recipes": 1, "canonical_recipes": 1, "unique_components": 2,
            "expected_new_recipes": 1, "expected_prior_cache_hits": 0,
            "estimated_position_equivalences": 0,
        },
    )
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(RunOptimizationContractV1.model_validate(policy).model_dump_json())
    root = tmp_path / "store"
    writer = ComponentStoreWriter(
        root, data_snapshot_sha256="b" * 64, evaluator_sha256="a" * 64, session_count=3,
    )
    writer.add("1" * 64, np.array([1, 0, -1], dtype=np.int8))
    writer.add("2" * 64, np.array([-1, 1, 0], dtype=np.int8))
    writer.commit()
    sources = [
        {"component_id": "3" * 64, "source_configuration_sha256": "1" * 64},
        {"component_id": "4" * 64, "source_configuration_sha256": "2" * 64},
    ]
    assignment = {
        "schema_version": "1", "worker_id": 0,
        "component_ids": ["3" * 64, "4" * 64],
        "component_sources": sources,
        "component_schedule": {}, "validation_opened": False, "locked_opened": False,
    }
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment))
    original = seal_component_bundle(
        root, resolved_contract=contract_path, assignment_file=assignment_path,
        bundle_identity_sha256="5" * 64, expected_component_count=2,
    )
    return root, contract_path, assignment_path, assignment, sources, original


@pytest.mark.parametrize("invalid", [None, "missing", "source", "pin", "unpinned", "matrix"])
def test_pinned_bundle_reuses_subset_without_rewriting_or_recomputing(
    tmp_path: Path, sealed_bundle, invalid: str | None,
) -> None:
    root, contract_path, assignment_path, assignment, sources, original = sealed_bundle
    assignment["component_ids"] = ["3" * 64]
    assignment["component_sources"] = sources[:1]
    expected = str(original["manifest_sha256"])
    if invalid == "missing":
        assignment["component_ids"] = ["6" * 64]
        assignment["component_sources"] = [
            {"component_id": "6" * 64, "source_configuration_sha256": "1" * 64},
        ]
    elif invalid == "source":
        assignment["component_sources"] = [
            {"component_id": "3" * 64, "source_configuration_sha256": "2" * 64},
        ]
    elif invalid == "pin":
        expected = "0" * 64
    elif invalid == "matrix":
        matrix = root / "signals.npy"
        matrix.write_bytes(matrix.read_bytes()[:-1] + b"\x01")
    assignment_path.write_text(json.dumps(assignment))
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    if invalid is not None:
        with pytest.raises(ValueError, match="COMPONENT_"):
            seal_component_bundle(
                root, resolved_contract=contract_path, assignment_file=assignment_path,
                bundle_identity_sha256="5" * 64, expected_component_count=1,
                expected_bundle_manifest_sha256=None if invalid == "unpinned" else expected,
            )
        assert {path.name: path.read_bytes() for path in root.iterdir()} == before
        return
    reused = seal_component_bundle(
        root, resolved_contract=contract_path, assignment_file=assignment_path,
        bundle_identity_sha256="5" * 64, expected_component_count=1,
        expected_bundle_manifest_sha256=expected,
    )
    assert reused == original
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    github_output = tmp_path / "github-output.txt"
    cli = subprocess.run(
        [
            sys.executable, "-m", "scripts.verify_sp500_component_store",
            "--component-store", str(root), "--resolved-contract", str(contract_path),
            "--expected-component-count", "1", "--assignment-file", str(assignment_path),
            "--bundle-identity-sha256", "5" * 64,
            "--expected-manifest-sha256", expected,
            "--cache-key-prefix", "aurora-catalog-v1-" + "5" * 64 + "-",
            "--github-output", str(github_output),
        ], capture_output=True, text=True, check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout) == original
    assert github_output.read_text().splitlines() == [
        "cache_key=aurora-catalog-v1-" + "5" * 64 + "-" + expected + "-main",
        "bundle_manifest_sha256=" + expected,
    ]
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    from scripts.run_sp500_optimized_recipe_worker import _ExactComponentPayload

    with CatalogComponentStore.open(root) as store:
        payload = _ExactComponentPayload((store,))
        np.testing.assert_array_equal(payload.get("1" * 64), [1, 0, -1])


@pytest.mark.parametrize("case", [
    "subset", "wrong_pin", "unpinned_subset", "missing", "unselected_result", "unselected_duplicate",
])
def test_actual_workflow_reconciles_only_pinned_selected_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sealed_bundle, case: str,
) -> None:
    root, contract_path, _, _, _, original = sealed_bundle
    workflow = Path(".github/workflows/catalog-optimized-run.yml").read_text()
    step = workflow.split("- name: Reconcile and verify the complete global component store", 1)[1]
    code = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    plan = tmp_path / "sealed-plan"
    plan.mkdir()
    (plan / "resolved_contract.json").write_bytes(contract_path.read_bytes())
    artifact = "catalog-component-transport-test"
    transport = tmp_path / "component-transports" / artifact
    transport.mkdir(parents=True)
    for path in root.iterdir():
        (transport / path.name).write_bytes(path.read_bytes())
    selected = ["3" * 64, "4" * 64] if case == "wrong_pin" else ["3" * 64]
    if case == "missing":
        selected = ["6" * 64]
    pin = "0" * 64 if case == "wrong_pin" else original["manifest_sha256"]
    if case == "unpinned_subset":
        pin = None
    if case.startswith("unselected_"):
        from aurora.infra.github_performance.contracts import canonical_sha256

        wrapper_path = transport / "component_bundle_manifest.json"
        wrapper = json.loads(wrapper_path.read_text())
        if case == "unselected_result":
            wrapper["components"][1]["result_sha256"] = "0" * 64
        else:
            wrapper["components"].append(dict(wrapper["components"][1]))
        pin = canonical_sha256({key: value for key, value in wrapper.items() if key != "manifest_sha256"})
        wrapper["manifest_sha256"] = pin
        wrapper_path.write_text(json.dumps(wrapper))
    (plan / "component_store_input_manifest.json").write_text(json.dumps({
        "required_component_ids": selected,
        "bundles": [{
            "component_transport_artifact": artifact,
            "bundle_identity_sha256": "5" * 64,
            "component_ids": selected,
            "expected_store_manifest_sha256": pin,
        }],
    }))
    before = {path.name: path.read_bytes() for path in transport.iterdir()}
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    if case != "subset":
        with pytest.raises(SystemExit, match="COMPONENT_BUNDLE_"):
            exec(compile(code, "catalog-optimized-run-reconcile", "exec"), {})
        assert not (tmp_path / "component-store-seal.json").exists()
    else:
        exec(compile(code, "catalog-optimized-run-reconcile", "exec"), {})
        seal = json.loads((tmp_path / "component-store-seal.json").read_text())
        assert seal["required_component_ids"] == ["3" * 64]
        assert list(seal["component_result_sha256"]) == ["3" * 64]
        assert seal["validation_opened"] is False
        assert seal["locked_opened"] is False
    assert {path.name: path.read_bytes() for path in transport.iterdir()} == before
