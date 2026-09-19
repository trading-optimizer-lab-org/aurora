"""Execute the workflow wrapper with only its process boundary replaced."""

import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_worker_failure import worker_failure_artifact_name
from aurora.infra.sp500_megarun import catalog_sealed_plan


ROOT = Path(__file__).resolve().parents[1]


def _exercise(tmp_path, monkeypatch, *, change=None, artifact_change=None,
              run_change=None, member="recipe_matrix_a.json", cli_failure=False):
    step = next(s for s in load_github_yaml(
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    )["jobs"]["campaign_outcome"]["steps"] if s.get("id") == "outcome")
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    payload = {
        "authority_id": "authority", "execution_plan_sha256": "a" * 64,
        "engine_run_id": 123, "engine_run_attempt": 2,
        "protected_commit_sha": "b" * 40, "reduction_only": False,
        "recovery_statuses": ["retry", "complete"],
        "stage_results": {name: "success" for name in (
            "engine_verify_sealed_plan", "prepare_runtime_and_inputs",
            "publish_sealed_payload_artifacts", "verify_component_store",
            "reconcile_wave_0", "ready_to_merge", "reduce_groups", "reduce",
            "verify_terminal_science", "audit_runtime")},
    }
    payload["stage_results"]["evaluate_a"] = "failure"
    payload.update(request_sha256="c" * 64, campaign_id="campaign",
                   science_sha256="d" * 64, execution_protocol_sha256="e" * 64)
    if change:
        change(payload)
    monkeypatch.chdir(tmp_path)
    for key, value in {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                       "GITHUB_SHA": "b" * 40, "GITHUB_REPOSITORY": "owner/repo",
                       "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "out")}.items():
        monkeypatch.setenv(key, value)
    (tmp_path / "engine-outcome-input.json").write_text(json.dumps(payload))
    failure = worker_failure_artifact_name(execution_plan_sha256="a" * 64,
        worker_id=3, attempt_id="authority:worker:003:attempt:1")
    names = ["catalog-sealed-execution-plan-authority", "catalog-terminal-science-authority", failure]
    artifacts = [dict(id=index, name=name, expired=False, created_at="2026-09-19T12:01:00Z",
                      workflow_run={"id": 123, "head_sha": "b" * 40})
                 for index, name in enumerate(names, 1)]
    if artifact_change:
        artifact_change(artifacts)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is True
        if command[:2] == ["gh", "api"]:
            if command[2].endswith("/zip"):
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, "w") as archive:
                    entry = zipfile.ZipInfo()
                    # Preserve hostile ZIP spelling; Windows ZipInfo normalizes backslashes.
                    entry.filename = member
                    archive.writestr(entry, json.dumps({"include": [{"worker_id": 3}]}))
                return subprocess.CompletedProcess(command, 0, raw.getvalue())
            elif "/attempts/" in command[2]:
                result = dict(id=123, run_attempt=2, head_sha="b" * 40,
                              run_started_at="2026-09-19T12:00:00Z")
                if run_change:
                    run_change(result)
            else:
                assert command[2] == "repos/owner/repo/actions/runs/123/artifacts?per_page=100"
                result = [{"artifacts": artifacts}]
            return subprocess.CompletedProcess(command, 0, json.dumps(result))
        if cli_failure:
            raise subprocess.CalledProcessError(2, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    verified = []

    def verify(path, *, expected_bindings):
        assert path == tmp_path / "recovered-outcome-proof/sealed-plan"
        assert expected_bindings == {key: payload[key] for key in (
            "request_sha256", "authority_id", "campaign_id", "science_sha256",
            "execution_plan_sha256", "execution_protocol_sha256", "protected_commit_sha")}
        verified.append(path)

    monkeypatch.setattr(catalog_sealed_plan, "verify_sealed_global_reuse_execution_plan", verify)
    exec(compile(source, str(ROOT / ".github/workflows/catalog-optimized-run.yml"), "exec"), {})
    assert bool(verified) == any("--sealed-plan" in c for c in calls)
    return calls, names


def test_recovered_proof_downloads_exact_current_run_and_passes_all_three(tmp_path, monkeypatch):
    calls, names = _exercise(tmp_path, monkeypatch)
    downloads = [c for c in calls if c[:2] == ["gh", "api"] and c[2].endswith("/zip")]
    assert [c[2] for c in downloads] == [f"repos/owner/repo/actions/artifacts/{i}/zip" for i in (1, 2, 3)]
    assert [p.name for p in (tmp_path / "recovered-outcome-proof/failures").iterdir()] == [names[-1]]
    command = calls[-1]
    for flag, suffix in (("--sealed-plan", "sealed-plan"),
                         ("--recovered-science-index", "science/catalog_terminal_science_index_v1.json"),
                         ("--recovered-failure-root", "failures")):
        assert Path(command[command.index(flag) + 1]).as_posix().endswith(suffix)


@pytest.mark.parametrize("change", [
    lambda p: p.update(reduction_only=True),
    lambda p: p.update(recovery_statuses=["retry"]),
    lambda p: p["stage_results"].update(evaluate_a="success"),
    lambda p: p["stage_results"].update(evaluate_b="cancelled"),
    lambda p: p["stage_results"].update(audit_runtime="failure"),
    lambda p: p["stage_results"].update(verify_terminal_science="skipped"),
])
def test_ineligible_never_downloads_or_supplies_proof(tmp_path, monkeypatch, change):
    calls, _ = _exercise(tmp_path, monkeypatch, change=change)
    assert len(calls) == 1
    assert "--recovered-science-index" not in calls[0]


@pytest.mark.parametrize("mutate", [
    lambda a: a[0].update(expired=True),
    lambda a: a[0]["workflow_run"].update(id=456),
    lambda a: a[0]["workflow_run"].update(head_sha="c" * 40),
    lambda a: a[0].update(created_at="2026-09-19T11:59:00Z"),
    lambda a: a.append(dict(a[0])),
    lambda a: a.pop(),
])
def test_bad_or_missing_origin_fails_closed(tmp_path, monkeypatch, mutate):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME"):
        _exercise(tmp_path, monkeypatch, artifact_change=mutate)


def test_ignores_retry_and_unrelated_artifacts(tmp_path, monkeypatch):
    def add(artifacts):
        for index, name in enumerate(("unrelated", worker_failure_artifact_name(
                execution_plan_sha256="a" * 64, worker_id=3,
                attempt_id="authority:worker:003:attempt:2")), 10):
            artifacts.append({**artifacts[-1], "id": index, "name": name})

    calls, _ = _exercise(tmp_path, monkeypatch, artifact_change=add)
    assert len([c for c in calls if c[0] == "gh" and c[2].endswith("/zip")]) == 3


@pytest.mark.parametrize("key,value", [("id", 456), ("run_attempt", 1), ("head_sha", "c" * 40)])
def test_authenticated_run_must_match_current_attempt(tmp_path, monkeypatch, key, value):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME_RUN_ORIGIN_INVALID"):
        _exercise(tmp_path, monkeypatch, run_change=lambda run: run.update({key: value}))


@pytest.mark.parametrize("key,value", [("engine_run_id", 456), ("engine_run_attempt", 1),
                                        ("protected_commit_sha", "c" * 40)])
def test_input_must_match_current_environment(tmp_path, monkeypatch, key, value):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME_CURRENT_RUN_INVALID"):
        _exercise(tmp_path, monkeypatch, change=lambda payload: payload.update({key: value}))


@pytest.mark.parametrize("member", ["../escape.json", "/absolute.json", "C:/escape.json", "a\\b.json"])
def test_archive_paths_fail_closed(tmp_path, monkeypatch, member):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME_ARCHIVE_INVALID"):
        _exercise(tmp_path, monkeypatch, member=member)


def test_proof_consumer_failure_is_not_swallowed(tmp_path, monkeypatch):
    with pytest.raises(subprocess.CalledProcessError) as error:
        _exercise(tmp_path, monkeypatch, cli_failure=True)
    assert error.value.returncode == 2
