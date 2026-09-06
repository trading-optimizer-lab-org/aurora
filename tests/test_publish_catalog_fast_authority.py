"""Run the actual publication CLI with transport-only doubles; no GitHub writes."""

from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityEditBindingV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1, CatalogTerminalReceiptV1, CatalogTerminalReceiptV2, CatalogTerminalReceipt
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from tests.test_catalog_fast_authority_github import publication_transport
from tests.test_inspect_catalog_fast_request import _signed_request
from tests.test_catalog_fast_path import NOW


@pytest.mark.parametrize(("phase", "fault", "version"), [(phase, fault, "1") for phase in ("gate", "finalize")
    for fault in (None, "write_rejected", "foreign_decision", "reusable")] + [("finalize", "foreign_receipt", "1")]
    + [("finalize", fault, "2") for fault in (None, "write_rejected", "foreign_decision", "reusable", "foreign_receipt")])
def test_reservation_cli_stages_only_its_authenticated_request(tmp_path, monkeypatch, fault, phase, version):
    from scripts import publish_catalog_fast_authority as command

    fixture = publication_transport()
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config/catalog_authority_anchor_v1.json").write_text(json.dumps(fixture.anchor))
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    (root / "requester.pem").write_bytes(public)
    (root / "config/catalog_controller_actors_v1.json").write_text(json.dumps({
        "requester_public_key_path": "requester.pem", "request_actors": ["requester"]}))
    title, body = _signed_request(private)
    request = parse_catalog_run_request(title, body, public)
    run_id = 234 if phase == "gate" else 123
    if phase == "finalize":
        current = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(request=request, issue_number=280, run_id=123)
        fixture = publication_transport(state=current, phase="gate", reusable_issue_number=280 if fault == "reusable" else None)
    context = {"request": request.model_dump(mode="json"), "issue_number": 280, "actor": "requester",
        "protected_commit_sha": "a" * 40, "logical_recipe_count": 1}
    context["content_sha256"] = canonical_sha256(context)
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context))
    decision = CatalogFastLaunchDecisionV1.create(state="QUEUED", reason_code="CATALOG_READY",
        request_sha256="f" * 64 if fault == "foreign_decision" else request.request_sha256,
        submission_key_sha256=request.submission_key_sha256, campaign_key=request.campaign_key,
        prepared_receipt_sha256="1" * 64, selected_workers=1, launch_required=True, existing_run_id=None,
        decided_at=NOW, expires_at=NOW + timedelta(minutes=5))
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(decision.model_dump_json())
    receipt: CatalogTerminalReceipt = CatalogTerminalReceiptV1.create(state="BLOCKED", reason_code="CATALOG_ENGINE_OUTCOME_MISSING",
        request_sha256=request.request_sha256, submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key, prepared_receipt_sha256="1" * 64, engine_run_id=999 if fault == "foreign_receipt" else run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run_id}",
        expected_recipe_count=1, observed_recipe_count=0, queue_seconds=0.0, preparation_seconds=0.0,
        computation_seconds=0.0, recovery_seconds=0.0, reduction_seconds=0.0, recovered_block_count=0,
        failure_class="infrastructure", result_science_sha256=None, created_at=NOW)
    if version == "2":
        values = receipt.model_dump(exclude={"schema_version", "receipt_sha256", "queue_seconds", "preparation_seconds",
            "computation_seconds", "recovery_seconds", "reduction_seconds", "recovered_block_count"})
        receipt = CatalogTerminalReceiptV2.create(**values, timing={}, recovered_block_ids=None)
    receipt_path = tmp_path / "terminal.json"
    receipt_path.write_text(receipt.model_dump_json())
    calls = []
    old_get = fixture.client.get_json

    def get_json(path):
        if path.endswith("/issues/280"):
            return {"number": 280, "title": title, "body": body, "user": {"login": "requester"}}, None
        if path.endswith(f"/actions/runs/{run_id}"):
            if fault == "reusable":
                return {**fixture.run, "id": run_id, "path": ".github/workflows/catalog-request-reconciler.yml", "event": "schedule",
                    "referenced_workflows": [{"path": fixture.client.repository + "/.github/workflows/catalog-fast-controller.yml@" + "a" * 40,
                        "sha": "a" * 40, "ref": "refs/heads/main"}]}, None
            return {**fixture.run, "id": run_id, "path": ".github/workflows/catalog-fast-controller.yml", "event": "issues"}, None
        if path.endswith(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1"):
            return {"total_count": 1, "jobs": [{"id": 790, "name": f"catalog-request-280 / {phase}" if fault == "reusable" else phase, "run_id": run_id,
                "run_attempt": 1, "head_sha": "a" * 40, "status": "in_progress"}]}, None
        return old_get(path)

    fixture.client.get_json = get_json

    def process(args, **kwargs):
        if args[0] == "git":
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        if args == ["gh", "api", "graphql", "--input", "-"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(fixture.edit))
        assert args == ["gh", "api", "--method", "PATCH", "repos/" + fixture.client.repository + "/issues/161", "--input", "-"]
        calls.append(args)
        if fault == "write_rejected":
            return SimpleNamespace(returncode=1, stdout="")
        issue = fixture.edit["data"]["repository"]["issue"]
        issue["body"] = json.loads(kwargs["input"])["body"]
        issue["lastEditedAt"] = "2026-09-05T12:00:02Z"
        issue["userContentEdits"]["nodes"][0].update(id="E_written", editedAt=issue["lastEditedAt"])
        return SimpleNamespace(returncode=0, stdout="{}")

    monkeypatch.setattr(command.subprocess, "run", process)
    monkeypatch.setattr(command, "CatalogGitHubReadOnlyClient", lambda *args: fixture.client)
    monkeypatch.setattr(command, "_download_owner_archive", lambda *args: fixture.raw)
    for name, value in {"GH_TOKEN": "fixture-only", "GITHUB_REPOSITORY": fixture.client.repository,
        "CATALOG_PROTECTED_COMMIT_SHA": "a" * 40, "RUNNER_TEMP": str(tmp_path), "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": str(run_id), "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": phase}.items():
        monkeypatch.setenv(name, value)
    output = tmp_path / "publication.json"
    github_output = tmp_path / "github-output"
    code = command.main(["--repo-root", str(root), "--phase", phase, "--request-context", str(context_path),
        "--decision", str(decision_path), "--output", str(output), "--github-output", str(github_output)] +
        (["--terminal-receipt", str(receipt_path)] if phase == "finalize" else []))
    if fault in {None, "reusable"}:
        assert code == 0
        assert github_output.read_text().strip() == f"authority_artifact_name=catalog-fast-authority-{run_id}-1-{phase}-790"
        publication = FastAuthorityEditBindingV1.model_validate_json(output.read_text())
        assert publication.state.campaigns[0].owner_run_id == run_id
        assert publication.state.campaigns[0].owner_issue_number == 280
        assert publication.edit_node_id == "E_written"
        assert len(calls) == 1
        assert publication.state.campaigns[0].terminal_receipt_sha256 == (receipt.receipt_sha256 if phase == "finalize" else None)
        # Upload boundary packages the CLI's actual bytes, not a new model dump.
        uploaded = publication_transport(state=publication.state, phase=phase, run_id=run_id,
            job_id=790, edit_id="E_written", publication_bytes=output.read_bytes(),
            reusable_issue_number=280 if fault == "reusable" else None)
        assert uploaded.edit["data"]["repository"]["issue"]["body"] == fixture.edit["data"]["repository"]["issue"]["body"]
        reopened = load_current_fast_authority(client=uploaded.client, anchor=uploaded.anchor,
            protected_commit="a" * 40, read_edit=lambda: uploaded.edit, download_archive=lambda _: uploaded.raw)
        assert reopened == publication.state
        if fault == "reusable":
            uploaded.run["referenced_workflows"][0]["sha"] = "b" * 40
            with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_PRODUCER_INVALID"):
                load_current_fast_authority(client=uploaded.client, anchor=uploaded.anchor,
                    protected_commit="a" * 40, read_edit=lambda: uploaded.edit, download_archive=lambda _: uploaded.raw)
            uploaded.run["referenced_workflows"][0]["sha"] = "a" * 40
            uploaded.job["name"] = f"catalog-request-999 / {phase}"
            with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_OWNER_MISMATCH"):
                load_current_fast_authority(client=uploaded.client, anchor=uploaded.anchor,
                    protected_commit="a" * 40, read_edit=lambda: uploaded.edit, download_archive=lambda _: uploaded.raw)
    else:
        assert code == 2
        assert not output.exists()
        assert len(calls) == (1 if fault == "write_rejected" else 0)


def test_gate_durable_publication_is_verified_before_queue_exposure():
    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["gate"]["steps"]
    ids = [step.get("id") for step in steps]
    assert ids.index("write_authority") < ids.index("publish_authority") < ids.index("verify_authority") < ids.index("reserve")
    for name in ("write_authority", "publish_authority", "verify_authority"):
        step = steps[ids.index(name)]
        assert step.get("continue-on-error", False) is (name == "publish_authority")
        assert "steps.admit.outputs.launch_required == 'true'" in step["if"]


def test_terminal_durable_publication_precedes_release():
    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["finalize"]["steps"]
    ids = [step.get("id") for step in steps]
    assert ids.index("publish_receipt") < ids.index("write_authority") < ids.index("publish_authority") < ids.index("verify_authority") < ids.index("publish_terminal")
