"""Execute the workflow wrapper with only its process boundary replaced."""

import io
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import zipfile

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_worker_failure import worker_failure_artifact_name
from aurora.infra.sp500_megarun import catalog_sealed_plan


ROOT = Path(__file__).resolve().parents[1]


def _exercise(tmp_path, monkeypatch, *, change=None, artifact_change=None,
              run_change=None, member="recipe_matrix_a.json", cli_failure=False,
              job_change=None, raw_change=None, extra_member_bytes=0, archive_change=None):
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
                       "GITHUB_REPOSITORY_ID": "1232647748",
                       "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "out")}.items():
        monkeypatch.setenv(key, value)
    (tmp_path / "engine-outcome-input.json").write_text(json.dumps(payload))
    failure = worker_failure_artifact_name(execution_plan_sha256="a" * 64,
        worker_id=3, attempt_id="authority:worker:003:attempt:1")
    names = ["catalog-sealed-execution-plan-authority", "catalog-terminal-science-authority", failure]
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        entry = zipfile.ZipInfo()
        # Preserve hostile ZIP spelling; Windows ZipInfo normalizes backslashes.
        entry.filename = member
        archive.writestr(entry, json.dumps({"include": [{
            "descriptor_bundle_artifact": "bundle", "descriptor_member": "recipe/worker-003.json",
            "descriptor_sha256": "c" * 64, "worker_id": 3}]}))
        if extra_member_bytes:
            archive.writestr("logical_recipe_manifest.json", b" " * extra_member_bytes)
    archive_bytes = raw.getvalue()
    if archive_change:
        archive_bytes = archive_change(archive_bytes)
    artifacts = [dict(id=index, name=name, expired=False, created_at="2026-09-19T12:01:00Z",
                      digest="sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
                      size_in_bytes=len(archive_bytes),
                      workflow_run={"id": 123, "head_sha": "b" * 40, "head_branch": "main",
                                    "repository_id": 1232647748, "head_repository_id": 1232647748})
                 for index, name in enumerate(names, 1)]
    if artifact_change:
        artifact_change(artifacts)
    calls = []
    publisher_names = ["gate", "engine / verify_terminal_science",
                       "engine / evaluate_a (bundle, recipe/worker-003.json, " + "c" * 64 + ", 3) / evaluate"]
    # The server truncates each matrix job display component to 100 characters.
    publisher_names[2] = "engine / " + publisher_names[2][9:-11][:97] + "... / evaluate"
    jobs = [dict(id=index, name=name, run_id=123, run_attempt=2, head_sha="b" * 40,
                 status="completed", conclusion="failure" if index == 3 else "success",
                 steps=[dict(name=publish, status="completed", conclusion="success",
                             started_at="2026-09-19T12:00:59Z", completed_at="2026-09-19T12:01:00Z")])
            for index, (name, publish) in enumerate(zip(publisher_names, [
                "Publish the already-materialized sealed plan", "Publish terminal science evidence",
                "Publish the sealed failed worker attempt"], strict=True), 1)]
    if job_change:
        job_change(jobs)

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is True
        if command[:2] == ["gh", "api"]:
            if command[2].endswith("/zip"):
                return subprocess.CompletedProcess(command, 0, raw_change(archive_bytes) if raw_change else archive_bytes)
            elif command[2].endswith("/jobs?per_page=100"):
                assert command[2] == "repos/owner/repo/actions/runs/123/attempts/2/jobs?per_page=100"
                result = [{"jobs": jobs, "total_count": len(jobs)}]
            elif "/attempts/" in command[2]:
                result = dict(id=123, run_attempt=2, head_sha="b" * 40,
                              run_started_at="2026-09-19T12:00:00Z", head_branch="main",
                              path=".github/workflows/catalog-fast-controller.yml",
                              repository={"id": 1232647748, "full_name": "owner/repo"})
                if run_change:
                    run_change(result)
            else:
                assert command[2] == "repos/owner/repo/actions/runs/123/artifacts?per_page=100"
                result = [{"artifacts": artifacts, "total_count": len(artifacts)}]
            return subprocess.CompletedProcess(command, 0, json.dumps(result))
        if cli_failure:
            raise subprocess.CalledProcessError(2, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)

    class Download:
        def __init__(self, command, **kwargs):
            assert kwargs["stdout"] == subprocess.PIPE
            class BoundedStream(io.BytesIO):
                def read(self, size=-1):
                    assert 0 < size <= 64 * 1024 * 1024 + 1
                    return super().read(size)

            self.stdout = BoundedStream(run(command, check=True).stdout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stdout.close()

        def kill(self):
            pass

        def wait(self, **kwargs):
            return 0

    monkeypatch.setattr(subprocess, "Popen", Download)
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


@pytest.mark.parametrize("mutate", [
    lambda a: a[0].update(digest="sha256:" + "0" * 64),
    lambda a: a[0].pop("digest"),
    lambda a: a[0].update(size_in_bytes=0),
    lambda a: a[0].update(size_in_bytes=64 * 1024 * 1024 + 1),
    lambda a: a[0].update(size_in_bytes=a[0]["size_in_bytes"] + 1),
    lambda a: a[0]["workflow_run"].update(head_repository_id=456),
])
def test_transport_metadata_is_enforced(tmp_path, monkeypatch, mutate):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME"):
        _exercise(tmp_path, monkeypatch, artifact_change=mutate)


def test_downloaded_bytes_must_match_digest_and_size(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME"):
        _exercise(tmp_path, monkeypatch, raw_change=lambda raw: raw + b"extra")


@pytest.mark.parametrize("mutate", [
    lambda j: j[0].update(name="untrusted-plan-publisher"),
    lambda j: j[1].update(name="engine / audit_runtime"),
    lambda j: j[2].update(name=j[2]["name"].replace("worker-003", "worker-004")),
    lambda j: j[2].update(name=j[2]["name"].replace("evaluate_a", "recovery_wave_1")),
    lambda j: j[2].update(conclusion="cancelled"),
    lambda j: j[2].update(conclusion="success"),
    lambda j: j[2].update(run_attempt=1),
    lambda j: j[2].update(head_sha="0" * 40),
    lambda j: j[2]["steps"][0].update(conclusion="failure"),
    lambda j: j[2]["steps"][0].update(name="wrong publish step"),
    lambda j: j[2]["steps"][0].update(started_at="2026-09-19T12:01:01Z"),
    lambda j: j.append({**j[2], "id": 10}),
])
def test_exact_publisher_and_successful_publication_are_required(tmp_path, monkeypatch, mutate):
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_OUTCOME"):
        _exercise(tmp_path, monkeypatch, job_change=mutate)


def test_real_sp_sized_manifest_is_not_rejected_by_small_cap(tmp_path, monkeypatch):
    _exercise(tmp_path, monkeypatch, extra_member_bytes=9_881_185)
    assert (tmp_path / "recovered-outcome-proof/sealed-plan/logical_recipe_manifest.json").stat().st_size == 9_881_185


@pytest.mark.parametrize("file_sizes,reason", [
    ([65 * 1024 * 1024], "ARCHIVE_MEMBER_SIZE_INVALID"),
    ([50 * 1024 * 1024] * 3, "ARCHIVE_TOTAL_SIZE_INVALID"),
])
def test_expansion_limits_are_checked_before_extraction(tmp_path, monkeypatch, file_sizes, reason):
    def oversized_headers(_raw):
        # Honest transport hash, hostile central-directory sizes; no large allocation.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for index in range(len(file_sizes)):
                archive.writestr(f"member-{index}.json", b"{}")
        raw = bytearray(buffer.getvalue())
        position = 0
        for size in file_sizes:
            position = raw.index(b"PK\x01\x02", position)
            struct.pack_into("<II", raw, position + 20, size, size)
            position += 4
        return bytes(raw)

    with pytest.raises(ValueError, match=f"CATALOG_RECOVERED_OUTCOME_{reason}"):
        _exercise(tmp_path, monkeypatch, archive_change=oversized_headers)
    assert not list((tmp_path / "recovered-outcome-proof").rglob("member-*.json"))
