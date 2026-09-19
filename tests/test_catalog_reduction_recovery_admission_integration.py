"""Integration coverage for gen8/9/11 admission with closed recovery sources.

The profile selector, authority model, predecessor guard, fast admission and
prepared-plan materializer are real. GitHub issue/cache responses, the owner
evidence reader, the terminal reader and the observed GitHub clock are explicit
boundaries: their independent provenance/reader contracts are covered by the
existing tests. This test therefore does not claim to exercise live GitHub
archive authentication or scientific execution.
The 24-recipe transport fixture exercises materialization only, not compatibility
with the eight scientific results pinned by any recovery profile.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import CatalogCampaignEntryV1
from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityCampaignV1,
    FastAuthorityStateV1,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogTerminalReceiptV2,
    CatalogTerminalTimingV2,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    write_prepared_catalog_bundle_manifest,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentV1,
    CatalogRunRequestV1,
    _attestation_payload,
)
from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
    load_reduction_recovery_profiles,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)
from aurora.tests.test_catalog_fast_path import _prepared
from aurora.tests.test_catalog_prepared_materialization import prepared_transport_fixture
from scripts import admit_catalog_fast_request as admission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GEN7_FIXTURE = ROOT / "tests/fixtures/catalog_recovery_gen7_request.json"
PUBLIC_GEN10_FIXTURE = ROOT / "tests/fixtures/catalog_recovery_gen10_request.json"
SOURCE_ISSUE = 323
SOURCE_RUN = 35436320227
SOURCE_RUN_ATTEMPT = 1
SOURCE10_ISSUE = 333
SOURCE10_RUN = 35460847765
SOURCE10_RUN_ATTEMPT = 1
SOURCE10_REQUEST_SHA256 = "655d64878185f1066590c4acafcd76e6b48c6626e03e5c331371caa735a5193b"
SOURCE10_TERMINAL_RECEIPT_SHA256 = "3a414441d7498154f1c3128f9fc4dc286075286e86fb2a3d001574b0236e9bf5"
CURRENT_ISSUE = 324
CURRENT_RUN = 35436320228
CURRENT_COMMIT = "a" * 40
PREPARED_RECEIPT_SHA256 = "4dee5b0498c5eefc8c32b1dd08e89a6944573a052ab7e737b7174b85075747c3"
GEN10_PREPARED = "a739832505767bb239ed9d2423c6165ad56f30d82eda8bf2378597aa9af7a7ab"
CURRENT_CREATED_AT = "2026-09-19T17:00:00Z"
OBSERVED_AT = datetime(2026, 9, 19, 17, 1, tzinfo=timezone.utc)
GEN8_PREPARED = "938dd3aff5eafefbcd99d3140e22405e6b21d77f6996a4f769476da59fcb285b"
GEN8_DECISION = "91e1e0bb41a76b5014d8d705cb67ccb5b163c24c2551bd1d84cc91ab37ccf023"
GEN10_DECISION = "4bedf1b0e05eb1d15b14aad37d08d2d42fa76f1299ccbddd501900c8869dbdc5"
GEN10_SOURCE_PLAN_BINDINGS = {
    "request_sha256": SOURCE10_REQUEST_SHA256,
    "decision_sha256": GEN10_DECISION,
    "protected_commit_sha": "26a6832e3d0b9f0c319b99afc328ea9fb4831acf",
    "authority_id": "abe7c473-f1dd-56ce-a1f0-6477b3f6c211",
    "campaign_id": "235cb870254559227dbac2e56f7d492af786851d044aa61c4c30e6cb083fd8db",
    "science_sha256": "57a24398bba9779f2095d20dc50f15975cd04949964055ae322411a3d57906a2",
    "execution_plan_sha256": "c0e73224fd7eb5af9abf51587f44fbaee791dabb1862164ac2829ed6eee2032c",
    "execution_protocol_sha256": "a856bc16bb3c5b39746a47eefa8f3c079641d0b13b2a686b43ce4c359ef119cc",
}
GEN10_SOURCE_PLAN_RECEIPT_SHA256 = "27027da90e69ac0aeefc83c8d0818095c062f576e69a9f3521cf3c4f2418dea2"
GEN10_CATALOG_MANIFEST_SHA256 = "2de5b6a09fb10b71adff0f45af450f30c7f3dbfb196bfea8f01f92d4cf3cb981"


def _public_request_body(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload["request"], sort_keys=True, separators=(",", ":"))
    return f"```json\n{encoded}\n```\n"


def _load_source_request(
    fixture: Path,
    *,
    generation: int,
    issue: int,
    run_id: int,
    run_attempt: int,
    terminal_receipt_sha256: str,
) -> tuple[dict[str, Any], CatalogRunRequestV1, str, str]:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    title = payload["title"]
    body = _public_request_body(payload)
    public_key = (ROOT / "config/catalog_requester_public_key_v1.pem").read_bytes()
    request = parse_catalog_run_request(title, body, public_key)
    assert request.request_sha256 == payload["request_sha256"]
    assert request.launch_generation == generation
    assert payload["issue_number"] == issue
    assert payload["owner_run_id"] == run_id
    assert payload["owner_run_attempt"] == run_attempt
    assert payload["terminal_receipt_sha256"] == terminal_receipt_sha256
    return payload, request, title, body


def _source_request() -> tuple[dict[str, Any], CatalogRunRequestV1, str, str]:
    return _load_source_request(
        PUBLIC_GEN7_FIXTURE,
        generation=7,
        issue=SOURCE_ISSUE,
        run_id=SOURCE_RUN,
        run_attempt=SOURCE_RUN_ATTEMPT,
        terminal_receipt_sha256="67224b935b44f2d7598e2b28d9cb686d4eee89a046d0ec3b0482db4aba9d8cc4",
    )


def _source10_request() -> tuple[dict[str, Any], CatalogRunRequestV1, str, str]:
    return _load_source_request(
        PUBLIC_GEN10_FIXTURE,
        generation=10,
        issue=SOURCE10_ISSUE,
        run_id=SOURCE10_RUN,
        run_attempt=SOURCE10_RUN_ATTEMPT,
        terminal_receipt_sha256=SOURCE10_TERMINAL_RECEIPT_SHA256,
    )


def _next_generation_request(
    source: CatalogRunRequestV1, private_key: rsa.RSAPrivateKey
) -> tuple[CatalogRunRequestV1, str, str, bytes]:
    request_id = "01a0b91d-df5d-7635-9421-4def26452d5e"
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=request_id,
        campaign_key=source.campaign_key,
        launch_generation=source.launch_generation + 1,
        campaign_definition_sha256=source.campaign_definition_sha256,
        prompt_sha256=source.prompt_sha256,
        previous_terminal_request_sha256=source.request_sha256,
    )
    intent = CatalogRunIntentV1(
        schema_version="1",
        request_id=request_id,
        campaign_key=source.campaign_key,
        launch_generation=source.launch_generation + 1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=source.request_sha256,
        campaign_definition_sha256=source.campaign_definition_sha256,
        prompt_sha256=source.prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    title = f"[AURORA CATALOG RUN REQUEST] {request_id}"
    signature = private_key.sign(
        _attestation_payload(title, intent),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    request = CatalogRunRequestV1(
        **intent.model_dump(mode="json"),
        requester_public_key_sha256=sha256(public_der).hexdigest(),
        requester_attestation_algorithm="rsa-pss-sha256-v1",
        requester_attestation_b64=b64encode(signature).decode("ascii"),
    )
    body = f'```json\n{json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))}\n```\n'
    return request, title, body, private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _campaign_entry(science_sha256: str) -> CatalogCampaignEntryV1:
    return CatalogCampaignEntryV1(
        campaign_key="catalog-fast-canary-v1",
        engine_id="optimized_catalog_v1",
        definition_manifest_path="config/definition.json",
        optimization_policy_path="config/optimization.json",
        campaign_contract_path="config/campaign.json",
        catalog_dir="catalog",
        selected_config_path="config/selected.json",
        admission_evidence_path="config/admission.json",
        data_contract_path="config/data.json",
        feature_contract_path="config/features.json",
        runtime_input_run_id=1,
        reference_run_id=2,
        scientific_contract_sha256=science_sha256,
        max_free_workers=360,
        allowed_protected_branch="main",
        source_artifact_contracts=("runtime_input_pack_v1", "reference_oracle_v1"),
        component_store_family="sp500_component_store_v1",
        reducer_family="catalog_hierarchical_reducer_v1",
        active=True,
    )


def _prepare_transport_bundle(runner_temp: Path):
    bundle, template, plan, original_identity, _ = prepared_transport_fixture(
        runner_temp / "transport"
    )
    identity = original_identity.model_copy(
        update={"campaign_key": "catalog-fast-canary-v1"}
    )
    cache_key = "aurora-catalog-v1-" + "1" * 64 + "-" + "2" * 64 + "-main"
    candidate = RebuildableStoreCandidateV1(
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
    store_index = CatalogRebuildableStoreIndexV1.create(
        artifact_name="catalog-rebuildable-store-index-v1",
        repository="trading-optimizer-lab-org/aurora",
        writer_workflow=".github/workflows/catalog-optimized-run.yml",
        writer_run_id=1,
        writer_run_attempt=1,
        protected_commit_sha=CURRENT_COMMIT,
        source_branch="main",
        authority_id=plan.authority_id,
        campaign_id=plan.campaign_id,
        science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256,
        execution_protocol_sha256="b" * 64,
        candidates=(candidate,),
    )
    evidence_dir = bundle / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "catalog-rebuildable-store-index-v1.json").write_text(
        store_index.model_dump_json(), encoding="utf-8"
    )
    original_prepared = json.loads(
        (bundle / "prepared-receipt.json").read_text(encoding="utf-8")
    )
    prepared = _prepared(
        identity=identity,
        execution_plan_template_sha256=original_prepared["execution_plan_template_sha256"],
        component_store_manifest_sha256=store_index.index_sha256,
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
    return bundle, template, plan, identity, prepared, cache_key


def _write_test_repo(
    repo_root: Path,
    *,
    science_sha256: str,
    public_key: bytes,
    include_profile: bool,
) -> None:
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True)
    entry = _campaign_entry(science_sha256)
    for relative in (entry.definition_manifest_path, *entry.repository_paths):
        path = repo_root / relative
        if relative == entry.catalog_dir:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
    (config_dir / "catalog_campaign_registry_v1.json").write_text(
        json.dumps({"schema_version": "1", "campaigns": [entry.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    (repo_root / "requester.pem").write_bytes(public_key)
    actors = {
        "production_enabled": True,
        "request_actors": ["requester"],
        "required_request_actor_kind": "non_admin_github_app",
        "requester_public_key_path": "requester.pem",
        "requester_public_key_sha256": sha256(
            serialization.load_pem_public_key(public_key)
            .public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest(),
        "ledger_actor": "github-actions[bot]",
    }
    (config_dir / "catalog_controller_actors_v1.json").write_text(
        json.dumps(actors), encoding="utf-8"
    )
    if include_profile:
        shutil.copyfile(
            ROOT / "config/catalog_reduction_recovery_profiles_v1.json",
            config_dir / "catalog_reduction_recovery_profiles_v1.json",
        )


def _terminal_receipt(source: CatalogRunRequestV1) -> CatalogTerminalReceiptV2:
    gen8 = source.launch_generation == 8
    gen10 = source.launch_generation == 10
    run_id = 35454099484 if gen8 else SOURCE10_RUN if gen10 else SOURCE_RUN
    return CatalogTerminalReceiptV2.create(
        state="BLOCKED",
        reason_code="CATALOG_ENGINE_STAGE_FAILED" if gen10 else "CATALOG_REDUCTION_FAILED",
        request_sha256=source.request_sha256,
        submission_key_sha256=source.submission_key_sha256,
        campaign_key=source.campaign_key,
        prepared_receipt_sha256=(
            GEN8_PREPARED if gen8 else GEN10_PREPARED if gen10 else PREPARED_RECEIPT_SHA256
        ),
        engine_run_id=run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run_id}",
        expected_recipe_count=8,
        observed_recipe_count=0,
        timing=CatalogTerminalTimingV2(
            initial_queue_seconds=22.0 if gen10 else 21.0 if gen8 else 14.0,
            preparation_jobs_window_seconds=138.0 if gen10 else 85.0 if gen8 else 183.0,
            evaluation_jobs_window_seconds=None if gen8 or gen10 else 53.0,
            recovery_jobs_window_seconds=179.0 if gen10 else None,
            reduction_jobs_window_seconds=105.0 if gen10 else 49.0 if gen8 else 69.0,
            worker_evaluation_seconds=None,
        ),
        recovered_block_ids=None,
        failure_class="infrastructure",
        result_science_sha256=None,
        created_at=(
            datetime(2026, 9, 19, 18, 30, 32, 493920, tzinfo=timezone.utc)
            if gen10
            else datetime(2026, 9, 19, 16, 14, 39, 41347, tzinfo=timezone.utc)
            if gen8
            else datetime(2026, 9, 19, 10, 11, 9, 728262, tzinfo=timezone.utc)
        ),
    )


def _run_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    terminal_mode: str = "valid",
    include_profile: bool = True,
    target_generation: int = 8,
    owner_mode: str = "valid",
    altered_link: bool = False,
) -> dict[str, Any]:
    if target_generation == 11:
        source_metadata, source, _source_title, _source_body = _source10_request()
    else:
        source_metadata, source, _source_title, _source_body = _source_request()
    predecessor = source
    predecessor_metadata = source_metadata
    if target_generation == 9:
        predecessor_metadata = json.loads(
            (ROOT / "tests/fixtures/catalog_recovery_gen8_request.json").read_text("utf-8")
        )
        predecessor = parse_catalog_run_request(
            predecessor_metadata["title"], _public_request_body(predecessor_metadata),
            (ROOT / "config/catalog_requester_public_key_v1.pem").read_bytes(),
        )
        assert predecessor.request_sha256 == predecessor_metadata["request_sha256"]
        assert predecessor.previous_terminal_request_sha256 == source.request_sha256
    elif target_generation == 11:
        assert predecessor.launch_generation == 10
        assert predecessor.request_sha256 == SOURCE10_REQUEST_SHA256
    predecessor_issue = predecessor_metadata["issue_number"]
    predecessor_run = predecessor_metadata["owner_run_id"]
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    request, title, body, public_key = _next_generation_request(predecessor, private_key)
    original_terminal = _terminal_receipt(predecessor)
    assert original_terminal.receipt_sha256 == predecessor_metadata["terminal_receipt_sha256"]
    # Corrupt only the authority boundary after authenticating the public request.
    # Its changed request hash must also be rejected; no signature bypass is mocked.
    if altered_link:
        predecessor = predecessor.model_copy(
            update={"previous_terminal_request_sha256": "0" * 64}
        )
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    bundle, template, plan, identity, prepared, cache_key = _prepare_transport_bundle(
        runner_temp
    )
    repo_root = tmp_path / "repo"
    _write_test_repo(
        repo_root,
        science_sha256=plan.science_sha256,
        public_key=public_key,
        include_profile=include_profile,
    )
    authority = FastAuthorityStateV1.bootstrap(
        campaigns=(
            FastAuthorityCampaignV1(
                request=predecessor,
                owner_issue_number=predecessor_issue,
                owner_run_id=predecessor_run,
                terminal_receipt_sha256=predecessor_metadata["terminal_receipt_sha256"],
            ),
        )
    )
    (runner_temp / "catalog-fast-authority-current.json").write_text(
        authority.model_dump_json(), encoding="utf-8"
    )
    context = {
        "schema_version": "1",
        "document_type": "catalog_fast_request_context_v1",
        "protected_commit_sha": CURRENT_COMMIT,
        "request": request.model_dump(mode="json"),
        "identity": identity.model_dump(mode="json"),
        "issue_number": CURRENT_ISSUE,
        "issue_created_at": CURRENT_CREATED_AT,
        "actor": "requester",
        "request_mode": "admit_new",
    }
    context["content_sha256"] = canonical_sha256(context)
    context_path = runner_temp / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    github_output = runner_temp / "github-output.txt"
    target = runner_temp / "admitted"
    profiles = load_reduction_recovery_profiles(ROOT)
    profile = next(row for row in profiles if row.target_generation == target_generation)
    if target_generation == 11:
        assert len(profiles) == 3
        assert {row.target_generation for row in profiles} == {8, 9, 11}
        assert profile.source_generation == 10
        assert profile.terminal_reason_code == "CATALOG_ENGINE_STAGE_FAILED"
        assert profile.source_request_sha256 == SOURCE10_REQUEST_SHA256
        assert profile.source_issue_number == SOURCE10_ISSUE
        assert profile.source_run_id == SOURCE10_RUN
        assert profile.source_run_attempt == SOURCE10_RUN_ATTEMPT
        assert profile.source_terminal_receipt_sha256 == SOURCE10_TERMINAL_RECEIPT_SHA256
        assert profile.source_plan_bindings == GEN10_SOURCE_PLAN_BINDINGS
        assert profile.source_plan_receipt_sha256 == GEN10_SOURCE_PLAN_RECEIPT_SHA256
        assert profile.science_sha256 == GEN10_SOURCE_PLAN_BINDINGS["science_sha256"]
        assert profile.catalog_manifest_sha256 == GEN10_CATALOG_MANIFEST_SHA256
    else:
        assert profile.source_request_sha256 == source.request_sha256
        assert profile.source_issue_number == SOURCE_ISSUE
        assert profile.source_run_id == SOURCE_RUN
        assert profile.source_run_attempt == SOURCE_RUN_ATTEMPT
        assert profile.source_terminal_receipt_sha256 == source_metadata["terminal_receipt_sha256"]
    assert len(profile.strategy_ids) == 8
    assert set(profile.source_plan_bindings) == {
        "request_sha256",
        "decision_sha256",
        "protected_commit_sha",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
    }
    if include_profile:
        assert load_reduction_recovery_profiles(repo_root) == profiles
    terminal: CatalogTerminalReceiptV2 | None = original_terminal
    if terminal_mode == "mismatch":
        terminal = original_terminal.model_copy(update={"receipt_sha256": "0" * 64})
    elif terminal_mode == "missing":
        terminal = None
    elif terminal_mode != "valid":
        mutations = {
            "reason": {
                "reason_code": (
                    "CATALOG_REDUCTION_FAILED"
                    if original_terminal.reason_code == "CATALOG_ENGINE_STAGE_FAILED"
                    else "CATALOG_ENGINE_STAGE_FAILED"
                )
            },
            "status": {"state": "COMPLETED"},
            "observed": {"observed_recipe_count": 8},
            "science": {"result_science_sha256": profile.science_sha256},
        }
        # Keep the pinned hash to exercise semantic checks independently of hash mismatch.
        terminal = original_terminal.model_copy(update=mutations[terminal_mode])

    owner_decision = cast(
        Any,
        SimpleNamespace(
            decision_sha256=(
                GEN8_DECISION
                if target_generation == 9
                else profile.source_plan_bindings["decision_sha256"]
            ),
            prepared_receipt_sha256=(
                GEN8_PREPARED
                if target_generation == 9
                else GEN10_PREPARED
                if target_generation == 11
                else PREPARED_RECEIPT_SHA256
            ),
        ),
    )
    owner_run: dict[str, Any] = {
        "run_attempt": profile.predecessor_bindings.run_attempt,
        "head_sha": profile.predecessor_bindings.protected_commit_sha,
        "status": "completed",
    }
    owner = FastGateOwnerEvidence(
        run_id=predecessor_run,
        run=owner_run,
        decision=owner_decision,
    )
    if owner_mode == "attempt":
        owner_run["run_attempt"] = 2
    elif owner_mode == "head":
        owner_run["head_sha"] = "0" * 40
    elif owner_mode == "decision":
        owner_decision.decision_sha256 = "0" * 64
    owner_calls: list[int] = []
    terminal_calls: list[tuple[int, int]] = []

    def owner_reader(**kwargs: Any) -> FastGateOwnerEvidence | None:
        number = kwargs["issue_number"]
        owner_calls.append(number)
        return owner if number == predecessor_issue else None

    def terminal_reader(**kwargs: Any) -> Any:
        terminal_calls.append((kwargs["issue_number"], kwargs["owner"].run_id))
        return terminal

    issue = {
        "number": CURRENT_ISSUE,
        "title": title,
        "body": body,
        "user": {"login": "requester"},
        "state": "open",
        "labels": [],
        "created_at": CURRENT_CREATED_AT,
    }

    class Client:
        repository = "trading-optimizer-lab-org/aurora"
        observed_at = OBSERVED_AT

        def get_json(self, path: str) -> tuple[object, object]:
            assert path == f"/repos/{self.repository}/issues/{CURRENT_ISSUE}"
            return issue, None

        def stable_paginated(self, path: str, *, root: str) -> Any:
            assert path == f"/repos/{self.repository}/actions/caches?ref=refs/heads/main"
            assert root == "actions_caches"
            return SimpleNamespace(
                stable=True,
                collection=SimpleNamespace(
                    complete=True,
                    rows=[{"key": cache_key, "ref": "refs/heads/main"}],
                ),
            )

    monkeypatch.setattr(admission, "CatalogGitHubReadOnlyClient", lambda *args: Client())
    monkeypatch.setattr(admission, "load_fast_gate_owner", owner_reader)
    monkeypatch.setattr(admission, "load_owner_terminal_receipt", terminal_reader)
    for name, value in {
        "GITHUB_REPOSITORY": "trading-optimizer-lab-org/aurora",
        "GH_TOKEN": "fixture-only",
        "CATALOG_PROTECTED_COMMIT_SHA": CURRENT_COMMIT,
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_RUN_ID": str(CURRENT_RUN),
        "CATALOG_SAFE_FREE_CAPACITY": "7",
        "CATALOG_CONTROLLER_ENABLED": "true",
        "CATALOG_CONTROLLER_PRODUCTION_ARMED": "true",
    }.items():
        monkeypatch.setenv(name, value)

    template_before = _file_hashes(template)
    decision = admission.admit_request(
        request_context_path=context_path,
        prepared_bundle=bundle,
        repo_root=repo_root,
        output_dir=target,
        github_output=github_output,
    )
    return {
        "decision": decision,
        "profile": profile,
        "request": request,
        "target": target,
        "template": template,
        "prepared": prepared,
        "plan": plan,
        "owner_calls": owner_calls,
        "terminal_calls": terminal_calls,
        "template_before": template_before,
        "repo_root": repo_root,
        "include_profile": include_profile,
        "predecessor_issue": predecessor_issue,
        "predecessor_run": predecessor_run,
    }


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("target_generation", [8, 9, 11])
def test_real_recovery_admission_materializes_protected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_generation: int,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, target_generation=target_generation)
    decision = result["decision"]
    profile = result["profile"]
    target = result["target"]
    template = result["template"]
    assert decision.launch_required is True
    assert decision.state == "QUEUED"
    assert decision.selected_workers == 7
    assert result["owner_calls"] == [CURRENT_ISSUE, result["predecessor_issue"]]
    assert result["terminal_calls"] == [(result["predecessor_issue"], result["predecessor_run"])]
    sealed = target / "sealed-plan"
    assert json.loads((sealed / "reduction_recovery.json").read_text(encoding="utf-8")) == profile.model_dump(mode="json")
    verify_sealed_global_reuse_execution_plan(
        sealed,
        expected_bindings={
            "request_sha256": result["request"].request_sha256,
            "decision_sha256": decision.decision_sha256,
        },
    )
    assert result["template_before"] == _file_hashes(template)


@pytest.mark.parametrize("target_generation", [8, 9, 11])
@pytest.mark.parametrize("terminal_mode", ["mismatch", "missing"])
def test_real_recovery_admission_rejects_terminal_without_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_generation: int,
    terminal_mode: str,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, terminal_mode=terminal_mode,
                            target_generation=target_generation)
    decision = result["decision"]
    assert decision.launch_required is False
    assert decision.reason_code == "CATALOG_RECOVERY_PREDECESSOR_TERMINAL_INVALID"
    assert not (result["target"] / "sealed-plan").exists()
    assert result["owner_calls"] == [CURRENT_ISSUE, result["predecessor_issue"]]
    assert result["terminal_calls"] == [(result["predecessor_issue"], result["predecessor_run"])]


@pytest.mark.parametrize("target_generation", [8, 9, 11])
def test_real_recovery_admission_rejects_missing_profile_without_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_generation: int,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, include_profile=False,
                            target_generation=target_generation)
    decision = result["decision"]
    assert decision.launch_required is False
    assert decision.reason_code == "CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID"
    assert not (result["target"] / "sealed-plan").exists()
    assert result["owner_calls"] == [CURRENT_ISSUE]
    assert result["terminal_calls"] == []


@pytest.mark.parametrize("target_generation", [9, 11])
@pytest.mark.parametrize("owner_mode", ["attempt", "head", "decision"])
def test_gen9_and_gen11_reject_owner_corruption_before_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_generation: int,
    owner_mode: str,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, target_generation=target_generation,
                            owner_mode=owner_mode)
    assert result["decision"].launch_required is False
    assert result["decision"].reason_code == "CATALOG_RECOVERY_PREDECESSOR_OWNER_INVALID"
    assert result["owner_calls"] == [CURRENT_ISSUE, result["predecessor_issue"]]
    assert result["terminal_calls"] == []
    assert not (result["target"] / "sealed-plan").exists()


@pytest.mark.parametrize("target_generation", [9, 11])
@pytest.mark.parametrize("terminal_mode", ["reason", "status", "observed", "science"])
def test_gen9_and_gen11_reject_terminal_semantics_before_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_generation: int,
    terminal_mode: str,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, target_generation=target_generation,
                            terminal_mode=terminal_mode)
    assert result["decision"].launch_required is False
    assert result["decision"].reason_code == "CATALOG_RECOVERY_PREDECESSOR_TERMINAL_INVALID"
    assert result["terminal_calls"] == [(result["predecessor_issue"], result["predecessor_run"])]
    assert not (result["target"] / "sealed-plan").exists()


def test_gen9_rejects_altered_gen8_to_gen7_link_before_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_admission(tmp_path, monkeypatch, target_generation=9, altered_link=True)
    assert result["decision"].launch_required is False
    assert result["decision"].reason_code == "CATALOG_FAST_PREDECESSOR_CONFLICT"
    assert result["terminal_calls"] == []
    assert not (result["target"] / "sealed-plan").exists()
