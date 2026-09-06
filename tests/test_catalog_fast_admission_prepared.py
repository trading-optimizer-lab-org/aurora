"""Real admission/materialization with controlled remote inventory; no science run."""

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_prepared_bundle import write_prepared_catalog_bundle_manifest
from aurora.infra.sp500_megarun.catalog_rebuildable_store import RebuildableStoreCandidateV1
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import CatalogRebuildableStoreIndexV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.catalog_sealed_plan import verify_sealed_global_reuse_execution_plan
from aurora.tests.test_catalog_prepared_materialization import prepared_transport_fixture
from aurora.tests.test_catalog_fast_path import _prepared
from aurora.tests.test_inspect_catalog_fast_request import _entry, _signed_request
from scripts import admit_catalog_fast_request as admission


@pytest.mark.parametrize("inventory_state", ("complete", "incomplete", "unstable", "complete_with_previous", "stale_generation", "wrong_predecessor", "invalid_terminal_author", "missing_terminal_author", "compact_valid", "compact_busy", "compact_wrong_predecessor", "compact_corrupt", "compact_missing_cli"))
def test_new_admission_materializes_only_with_verified_inventory(tmp_path, monkeypatch, capsys, inventory_state):
    """Ignoring inventory completeness/stability must fail the negative cases."""
    bundle, template, plan, identity, prepared = prepared_transport_fixture(tmp_path)
    # This exercises cache-index transport, not component coverage or evaluation.
    key = "aurora-catalog-v1-" + "1" * 64 + "-" + "2" * 64 + "-main"
    candidate = RebuildableStoreCandidateV1(object_family="runtime", logical_id="runtime",
        identity_sha256="1" * 64, content_manifest_sha256="2" * 64, content_sha256="3" * 64,
        storage_kind="actions_cache", status="verified", source_branch="main", cache_key=key,
        file_hashes=(("runtime.bin", "4" * 64),), manifest_verified=True, content_verified=True, scope_verified=True)
    index = CatalogRebuildableStoreIndexV1.create(artifact_name="catalog-rebuildable-store-index-v1",
        repository="trading-optimizer-lab-org/aurora", writer_workflow=".github/workflows/catalog-optimized-run.yml",
        writer_run_id=1, writer_run_attempt=1, protected_commit_sha="a" * 40, source_branch="main",
        authority_id=plan.authority_id, campaign_id=plan.campaign_id, science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256, execution_protocol_sha256="b" * 64, candidates=(candidate,))
    (bundle / "evidence").mkdir()
    (bundle / "evidence/catalog-rebuildable-store-index-v1.json").write_text(index.model_dump_json(), encoding="utf-8")
    prepared = _prepared(identity=identity, execution_plan_template_sha256=prepared.execution_plan_template_sha256,
        component_store_manifest_sha256=index.index_sha256, required_cache_keys=(key,),
        logical_recipe_count=24, unique_component_count=12, qualified_worker_ceiling=7)
    (bundle / "prepared-receipt.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    (bundle / "prepared-bundle-manifest.json").unlink()  # only this test's temporary fixture
    write_prepared_catalog_bundle_manifest(bundle_dir=bundle, prepared_receipt=prepared)
    root = tmp_path / "repo"
    root.mkdir()
    entry = _entry().model_copy(update={"scientific_contract_sha256": plan.science_sha256})
    for relative in entry.repository_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == entry.catalog_dir:
            path.mkdir()
        else:
            path.write_text("{}", encoding="utf-8")
    (root / "config/catalog_campaign_registry_v1.json").write_text(json.dumps({"schema_version": "1",
        "campaigns": [entry.model_dump(mode="json")]}), encoding="utf-8")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    (root / "requester.pem").write_bytes(public)
    (root / "config/catalog_controller_actors_v1.json").write_text(json.dumps({
        "requester_public_key_path": "requester.pem", "request_actors": ["requester"], "ledger_actor": "github-actions[bot]"}), encoding="utf-8")
    title, body = _signed_request(private)
    previous_issue = None
    if inventory_state.startswith("compact_") or inventory_state in {"complete_with_previous", "stale_generation", "wrong_predecessor", "invalid_terminal_author", "missing_terminal_author"}:
        previous_request = parse_catalog_run_request(title, body, public)
        previous_issue = {"number": 279, "title": title, "body": body, "user": {"login": "requester"},
            "state": "closed", "state_reason": "completed", "closed_by": {"login": "github-actions[bot]"},
            "labels": [{"name": "catalog-run-terminal-v1"}], "created_at": "2026-09-05T11:00:00Z",
            "closed_at": "2026-09-05T11:59:00Z", "updated_at": "2026-09-05T11:59:00Z"}
        if inventory_state == "invalid_terminal_author":
            previous_issue["closed_by"] = {"login": "untrusted"}
        elif inventory_state == "missing_terminal_author":
            previous_issue["closed_by"] = None
        title, body = _signed_request(private, request_id="018f47a2-6e91-7c34-8000-000000000002",
            launch_generation=1 if inventory_state == "stale_generation" else 2,
            previous_terminal_request_sha256=None if inventory_state == "stale_generation" else
                "0" * 64 if inventory_state in {"wrong_predecessor", "compact_wrong_predecessor"} else previous_request.request_sha256)
    if inventory_state.startswith("compact_"):
        # Boundary output from the protected reader, not a replacement for its
        # independent provenance tests. No historical search may be used here.
        authority = FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
            request=previous_request, owner_issue_number=279, owner_run_id=123,
            legacy_closure_evidence_sha256=None if inventory_state == "compact_busy" else "b" * 64,
        ),))
        snapshot = authority.model_dump(mode="json")
        if inventory_state == "compact_corrupt":
            snapshot["state_sha256"] = "0" * 64
        if inventory_state != "compact_missing_cli":
            (tmp_path / "catalog-fast-authority-current.json").write_text(json.dumps(snapshot), encoding="utf-8")
    request = parse_catalog_run_request(title, body, public)
    issue = {"number": 280, "title": title, "body": body, "user": {"login": "requester"},
             "state": "open", "labels": [], "created_at": "2026-09-05T12:00:00Z"}
    context = {"schema_version": "1", "document_type": "catalog_fast_request_context_v1",
        "protected_commit_sha": "a" * 40, "request": request.model_dump(mode="json"),
        "identity": identity.model_dump(mode="json"), "issue_number": 280,
        "issue_created_at": issue["created_at"], "actor": "requester", "request_mode": "admit_new"}
    context["content_sha256"] = canonical_sha256(context)
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")

    class Client:
        repository = "trading-optimizer-lab-org/aurora"
        observed_at = datetime(2026, 9, 5, 12, 1, tzinfo=timezone.utc)

        def get_json(self, path):
            assert inventory_state != "compact_missing_cli", "Missing authority must block before live admission"
            if previous_issue is not None and path.endswith("/issues/279"):
                return previous_issue, None
            assert path == "/repos/" + self.repository + "/issues/280"
            return issue, None

        def stable_paginated(self, path, *, root):
            suffix = path.removeprefix("/repos/" + self.repository)
            if inventory_state.startswith("compact_"):
                assert not suffix.startswith("/issues?"), "Fresh admission must not scan request history"
            assert suffix in {"/actions/artifacts?name=catalog-fast-gate-280",
                "/issues?state=open&labels=catalog-run-active-v1", "/issues?state=all&labels=catalog-run-terminal-v1",
                "/actions/caches?ref=refs/heads/main"}
            cache = suffix.startswith("/actions/caches")
            return SimpleNamespace(stable=not(cache and inventory_state == "unstable"),
                collection=SimpleNamespace(complete=not(cache and inventory_state == "incomplete"),
                    rows=[{"key": key, "ref": "refs/heads/main"}] if cache else
                        [previous_issue] if previous_issue is not None and suffix.endswith("labels=catalog-run-terminal-v1") else []))

    monkeypatch.setattr(admission, "CatalogGitHubReadOnlyClient", lambda *args: Client())
    def git_read(command, **kwargs):
        assert command == ["git", "-C", str(root), "rev-parse", "HEAD"]
        return SimpleNamespace(stdout="a" * 40 + "\n", returncode=0)
    monkeypatch.setattr(admission.subprocess, "run", git_read)
    for name, value in {"GITHUB_REPOSITORY": Client.repository, "GH_TOKEN": "fixture-only",
        "RUNNER_TEMP": str(tmp_path), "CATALOG_PROTECTED_COMMIT_SHA": "a" * 40,
        "GITHUB_RUN_ID": "456",
        "CATALOG_SAFE_FREE_CAPACITY": "7", "CATALOG_CONTROLLER_ENABLED": "true",
        "CATALOG_CONTROLLER_PRODUCTION_ARMED": "true"}.items():
        monkeypatch.setenv(name, value)
    target = tmp_path / "admitted"
    if inventory_state == "compact_missing_cli":
        result = admission.main(["--request-context", str(context_path), "--prepared-bundle", str(bundle),
            "--repo-root", str(root), "--output-dir", str(target), "--github-output", str(tmp_path / "github-output")])
        assert result == 2
        assert "CATALOG_FAST_AUTHORITY_SNAPSHOT_REQUIRED" in capsys.readouterr().err
        assert not target.exists()
        return
    if inventory_state == "compact_valid":
        assert admission.main(["--request-context", str(context_path), "--prepared-bundle", str(bundle),
            "--repo-root", str(root), "--output-dir", str(target), "--github-output", str(tmp_path / "github-output")]) == 0
        result = CatalogFastLaunchDecisionV1.model_validate_json((target / "catalog-fast-decision-v1.json").read_text("utf-8"))
    else:
        result = admission.admit_request(request_context_path=context_path, prepared_bundle=bundle,
            repo_root=root, output_dir=target, github_output=tmp_path / "github-output")
    if inventory_state in {"complete", "complete_with_previous", "compact_valid"}:
        assert result.launch_required is True
        assert result.selected_workers == 7
        verify_sealed_global_reuse_execution_plan(target / "sealed-plan", expected_bindings={
            "request_sha256": request.request_sha256, "decision_sha256": result.decision_sha256})
    else:
        assert result.launch_required is False
        assert result.reason_code == ("CATALOG_CAMPAIGN_BUSY" if inventory_state == "compact_busy" else
            "CATALOG_FAST_AUTHORITY_SNAPSHOT_INVALID" if inventory_state == "compact_corrupt" else
            "CATALOG_FAST_GENERATION_CONFLICT" if inventory_state == "stale_generation" else
            "CATALOG_FAST_PREDECESSOR_CONFLICT" if inventory_state in {"wrong_predecessor", "compact_wrong_predecessor"} else
            "CATALOG_FAST_PREDECESSOR_INVALID" if inventory_state in {"invalid_terminal_author", "missing_terminal_author"} else
            "CATALOG_PREPARATION_CACHE_INVENTORY_INCOMPLETE")
        assert not (target / "sealed-plan").exists()
