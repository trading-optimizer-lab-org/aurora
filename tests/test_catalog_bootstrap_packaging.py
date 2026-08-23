from __future__ import annotations

import subprocess
import json
import runpy
import zipfile
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_catalog_bootstrap_assistant.py"
BUILDER = ROOT / "scripts/build_catalog_bootstrap_assistant.py"


def _build(destination: Path) -> None:
    subprocess.run(
        ["C:/Python314/python.exe", str(BUILDER), "--output", str(destination)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_cli_has_only_installed_root() -> None:
    text = RUNNER.read_text("utf-8")
    assert text.count("add_argument(") == 1
    assert '"--installed-root"' in text
    assert "--url" not in text and "--repository" not in text


def test_two_builds_are_identical(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    _build(first)
    _build(second)
    assert (first / "catalog-bootstrap-assistant.pyz").read_bytes() == (
        second / "catalog-bootstrap-assistant.pyz"
    ).read_bytes()
    assert (first / "catalog-bootstrap-application-manifest-v1.json").read_bytes() == (
        second / "catalog-bootstrap-application-manifest-v1.json"
    ).read_bytes()
    manifest = json.loads(
        (first / "catalog-bootstrap-application-manifest-v1.json").read_text("utf-8")
    )
    schema = json.loads(
        (ROOT / "schemas/catalog_bootstrap_application_manifest_v1.schema.json").read_text(
            "utf-8"
        )
    )
    jsonschema.validate(manifest, schema)
    with zipfile.ZipFile(first / "catalog-bootstrap-assistant.pyz") as archive:
        assert archive.namelist() == sorted(manifest["members"])
        assert set(archive.namelist()) == {
            "__main__.py",
            "infra/__init__.py",
            "infra/sp500_megarun/__init__.py",
            "infra/sp500_megarun/catalog_bootstrap_binding.py",
            "infra/sp500_megarun/catalog_bootstrap_contract.py",
            "infra/sp500_megarun/catalog_bootstrap_finalizer.py",
            "infra/sp500_megarun/catalog_bootstrap_github.py",
            "infra/sp500_megarun/catalog_bootstrap_manifest.py",
            "infra/sp500_megarun/catalog_bootstrap_secrets.py",
            "infra/sp500_megarun/catalog_bootstrap_state.py",
            "infra/sp500_megarun/catalog_request_contract.py",
            "config/catalog_bootstrap_app_manifests_v1.json",
        }


def test_runner_has_closed_phase_dispatch_and_no_production_launch() -> None:
    text = RUNNER.read_text("utf-8")
    for phase in (
        "PRECHECK",
        "REQUESTER_CREATE_PENDING",
        "AUDITOR_CREATE_PENDING",
        "PUBLIC_BINDING_PENDING",
        "FINAL_AUDIT_PENDING",
    ):
        assert f'"{phase}"' in text
    allowed_block = text.split("_ALLOWED_BOOTSTRAP_WORKFLOWS", 1)[1].split(
        "_HEAVY_WORKFLOW_PATHS", 1
    )[0]
    assert "catalog-live-controls-qualification.yml" in allowed_block
    assert "catalog-controller-qualification.yml" in allowed_block
    assert "catalog-optimized-run.yml" not in allowed_block
    assert "sp500-optimized-catalog-v1" not in text
    assert "shell=True" not in text
    assert "os.startfile" not in text
    assert 'root / "browser-action-v1.json"' in text
    assert "CATALOG_BOOTSTRAP_PHASE_NOT_YET_BOUND" not in text
    assert "_pending" not in text
    assert "_REQUIRED\")" not in text
    assert '"PRECHECK": perform_precheck' in text
    assert '"FINAL_AUDIT_PENDING": perform_final_audit' in text


def test_activity_snapshot_queries_only_bounded_heavy_workflows(monkeypatch) -> None:
    namespace = runpy.run_path(str(RUNNER))
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
        endpoint = args[-1]
        if "/issues?state=all&per_page=100" in endpoint:
            return json.dumps(
                [
                    [
                        {
                            "number": 17,
                            "title": "[AURORA CATALOG RUN REQUEST] bootstrap",
                        }
                    ]
                ]
            )
        if "/actions/workflows/" in endpoint:
            workflow_name = endpoint.split("/actions/workflows/", 1)[1].split(
                "/runs?", 1
            )[0]
            return json.dumps(
                {
                    "workflow_runs": [
                        {
                            "id": len(calls) + 100,
                            "path": f".github/workflows/{workflow_name}",
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected command: {args}")

    snapshot_function = namespace["_github_activity_snapshot"]
    monkeypatch.setitem(snapshot_function.__globals__, "_run", fake_run)
    snapshot = snapshot_function()

    assert snapshot["request_issue_numbers"] == [17]
    assert len(snapshot["heavy_run_ids"]) == 4
    heavy_calls = [args for args in calls if "/actions/workflows/" in args[-1]]
    assert len(heavy_calls) == 4
    assert all("branch=main&per_page=100" in args[-1] for args in heavy_calls)
    assert not any("/actions/runs?per_page=100" in args[-1] for args in calls)
