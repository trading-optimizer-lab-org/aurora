"""The prepared cloud path must not promote an uncontracted artifact fallback."""

from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    write_prepared_catalog_bundle_manifest,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts import admit_catalog_fast_request as admission
from tests.test_catalog_fast_path import _prepared
from tests.test_catalog_prepared_materialization import prepared_transport_fixture
from tests.test_inspect_catalog_fast_request import _entry, _signed_request


REPOSITORY = "trading-optimizer-lab-org/aurora"
PROTECTED_COMMIT = "a" * 40
OBSERVED_AT = datetime(2026, 9, 5, 12, 1, tzinfo=timezone.utc)


def _artifact_candidate() -> RebuildableStoreCandidateV1:
    payload = b"prepared-input-transport"
    return RebuildableStoreCandidateV1(
        object_family="prepared_input",
        logical_id="runtime-fragment-core",
        identity_sha256="1" * 64,
        content_manifest_sha256="2" * 64,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        storage_kind="artifact",
        status="verified",
        source_branch="main",
        artifact_run_id=34991736509,
        artifact_id=10405943875,
        file_hashes=(("payload.bin", hashlib.sha256(payload).hexdigest()),),
        manifest_verified=True,
        content_verified=True,
        scope_verified=True,
    )


def test_store_index_rejects_verified_artifact_candidate_as_fallback() -> None:
    """The real PREPARED index has no artifact-backed candidate contract."""
    candidate = _artifact_candidate()

    with pytest.raises(ValueError, match="CATALOG_STORE_INDEX_CANDIDATES_INVALID"):
        CatalogRebuildableStoreIndexV1.create(
            artifact_name="catalog-rebuildable-store-index-v1",
            repository=REPOSITORY,
            writer_workflow=".github/workflows/catalog-optimized-run.yml",
            writer_run_id=34991736509,
            writer_run_attempt=1,
            protected_commit_sha=PROTECTED_COMMIT,
            source_branch="main",
            authority_id="00000000-0000-0000-0000-000000000001",
            campaign_id="3" * 64,
            science_sha256="4" * 64,
            execution_plan_sha256="5" * 64,
            execution_protocol_sha256="6" * 64,
            candidates=(candidate,),
        )


def test_admission_keeps_cache_missing_block_with_bound_transport_metadata(
    tmp_path, monkeypatch
) -> None:
    """Existing transport bytes/metadata cannot authorize a cache-less run."""
    bundle, template, plan, identity, source_prepared = prepared_transport_fixture(tmp_path)
    cache_key = "aurora-catalog-v1-" + "1" * 64 + "-" + "2" * 64 + "-main"
    cache_candidate = RebuildableStoreCandidateV1(
        object_family="runtime",
        logical_id="runtime",
        identity_sha256="1" * 64,
        content_manifest_sha256="2" * 64,
        content_sha256="3" * 64,
        storage_kind="actions_cache",
        status="verified",
        source_branch="main",
        cache_key=cache_key,
        file_hashes=(("runtime.bin", "4" * 64),),
        manifest_verified=True,
        content_verified=True,
        scope_verified=True,
    )
    index = CatalogRebuildableStoreIndexV1.create(
        artifact_name="catalog-rebuildable-store-index-v1",
        repository=REPOSITORY,
        writer_workflow=".github/workflows/catalog-optimized-run.yml",
        writer_run_id=34991736509,
        writer_run_attempt=1,
        protected_commit_sha=PROTECTED_COMMIT,
        source_branch="main",
        authority_id=plan.authority_id,
        campaign_id=plan.campaign_id,
        science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256,
        execution_protocol_sha256="b" * 64,
        candidates=(cache_candidate,),
    )
    evidence = bundle / "evidence"
    evidence.mkdir()
    (evidence / "catalog-rebuildable-store-index-v1.json").write_text(
        index.model_dump_json(), encoding="utf-8"
    )

    # This is the shape of the authenticated GitHub artifact metadata needed
    # for a future fallback, but no current PREPARED consumer reads it.
    transport_payload = b"prepared-input-transport-payload"
    transport_name = json.loads(
        (template / "execution_plan_receipt.json").read_text("utf-8")
    )["prepared_input_transport_artifacts"][0]
    transport_metadata = {
        "artifact_id": 10405943875,
        "artifact_name": transport_name,
        "digest": "sha256:" + hashlib.sha256(transport_payload).hexdigest(),
        "expired": False,
        "created_at": "2026-09-05T11:00:00Z",
        "expires_at": "2026-09-06T11:00:00Z",
        "size_in_bytes": len(transport_payload),
        "workflow_run": {
            "id": 34991736509,
            "run_attempt": 1,
            "head_branch": "main",
            "head_sha": PROTECTED_COMMIT,
            "repository_id": 123,
            "head_repository_id": 123,
        },
        "cache_key": cache_key,
        "preparation_key_sha256": identity.preparation_key_sha256,
        "retention_days": 1,
    }
    transport_dir = bundle / "transport-evidence"
    transport_dir.mkdir()
    (transport_dir / "prepared-input-artifact.json").write_text(
        json.dumps(transport_metadata, sort_keys=True), encoding="utf-8"
    )
    (transport_dir / "payload.bin").write_bytes(transport_payload)

    prepared = _prepared(
        identity=identity,
        execution_plan_template_sha256=source_prepared.execution_plan_template_sha256,
        component_store_manifest_sha256=index.index_sha256,
        required_cache_keys=(cache_key,),
        logical_recipe_count=24,
        unique_component_count=12,
        qualified_worker_ceiling=7,
    )
    (bundle / "prepared-receipt.json").write_text(
        prepared.model_dump_json(), encoding="utf-8"
    )
    (bundle / "prepared-bundle-manifest.json").unlink()
    write_prepared_catalog_bundle_manifest(
        bundle_dir=bundle, prepared_receipt=prepared
    )

    root = tmp_path / "repo"
    root.mkdir()
    entry = _entry().model_copy(
        update={"scientific_contract_sha256": plan.science_sha256}
    )
    for relative in entry.repository_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == entry.catalog_dir:
            path.mkdir()
        else:
            path.write_text("{}", encoding="utf-8")
    (root / "config/catalog_campaign_registry_v1.json").write_text(
        json.dumps({"schema_version": "1", "campaigns": [entry.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (root / "requester.pem").write_bytes(public)
    (root / "config/catalog_controller_actors_v1.json").write_text(
        json.dumps(
            {
                "requester_public_key_path": "requester.pem",
                "request_actors": ["requester"],
                "ledger_actor": "github-actions[bot]",
            }
        ),
        encoding="utf-8",
    )
    title, body = _signed_request(private)
    issue = {
        "number": 280,
        "title": title,
        "body": body,
        "user": {"login": "requester"},
        "state": "open",
        "labels": [],
        "created_at": "2026-09-05T12:00:00Z",
    }
    request = parse_catalog_run_request(title, body, public)
    context = {
        "schema_version": "1",
        "document_type": "catalog_fast_request_context_v1",
        "protected_commit_sha": PROTECTED_COMMIT,
        "request": request.model_dump(mode="json"),
        "identity": identity.model_dump(mode="json"),
        "issue_number": 280,
        "issue_created_at": issue["created_at"],
        "actor": "requester",
        "request_mode": "admit_new",
    }
    context["content_sha256"] = canonical_sha256(context)
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")

    class Client:
        repository = REPOSITORY
        observed_at = OBSERVED_AT

        def get_json(self, path):
            assert path == f"/repos/{self.repository}/issues/280"
            return issue, None

        def stable_paginated(self, path, *, root):
            suffix = path.removeprefix(f"/repos/{self.repository}")
            if suffix in {
                "/actions/artifacts?name=catalog-fast-gate-280",
                "/issues?state=open&labels=catalog-run-active-v1",
                "/issues?state=all&labels=catalog-run-terminal-v1",
            }:
                rows = []
            elif suffix == "/actions/caches?ref=refs/heads/main":
                rows = []
            else:
                raise AssertionError(f"unexpected live inventory: {suffix}")
            return SimpleNamespace(
                stable=True,
                collection=SimpleNamespace(complete=True, rows=rows),
            )

    monkeypatch.setattr(admission, "CatalogGitHubReadOnlyClient", lambda *args: Client())
    for name, value in {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GH_TOKEN": "fixture-only",
        "RUNNER_TEMP": str(tmp_path),
        "CATALOG_PROTECTED_COMMIT_SHA": PROTECTED_COMMIT,
        "CATALOG_SAFE_FREE_CAPACITY": "7",
        "CATALOG_CONTROLLER_ENABLED": "true",
        "CATALOG_CONTROLLER_PRODUCTION_ARMED": "true",
    }.items():
        monkeypatch.setenv(name, value)

    target = tmp_path / "admitted"
    result = admission.admit_request(
        request_context_path=context_path,
        prepared_bundle=bundle,
        repo_root=root,
        output_dir=target,
        github_output=tmp_path / "github-output",
    )

    assert result.reason_code == "CATALOG_PREPARATION_CACHE_MISSING"
    assert result.launch_required is False
    assert result.prepared_receipt_sha256 == prepared.receipt_sha256
    assert not (target / "sealed-plan").exists()
