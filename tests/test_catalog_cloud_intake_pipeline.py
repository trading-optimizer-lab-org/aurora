"""Four real intake phases; only GitHub/process transport is synthetic."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

from aurora.infra.sp500_megarun import catalog_cloud_app as app_module
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
from aurora.infra.sp500_megarun.catalog_cloud_qualification import CloudQualificationReceiptV1
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1, FastAuthorityEditBindingV1
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1, canonical_model_bytes, canonical_sha256
from aurora.infra.sp500_megarun.catalog_requester_broker import CatalogBrokerHttpResponse
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts import catalog_cloud_intake as phases
from scripts import publish_catalog_cloud_authority as publisher
from scripts import validate_catalog_cloud_intent as validator
from tests.test_catalog_cloud_app import _make_repo, _private_key, _SyntheticTransport, EXPECTED_ACTOR
from tests.test_catalog_cloud_cutover import write_retirement
from tests.test_catalog_fast_authority_github import publication_transport
from tests.test_validate_catalog_cloud_intent import _event


ROOT = Path(__file__).resolve().parents[1]
REPO = "trading-optimizer-lab-org/aurora"
SHA = "a" * 40
NOW = datetime(2026, 9, 17, 15, 1, tzinfo=timezone.utc)
QUALIFICATION_RUN_ID = 700
QUALIFICATION_ATTEMPT = 1
QUALIFICATION_JOB_ID = 701
QUALIFICATION_ARTIFACT_ID = 702


def _qualification_frontier(public_key_sha256):
    job_started = "2026-09-17T14:58:00Z"
    step_started = "2026-09-17T14:58:10Z"
    step_completed = "2026-09-17T14:58:50Z"
    job_completed = "2026-09-17T14:59:00Z"
    observed_at = datetime(2026, 9, 17, 14, 58, 30, tzinfo=timezone.utc)
    run = {
        "id": QUALIFICATION_RUN_ID,
        "run_attempt": QUALIFICATION_ATTEMPT,
        "head_sha": SHA,
        "head_branch": "main",
        "path": ".github/workflows/catalog-cloud-qualification.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "repository": {"id": 1232647748, "full_name": REPO},
        "actor": {"id": 271768688},
        "triggering_actor": {"id": 271768688},
    }
    job = {
        "id": QUALIFICATION_JOB_ID,
        "name": "qualify",
        "run_id": QUALIFICATION_RUN_ID,
        "run_attempt": QUALIFICATION_ATTEMPT,
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "started_at": job_started,
        "completed_at": job_completed,
        "steps": [{
            "name": "Qualify existing requester App without scientific publication",
            "status": "completed",
            "conclusion": "success",
            "started_at": step_started,
            "completed_at": step_completed,
        }],
    }
    unsigned = CloudQualificationReceiptV1.model_construct(
        schema_version="1",
        repository=REPO,
        repository_id=1232647748,
        producer_run_id=QUALIFICATION_RUN_ID,
        producer_run_attempt=QUALIFICATION_ATTEMPT,
        producer_job_id=QUALIFICATION_JOB_ID,
        producer_commit=SHA,
        actor_id=271768688,
        app_id=4693452,
        installation_id=155982969,
        requester_public_key_sha256=public_key_sha256,
        permissions=(("issues", "write"), ("metadata", "read")),
        signed_test_request_sha256="d" * 64,
        observed_at=observed_at,
        receipt_sha256="0" * 64,
    )
    receipt = CloudQualificationReceiptV1.model_validate({
        **unsigned.model_dump(mode="json"),
        "receipt_sha256": canonical_sha256(unsigned),
    })
    receipt_bytes = canonical_model_bytes(receipt) + b"\n"
    archive_stream = io.BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("catalog-cloud-qualification-v1.json", receipt_bytes)
    archive_bytes = archive_stream.getvalue()
    artifact = {
        "id": QUALIFICATION_ARTIFACT_ID,
        "name": f"catalog-cloud-qualification-v1-{QUALIFICATION_RUN_ID}-{QUALIFICATION_ATTEMPT}",
        "expired": False,
        "size_in_bytes": len(archive_bytes),
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
        "created_at": "2026-09-17T14:58:30Z",
        "expires_at": "2026-09-18T15:00:00Z",
        "workflow_run": {
            "id": QUALIFICATION_RUN_ID,
            "run_attempt": QUALIFICATION_ATTEMPT,
            "head_sha": SHA,
            "head_branch": "main",
            "repository_id": 1232647748,
            "head_repository_id": 1232647748,
        },
    }
    return run, job, artifact, archive_bytes


class Network:
    repository = REPO
    observed_at = NOW

    def __init__(self, live):
        self.live = live
        self.scientific_issue = None
        self.report_comments = []
        self.qualification_reads = []
        self.qualification_run = None
        self.qualification_job = None
        self.qualification_artifact = None
        self.qualification_archive = None
        self._token = "synthetic-job-token"
        self.writes = 0
        self.set_publication(FastAuthorityStateV1.bootstrap(campaigns=()), "bootstrap", "E_current")

    def set_publication(self, state, phase, edit_id, raw_publication=None):
        self.fixture = publication_transport(state=state, phase=phase, edit_id=edit_id,
            run_id=99 if phase == "bootstrap" else 123, publication_bytes=raw_publication)
        f = self.fixture
        if phase != "bootstrap":
            f.run.update(path=".github/workflows/catalog-cloud-intake.yml", event="issues",
                actor={"id": 271768688}, triggering_actor={"id": 271768688})
            f.run["repository"]["id"] = 1232647748
            f.artifact["workflow_run"].update(repository_id=1232647748, head_repository_id=1232647748)
            f.job["name"] = "intake"
            for step in f.job["steps"]:
                step["name"] += f" ({phase})"
        # Move the fixture clock as a unit, retaining every verified interval.
        for container in (f.edit, f.artifact, f.job):
            rendered = json.dumps(container).replace("2026-09-05T12:", "2026-09-17T15:")
            container.clear()
            container.update(json.loads(rendered))

    def current_run(self):
        return {"id": 123, "run_attempt": 1, "head_sha": SHA, "head_branch": "main",
            "path": ".github/workflows/catalog-cloud-intake.yml", "event": "issues",
            "repository": {"id": 1232647748, "node_id": "R_repo", "full_name": REPO},
            "actor": {"id": 271768688}, "triggering_actor": {"id": 271768688}}

    def get_json(self, path):
        prefix = f"/repos/{REPO}"
        qualification_prefix = f"{prefix}/actions/runs/{QUALIFICATION_RUN_ID}"
        if path == qualification_prefix:
            self.qualification_reads.append(path)
            return deepcopy(self.qualification_run), None
        if path == (f"{qualification_prefix}/attempts/{QUALIFICATION_ATTEMPT}/jobs"
                    "?per_page=100&page=1"):
            self.qualification_reads.append(path)
            return {"total_count": 1, "jobs": [deepcopy(self.qualification_job)]}, None
        if path == (f"{qualification_prefix}/artifacts"
                    f"?name=catalog-cloud-qualification-v1-{QUALIFICATION_RUN_ID}-{QUALIFICATION_ATTEMPT}"
                    "&per_page=100"):
            self.qualification_reads.append(path)
            return {"total_count": 1, "artifacts": [deepcopy(self.qualification_artifact)]}, None
        if path == prefix + "/issues/400":
            return deepcopy(self.live), None
        if path == prefix + "/issues/401":
            return deepcopy(self.scientific_issue), None
        if path.startswith(prefix + "/issues/400/comments?"):
            return deepcopy(self.report_comments), None
        if path in {prefix + "/actions/runs/123", prefix + "/actions/runs/123/attempts/1"}:
            return self.current_run(), None
        if path == prefix + "/actions/runs/123/attempts/1/jobs?per_page=100&page=1":
            return {"jobs": [{"id": 789, "name": "intake", "run_id": 123, "run_attempt": 1,
                "head_sha": SHA, "status": "in_progress", "started_at": "2026-09-17T15:00:00Z"}]}, None
        return self.fixture.client.get_json(path)

    def patch(self, command, **kwargs):
        assert command == ["gh", "api", "--method", "PATCH", f"repos/{REPO}/issues/161", "--input", "-"]
        self.writes += 1
        issue = self.fixture.edit["data"]["repository"]["issue"]
        issue["body"] = json.loads(kwargs["input"])["body"]
        issue["userContentEdits"]["nodes"][0]["id"] = f"E_written_{self.writes}"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def upload(self, work, phase):
        raw = (work / f"intake-{phase}" / "catalog-fast-authority-publication-v1.json").read_text("utf-8")
        binding = FastAuthorityEditBindingV1.model_validate_json(raw)
        self.set_publication(binding.state, f"intake-{phase}", binding.edit_node_id, raw)


class AppTransport(_SyntheticTransport):
    def __init__(self, network, lost_response=False):
        super().__init__()
        self.network = network
        self.posts = 0
        self.lost_response = lost_response

    def request(self, method, url, *, headers, json_body=None):
        if method == "POST" and url == f"https://api.github.com/repos/{REPO}/issues":
            self.posts += 1
            self.network.scientific_issue = {
                "number": 401, "title": json_body["title"], "body": json_body["body"],
                "user": {"login": EXPECTED_ACTOR}, "state": "open",
                "created_at": "2026-09-17T15:00:10Z", "updated_at": "2026-09-17T15:00:10Z",
                "html_url": f"https://github.com/{REPO}/issues/401",
            }
            if self.lost_response:
                raise TimeoutError("synthetic accepted response lost")
            return CatalogBrokerHttpResponse(status_code=201, headers={}, json_body={"number": 401})
        if method == "GET" and url == f"https://api.github.com/repos/{REPO}/issues/401":
            return CatalogBrokerHttpResponse(status_code=200, headers={}, json_body=self.network.scientific_issue)
        if method == "GET" and "/issues?" in url:
            return CatalogBrokerHttpResponse(status_code=200, headers={},
                json_body=[] if self.network.scientific_issue is None else [self.network.scientific_issue])
        return super().request(method, url, headers=headers, json_body=json_body)


class ReportFrontier:
    """Synthetic GitHub comment boundary, including an accepted lost response."""

    def __init__(self, network, *, lost_response=False):
        self.network = network
        self.lost_response = lost_response
        self.posts = 0

    def run(self, command, *, input=None, capture_output=False, text=False,
            timeout=None, check=False, stdout=None, stderr=None, env=None):
        if command == [
            "gh", "api", "--method", "GET",
            f"repos/{REPO}/actions/artifacts/{QUALIFICATION_ARTIFACT_ID}/zip",
        ]:
            assert stdout is not None
            stdout.write(self.network.qualification_archive)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if command == [
            "gh", "api", "--method", "POST",
            f"repos/{REPO}/issues/400/comments", "--input", "-",
        ]:
            assert capture_output is True and text is True and timeout == 30 and check is False
            payload = json.loads(input)
            comment = {
                "id": 800 + self.posts + 1,
                "body": payload["body"],
                "user": {"login": "github-actions[bot]"},
            }
            self.posts += 1
            self.network.report_comments.append(comment)
            if self.lost_response:
                raise subprocess.TimeoutExpired(command, timeout)
            return SimpleNamespace(returncode=0, stdout=json.dumps(comment), stderr="")
        return self.network.patch(command, input=input, capture_output=capture_output,
            text=text, timeout=timeout, check=check)


def setup_pipeline(tmp_path, monkeypatch, *, lost_response=False, lost_report_response=False):
    root, private_pem, public_pem = _make_repo(tmp_path, _private_key())
    registry = json.loads((ROOT / "config/catalog_campaign_registry_v1.json").read_text("utf-8"))
    entry = registry["campaigns"][0]
    (root / "config/catalog_campaign_registry_v1.json").write_text(json.dumps({"schema_version": "1", "campaigns": [entry]}), encoding="utf-8")
    (root / "config/catalog_cloud_intake_policy_v1.json").write_bytes((ROOT / "config/catalog_cloud_intake_policy_v1.json").read_bytes())
    for key, relative in entry.items():
        if key.endswith("_path") or key == "catalog_dir":
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if key == "catalog_dir":
                path.mkdir(exist_ok=True)
            else:
                path.write_text("{}", encoding="utf-8")
    manifest_path = root / entry["definition_manifest_path"]
    manifest_path.write_bytes((ROOT / entry["definition_manifest_path"]).read_bytes())
    manifest = parse_catalog_campaign_definition_bytes(manifest_path.read_bytes())
    prompt = b"Synthetic transport integration; no scientific execution.\n"
    prompt_path = root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_bytes(prompt)
    ticket = CatalogLaunchTicketV1(schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000001",
        campaign_key=entry["campaign_key"], launch_generation=1, previous_terminal_request_sha256=None,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt).hexdigest())
    write_retirement(root, ticket)
    event, live = _event()
    for issue in (event["issue"], live):
        issue["created_at"] = issue["updated_at"] = "2026-09-17T14:55:00Z"
    network = Network(live)
    actors = json.loads((root / "config/catalog_controller_actors_v1.json").read_text("utf-8"))
    (
        network.qualification_run,
        network.qualification_job,
        network.qualification_artifact,
        network.qualification_archive,
    ) = _qualification_frontier(actors["requester_public_key_sha256"])
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    environment = {
        "GITHUB_ACTIONS": "true", "GITHUB_JOB": "intake", "GITHUB_REF": "refs/heads/main",
        "GITHUB_REF_NAME": "main", "GITHUB_REPOSITORY": REPO, "GITHUB_SHA": SHA,
        "CATALOG_PROTECTED_COMMIT_SHA": SHA, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        "GH_TOKEN": "synthetic-job-token", "CATALOG_CLOUD_INTAKE_MODE": "OPEN_REGISTERED",
        "CATALOG_CLOUD_QUALIFICATION_RUN_ID": str(QUALIFICATION_RUN_ID),
        "GITHUB_EVENT_NAME": "issues", "GITHUB_EVENT_PATH": str(event_path), "RUNNER_TEMP": str(tmp_path),
        "CATALOG_REQUESTER_PRIVATE_KEY": private_pem.decode("utf-8"),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    anchor = network.fixture.anchor
    (root / "config/catalog_authority_anchor_v1.json").write_text(json.dumps(anchor), encoding="utf-8")
    monkeypatch.setattr(validator, "_git_head", lambda _: SHA)
    monkeypatch.setattr(validator, "_make_client", lambda *_: network)
    monkeypatch.setattr(validator, "read_live_edit", lambda _: network.fixture.edit)
    monkeypatch.setattr(validator, "_download_owner_archive", lambda *_: network.fixture.raw)
    monkeypatch.setattr(publisher, "read_live_edit", lambda _: network.fixture.edit)
    monkeypatch.setattr(phases, "CatalogGitHubReadOnlyClient", lambda *_: network)
    transport = AppTransport(network, lost_response)
    monkeypatch.setattr(app_module, "RequestsCatalogBrokerHttpTransport", lambda **_: transport)
    report_frontier = ReportFrontier(network, lost_response=lost_report_response)
    network.report_frontier = report_frontier
    monkeypatch.setattr(publisher.subprocess, "run", report_frontier.run)
    return root, tmp_path / "work", network, transport, ticket, public_pem


def test_real_four_phase_pipeline_and_replay_without_key(tmp_path, monkeypatch):
    root, work, network, transport, ticket, public = setup_pipeline(tmp_path, monkeypatch)
    for phase in ("signed", "uncertain", "post", "published"):
        assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", phase]) == 0
        if phase != "post":
            network.upload(work, phase)
    context = validator.load_validated_cloud_context(root)
    assert context.status == "PUBLICADO" and context.replay.issue_number == 401
    request = parse_catalog_run_request(network.scientific_issue["title"], network.scientific_issue["body"], public)
    assert request.request_id == ticket.request_id and request.launch_ticket_sha256 == ticket.launch_ticket_sha256
    assert network.writes == 3 and transport.posts == 1
    assert network.qualification_reads
    assert len([call for call in transport.calls if call[0] == "DELETE"]) == 2
    original = context.replay.body
    monkeypatch.delenv("CATALOG_REQUESTER_PRIVATE_KEY")
    assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", "signed"]) == 0
    assert validator.load_validated_cloud_context(root).replay.body == original
    assert network.writes == 3 and transport.posts == 1


def test_real_pipeline_reconciles_a_lost_post_response(tmp_path, monkeypatch):
    root, work, network, transport, _, _ = setup_pipeline(tmp_path, monkeypatch, lost_response=True)
    for phase in ("signed", "uncertain", "post", "published"):
        assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", phase]) == 0
        if phase != "post":
            network.upload(work, phase)
    assert transport.posts == 1
    assert validator.load_validated_cloud_context(root).status == "PUBLICADO"


def _complete_real_pipeline(tmp_path, monkeypatch, *, lost_report_response=False):
    root, work, network, transport, ticket, public = setup_pipeline(
        tmp_path, monkeypatch, lost_report_response=lost_report_response
    )
    for phase in ("signed", "uncertain", "post", "published"):
        assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", phase]) == 0
        if phase != "post":
            network.upload(work, phase)
    return root, work, network, transport, ticket, public


def test_report_locator_is_idempotent_and_does_not_publish_authority(
    tmp_path, monkeypatch, capsys
):
    root, work, network, transport, _, _ = _complete_real_pipeline(tmp_path, monkeypatch)
    before = validator.load_validated_cloud_context(root)
    writes_before = network.writes
    posts_before = transport.posts

    assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", "report"]) == 0
    first_output = capsys.readouterr().out
    assert '"changed": "false"' in first_output
    assert len(network.report_comments) == 1
    assert network.report_frontier.posts == 1

    assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", "report"]) == 0
    second_output = capsys.readouterr().out
    assert '"changed": "false"' in second_output
    assert len(network.report_comments) == 1
    assert network.report_frontier.posts == 1
    assert network.writes == writes_before
    assert transport.posts == posts_before

    after = validator.load_validated_cloud_context(root)
    assert after.status == before.status == "PUBLICADO"
    assert after.authority.state_sha256 == before.authority.state_sha256
    assert after.latest_edit_id == before.latest_edit_id
    assert "AURORA_CLOUD_INTENT:" in network.report_comments[0]["body"]
    assert "no acredita éxito científico" in network.report_comments[0]["body"]


def test_report_reconciles_lost_comment_response_without_duplicate_or_authority_change(
    tmp_path, monkeypatch
):
    root, work, network, transport, _, _ = _complete_real_pipeline(
        tmp_path, monkeypatch, lost_report_response=True
    )
    before = validator.load_validated_cloud_context(root)
    writes_before = network.writes

    assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", "report"]) == 0
    assert network.report_frontier.posts == 1
    assert len(network.report_comments) == 1

    # A retry sees the locator that was accepted before the synthetic timeout;
    # it must not issue a second POST or alter the authority.
    assert phases.main(["--repo-root", str(root), "--work-dir", str(work), "--phase", "report"]) == 0
    after = validator.load_validated_cloud_context(root)
    assert network.report_frontier.posts == 1
    assert len(network.report_comments) == 1
    assert network.writes == writes_before
    assert transport.posts == 1
    assert after.authority.state_sha256 == before.authority.state_sha256
    assert after.latest_edit_id == before.latest_edit_id
