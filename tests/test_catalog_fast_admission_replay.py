from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1, CatalogTerminalReceiptV1, CatalogTerminalReceiptV2, CatalogTerminalReceipt
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.tests.test_inspect_catalog_fast_request import _entry, _identity, _signed_request
from aurora.tests.test_catalog_fast_reservation import _metadata
from scripts import admit_catalog_fast_request as admission


@pytest.mark.parametrize("case", (
    "active", "older_approved", "unapproved", "missing_archive", "terminal_missing", "tampered_signature",
    "terminal_success", "terminal_blocked", "terminal_foreign", "terminal_wrong_attempt", "terminal_other_request",
    "terminal_unpublished", "terminal_bad_digest", "terminal_extra_member",
    "fresh_without_preparation",
    "inspected_replay_without_preparation",
    "inspected_replay_missing_owner",
    "duplicate_active", "duplicate_ambiguous", "duplicate_resigned", "duplicate_terminal_resigned",
    "duplicate_alias", "duplicate_alias_unpublished", "duplicate_alias_wrong_owner", "duplicate_alias_blocked",
    "duplicate_inspected_resigned", "inspected_preparation_missing_new",
    "compact_duplicate_active", "compact_duplicate_resigned", "compact_duplicate_terminal_resigned",
    "compact_duplicate_alias", "compact_duplicate_alias_wrong_owner", "compact_duplicate_inspected_resigned",
    "compact_owner_mismatch", "compact_terminal_mismatch", "compact_owner_missing",
    "failed_gate_terminal_blocked",
    "v2_terminal_success", "v2_terminal_blocked", "v2_terminal_foreign",
    "v2_terminal_bad_digest", "v2_terminal_other_request", "v2_compact_duplicate_terminal_resigned",
))
def test_admission_replay_preserves_original_and_never_materializes(tmp_path, monkeypatch, case):
    """Removing the production owner lookup must lose the original ID and fail.

    Only GitHub/gh transport is replaced. Signature, archive, metadata, lookup,
    admission and emitted workflow outputs execute their real implementations.
    No registry or prepared bundle exists: replay must not need a new campaign.
    """
    version2 = case.startswith("v2_")
    case = case.removeprefix("v2_")
    compact = case.startswith("compact_")
    failed_gate = case == "failed_gate_terminal_blocked"
    if failed_gate:
        case = "terminal_blocked"
    case = case.removeprefix("compact_")
    compact_failure = case if case in {"owner_mismatch", "terminal_mismatch", "owner_missing"} else None
    if compact_failure:
        case = "duplicate_terminal_resigned" if compact_failure == "terminal_mismatch" else "duplicate_active"
    root, temp = tmp_path / "repo", tmp_path / "runner"
    (root / "config").mkdir(parents=True)
    (root / "keys").mkdir()
    temp.mkdir()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    (root / "keys/requester.pem").write_bytes(public)
    (root / "config/catalog_controller_actors_v1.json").write_text(json.dumps({
        "requester_public_key_path": "keys/requester.pem", "request_actors": ["requester"],
    }), encoding="utf-8")
    if case == "fresh_without_preparation":
        entry = _entry()
        for relative in entry.repository_paths:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == entry.catalog_dir:
                path.mkdir()
            else:
                path.write_text("{}", encoding="utf-8")
        (root / "config/catalog_campaign_registry_v1.json").write_text(json.dumps({
            "schema_version": "1", "campaigns": [entry.model_dump(mode="json")],
        }), encoding="utf-8")
    title, body = _signed_request(private)
    request = parse_catalog_run_request(title, body, public)
    original_title, original_body = _signed_request(private) if "resigned" in case else (title, body)
    original_request = parse_catalog_run_request(original_title, original_body, public)
    if "resigned" in case:
        assert original_request.intent_sha256 == request.intent_sha256
        assert original_request.request_sha256 != request.request_sha256
    commit = "a" * 40
    context = {
        "schema_version": "1", "document_type": "catalog_fast_request_context_v1",
        "protected_commit_sha": commit, "request": request.model_dump(mode="json"),
        "identity": _identity().model_dump(mode="json"), "issue_number": 280 if case.startswith("duplicate_") else 276,
        "issue_created_at": "2026-09-04T19:20:00Z", "actor": "requester",
        "issue_labels": ["catalog-run-active-v1"],
    }
    context["content_sha256"] = canonical_sha256(context)
    context_path, output = temp / "context.json", temp / "github-output.txt"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=original_request.request_sha256, submission_key_sha256=original_request.submission_key_sha256,
        campaign_key=request.campaign_key, prepared_receipt_sha256="b" * 64,
        selected_workers=1, launch_required=True, existing_run_id=None,
        decided_at=datetime(2026, 9, 4, 19, 20, tzinfo=timezone.utc),
        expires_at=datetime(2026, 9, 4, 19, 50, tzinfo=timezone.utc),
    )
    buffer = io.BytesIO()
    archived_context = dict(context)
    archived_context["issue_number"] = 276
    archived_context["request"] = original_request.model_dump(mode="json")
    archived_context["content_sha256"] = canonical_sha256({key: value for key, value in archived_context.items() if key != "content_sha256"})
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("catalog-fast-request-context.json", json.dumps(archived_context))
        archive.writestr("catalog-fast-decision-v1.json", decision.model_dump_json())
    raw = buffer.getvalue()
    artifact, run, jobs = _metadata()
    source_commit = "c" * 40 if case in {"older_approved", "unapproved"} else commit
    artifact["workflow_run"]["head_sha"] = source_commit
    artifact["digest"] = "sha256:" + sha256(raw).hexdigest()
    artifact["size_in_bytes"] = len(raw)
    run.update(head_sha=source_commit, status="in_progress", conclusion=None)
    jobs[0]["head_sha"] = source_commit
    if failed_gate:
        jobs[0]["conclusion"] = "failure"
        jobs[0]["steps"][1].update(number=19, conclusion="failure")
        jobs[0]["steps"] += [
            {"name": name, "number": number, "status": "completed", "conclusion": "success",
             "started_at": f"2026-09-04T19:21:{start:02}Z", "completed_at": f"2026-09-04T19:21:{start + 1:02}Z"}
            for name, number, start in [("Write current authority edition", 16, 5),
                ("Publish current authority edition", 17, 7),
                ("Verify the uploaded reservation before exposing QUEUED", 18, 9)]
        ]
    if case.startswith("terminal_") or case == "duplicate_terminal_resigned":
        run.update(status="completed", conclusion="failure")
    terminal_receipt: CatalogTerminalReceipt = CatalogTerminalReceiptV1.create(
        state="BLOCKED" if case == "terminal_blocked" else "SUCCESS",
        reason_code="CATALOG_GATE_PUBLICATION_FAILED" if failed_gate else "CATALOG_ENGINE_FAILED" if case == "terminal_blocked" else "CATALOG_RUN_SUCCESS",
        request_sha256="d" * 64 if case == "terminal_other_request" else original_request.request_sha256,
        submission_key_sha256=original_request.submission_key_sha256, campaign_key=request.campaign_key,
        prepared_receipt_sha256="b" * 64, engine_run_id=run["id"],
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run['id']}",
        expected_recipe_count=8, observed_recipe_count=0 if case == "terminal_blocked" else 8,
        queue_seconds=0.0, preparation_seconds=0.0, computation_seconds=1.0,
        recovery_seconds=0.0, reduction_seconds=0.0, recovered_block_count=0,
        failure_class="infrastructure" if case == "terminal_blocked" else None,
        result_science_sha256=None if case == "terminal_blocked" else "e" * 64,
        created_at=datetime(2026, 9, 4, 19, 25, 1, tzinfo=timezone.utc),
    )
    if version2:
        values = terminal_receipt.model_dump(exclude={"schema_version", "receipt_sha256", "queue_seconds", "preparation_seconds",
            "computation_seconds", "recovery_seconds", "reduction_seconds", "recovered_block_count"})
        terminal_receipt = CatalogTerminalReceiptV2.create(**values, timing={}, recovered_block_ids=None)
    terminal_buffer = io.BytesIO()
    with zipfile.ZipFile(terminal_buffer, "w") as archive:
        archive.writestr("catalog-terminal-receipt-v1.json", terminal_receipt.model_dump_json())
        if case == "terminal_extra_member":
            archive.writestr("unexpected.txt", "must reject")
    terminal_raw = terminal_buffer.getvalue()
    terminal_artifact = {
        **artifact, "id": 9951225149, "name": f"catalog-terminal-receipt-{original_request.request_sha256}",
        "digest": "sha256:" + ("0" * 64 if case == "terminal_bad_digest" else sha256(terminal_raw).hexdigest()),
        "size_in_bytes": len(terminal_raw), "created_at": "2026-09-04T19:25:03Z",
        "workflow_run": dict(artifact["workflow_run"]),
    }
    if case == "terminal_foreign":
        terminal_artifact["workflow_run"]["id"] = 99
    terminal_job = {
        "id": 101146103607, "run_id": run["id"], "run_attempt": 2 if case == "terminal_wrong_attempt" else 1,
        "head_sha": source_commit, "name": "finalize", "status": "completed", "conclusion": "failure",
        "steps": [
            {"name": "Create exactly one terminal receipt", "status": "completed", "conclusion": "success", "number": 10,
             "started_at": "2026-09-04T19:25:00Z", "completed_at": "2026-09-04T19:25:02Z"},
            {"name": "Publish the terminal receipt before changing the issue", "status": "completed",
             "conclusion": "failure" if case == "terminal_unpublished" else "success", "number": 11,
             "started_at": "2026-09-04T19:25:03Z", "completed_at": "2026-09-04T19:25:04Z"},
        ],
    }
    # A failure updating the issue AFTER publication must not discard a valid receipt.
    if case.startswith("terminal_") or case == "duplicate_terminal_resigned":
        jobs.append(terminal_job)
    issue = {"number": context["issue_number"], "title": title, "body": body, "state": "open",
             "created_at": context["issue_created_at"], "user": {"login": "requester"},
             "labels": [{"name": "catalog-run-active-v1"}]}
    if case == "tampered_signature":
        issue["body"] = body.replace('"prompt_sha256":"' + "4" * 64, '"prompt_sha256":"' + "5" * 64)
    if case in {"fresh_without_preparation", "inspected_preparation_missing_new"} or case.startswith("duplicate_"):
        issue["labels"] = []
    alias_raw = b""
    if case.startswith("duplicate_alias"):
        alias_decision = CatalogFastLaunchDecisionV1.create(
            state="BLOCKED" if case == "duplicate_alias_blocked" else "QUEUED",
            reason_code="CATALOG_FAST_EXISTING_RUN", request_sha256=request.request_sha256,
            submission_key_sha256=request.submission_key_sha256, campaign_key=request.campaign_key,
            prepared_receipt_sha256="b" * 64, selected_workers=0, launch_required=False,
            existing_run_id=None if case == "duplicate_alias_blocked" else 99 if case == "duplicate_alias_wrong_owner" else run["id"],
            decided_at=now, expires_at=now,
        )
        alias_buffer = io.BytesIO()
        with zipfile.ZipFile(alias_buffer, "w") as archive:
            archive.writestr("catalog-fast-request-context.json", json.dumps(context))
            archive.writestr("catalog-fast-decision-v1.json", alias_decision.model_dump_json())
        alias_raw = alias_buffer.getvalue()
        alias_artifact, alias_run, alias_jobs = deepcopy((artifact, run, jobs))
        alias_artifact.update(id=9951225150, name="catalog-fast-gate-280",
            digest="sha256:" + sha256(alias_raw).hexdigest(), size_in_bytes=len(alias_raw))
        alias_artifact["workflow_run"]["id"] = 33910681071
        alias_run.update(id=33910681071, status="completed", conclusion="success")
        alias_jobs[0]["run_id"] = 33910681071
        alias_jobs[0]["steps"][0]["conclusion"] = "failure" if case == "duplicate_alias_unpublished" else "success"
        alias_jobs[0]["steps"][1]["conclusion"] = "skipped"
    if compact:
        authority = FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
            request=original_request, owner_issue_number=276,
            owner_run_id=99 if compact_failure == "owner_mismatch" else 33910681070,
            terminal_receipt_sha256="0" * 64 if compact_failure == "terminal_mismatch" else
                terminal_receipt.receipt_sha256 if case == "duplicate_terminal_resigned" else None,
        ),))
        (temp / "catalog-fast-authority-current.json").write_text(authority.model_dump_json(), encoding="utf-8")
    reads = []

    class Client:
        repository = "trading-optimizer-lab-org/aurora"
        observed_at = now

        def get_json(self, path):
            reads.append(path)
            if path.endswith(f"/issues/{context['issue_number']}"):
                return issue, None
            if path.endswith("/actions/runs/33910681070"):
                return run, None
            if case.startswith("duplicate_alias") and path.endswith("/actions/runs/33910681071"):
                return alias_run, None
            if "/compare/" in path:
                return {"base_commit": {"sha": source_commit}, "merge_base_commit": {"sha": source_commit},
                        "status": "ahead" if case == "older_approved" else "diverged"}, None
            raise AssertionError("Unexpected lookup: " + path)

        def stable_paginated(self, path, *, root):
            reads.append(path)
            if compact:
                assert "/issues?" not in path, "Compact replay must resolve its pinned owner without scanning history"
            if path.endswith("/actions/artifacts?name=catalog-fast-gate-276"):
                rows = [] if compact_failure == "owner_missing" or case in {"missing_archive", "fresh_without_preparation", "inspected_replay_missing_owner", "inspected_preparation_missing_new"} else [artifact]
            elif path.endswith("/actions/artifacts?name=catalog-fast-gate-280"):
                rows = [alias_artifact] if case.startswith("duplicate_alias") else []
            elif case.startswith("duplicate_alias") and path.endswith("/actions/runs/33910681071/attempts/1/jobs"):
                rows = alias_jobs
            elif case.startswith("duplicate_") and path.endswith("/issues?state=open&labels=catalog-run-active-v1"):
                original = {**issue, "number": 276, "title": original_title, "body": original_body,
                            "labels": [{"name": "catalog-run-active-v1"}]}
                rows = [] if case == "duplicate_terminal_resigned" else [original, {**original, "number": 277}] if case == "duplicate_ambiguous" else [original]
            elif case == "duplicate_terminal_resigned" and path.endswith("/issues?state=all&labels=catalog-run-terminal-v1"):
                rows = [{**issue, "number": 276, "title": original_title, "body": original_body,
                         "state": "closed", "labels": [{"name": "catalog-run-terminal-v1"}]}]
            elif path.endswith("/actions/runs/33910681070/attempts/1/jobs"):
                rows = jobs
            elif path.endswith(f"/actions/runs/33910681070/artifacts?name=catalog-terminal-receipt-{original_request.request_sha256}"):
                rows = [] if case == "terminal_missing" else [terminal_artifact]
            elif case in {"fresh_without_preparation", "inspected_replay_missing_owner", "inspected_preparation_missing_new"} and path in {
                "/repos/trading-optimizer-lab-org/aurora/issues?state=open&labels=catalog-run-active-v1",
                "/repos/trading-optimizer-lab-org/aurora/issues?state=all&labels=catalog-run-terminal-v1",
            }:
                rows = []
            else:
                raise AssertionError("Replay must not scan campaign history: " + path)
            return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=True, rows=rows))

    def gh_run(command, **kwargs):
        if command == ["git", "-C", str(root), "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=commit + "\n")
        assert command[:2] == ["gh", "api"]
        payloads = {
            "repos/trading-optimizer-lab-org/aurora/actions/artifacts/9951225148/zip": raw,
            "repos/trading-optimizer-lab-org/aurora/actions/artifacts/9951225149/zip": terminal_raw,
            "repos/trading-optimizer-lab-org/aurora/actions/artifacts/9951225150/zip": alias_raw,
        }
        kwargs["stdout"].write(payloads[command[2]])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(admission, "CatalogGitHubReadOnlyClient", lambda *args: Client())
    # Existing module has no gh downloader yet; patch the stdlib transport only.
    import subprocess
    monkeypatch.setattr(subprocess, "run", gh_run)
    for name, value in {"GITHUB_REPOSITORY": Client.repository, "GH_TOKEN": "fixture-only",
                        "RUNNER_TEMP": str(temp), "CATALOG_PROTECTED_COMMIT_SHA": commit,
                        "CATALOG_SAFE_FREE_CAPACITY": "1",
                        "CATALOG_CONTROLLER_ENABLED": "false", "CATALOG_CONTROLLER_PRODUCTION_ARMED": "false"}.items():
        monkeypatch.setenv(name, value)
    if case.startswith("inspected_replay_") or case in {"duplicate_inspected_resigned", "inspected_preparation_missing_new"}:
        from scripts import inspect_catalog_fast_request as inspector
        issue_path = temp / "issue.json"
        issue_path.write_text(json.dumps(issue), encoding="utf-8")
        context_path = temp / "inspected-context.json"
        inspector_outputs = temp / "inspect-outputs.txt"
        inspected = inspector.inspect_request(issue_path=issue_path, repo_root=root,
            output_path=context_path, github_output=inspector_outputs)
        assert inspected["identity"] is None
        assert inspected["request_mode"] == "lookup_existing"
        assert "prepared_cache_restore_prefix=\n" in inspector_outputs.read_text("utf-8")
        if case == "inspected_replay_missing_owner":
            # Labels may change after inspection. Lookup-only must never fall
            # through to fresh admission when evidence is missing.
            issue["labels"] = []
    if case == "tampered_signature":
        with pytest.raises(ValueError):
            admission.admit_request(request_context_path=context_path, prepared_bundle=temp / "absent",
                repo_root=root, output_dir=temp / "gate", github_output=output)
        assert not (temp / "gate").exists()
        return
    result = admission.admit_request(request_context_path=context_path, prepared_bundle=temp / "absent",
        repo_root=root, output_dir=temp / "gate", github_output=output)
    assert result.launch_required is False
    assert not (temp / "gate/sealed-plan").exists()
    emitted = dict(line.split("=", 1) for line in output.read_text("utf-8").splitlines())
    assert emitted["preserve_issue"] == ("false" if case == "fresh_without_preparation" else "true")
    assert emitted["launch_required"] == "false"
    if compact_failure:
        assert result.state == "BLOCKED"
        assert result.reason_code == {
            "owner_mismatch": "CATALOG_FAST_AUTHORITY_OWNER_MISMATCH",
            "terminal_mismatch": "CATALOG_FAST_AUTHORITY_TERMINAL_CONFLICT",
            "owner_missing": "CATALOG_FAST_OWNER_ORIGINAL_EVIDENCE_MISSING",
        }[compact_failure]
        assert result.existing_run_id == (33910681070 if compact_failure == "terminal_mismatch" else None)
        assert not emitted.get("terminal_receipt_sha256")
        return
    if case in {"active", "older_approved", "inspected_replay_without_preparation", "duplicate_active", "duplicate_resigned", "duplicate_terminal_resigned", "duplicate_alias", "duplicate_inspected_resigned"} or case.startswith("terminal_"):
        assert result.existing_run_id == 33910681070
        assert emitted["existing_run_id"] == "33910681070"
    if case == "fresh_without_preparation":
        assert result.state == "BLOCKED"
        assert result.reason_code == "CATALOG_PREPARATION_REQUIRED"
        assert result.existing_run_id is None
    elif case in {"terminal_success", "duplicate_terminal_resigned"}:
        assert result.state == "SUCCESS"
        assert result.reason_code == "CATALOG_RUN_SUCCESS"
        assert emitted["terminal_receipt_sha256"] == terminal_receipt.receipt_sha256
        assert emitted["existing_run_url"] == "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/33910681070"
    elif case == "terminal_blocked":
        assert result.state == "BLOCKED"
        assert result.reason_code == ("CATALOG_GATE_PUBLICATION_FAILED" if failed_gate else "CATALOG_ENGINE_FAILED")
        assert emitted["terminal_receipt_sha256"] == terminal_receipt.receipt_sha256
    elif case == "terminal_missing":
        assert result.state == "BLOCKED"
        assert result.reason_code == "CATALOG_FAST_OWNER_TERMINAL_EVIDENCE_REQUIRED"
    elif case.startswith("terminal_"):
        assert result.state == "BLOCKED"
        assert result.reason_code != "CATALOG_FAST_OWNER_TERMINAL_EVIDENCE_REQUIRED"
        assert emitted.get("terminal_receipt_sha256", "") == ""
    elif case in {"missing_archive", "unapproved", "inspected_replay_missing_owner", "duplicate_ambiguous",
                  "duplicate_alias_unpublished", "duplicate_alias_wrong_owner", "duplicate_alias_blocked", "inspected_preparation_missing_new"}:
        assert result.state == "BLOCKED"
        assert result.existing_run_id is None
        if case == "inspected_preparation_missing_new":
            assert result.reason_code == "CATALOG_REGISTRY_INVALID"
    else:
        assert result.state == "QUEUED"
    assert len(reads) <= (8 if case == "duplicate_terminal_resigned" or case.startswith("duplicate_alias") else 6 if case.startswith("duplicate_") else 5 if case == "older_approved" or case.startswith("terminal_") else 4)
    if case == "duplicate_alias":
        # A further observation of the same published alias must still resolve
        # the original owner, without creating a sealed plan or a new receipt.
        repeated = admission.admit_request(request_context_path=context_path, prepared_bundle=temp / "absent",
            repo_root=root, output_dir=temp / "gate-repeat", github_output=temp / "repeat-output.txt")
        assert repeated.existing_run_id == 33910681070
        assert repeated.launch_required is False
        assert not (temp / "gate-repeat/sealed-plan").exists()
