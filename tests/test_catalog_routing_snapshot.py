from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

import pytest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionEntryV1,
    CatalogCampaignDefinitionManifestV1,
    registry_entry_sha256,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import CatalogCampaignEntryV1
from aurora.infra.sp500_megarun.catalog_controller import catalog_campaign_id
from aurora.infra.sp500_megarun.catalog_execution_protocol import (
    PROTOCOL_COMMON_PATHS,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogRunIntentV1,
    CatalogRunRequestV1,
    _attestation_payload,
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_routing import CatalogRouteOutcome
from aurora.infra.sp500_megarun.catalog_routing_snapshot import (
    build_catalog_routing_bundle,
)


NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
HEAD = "a" * 40
REPOSITORY = "trading-optimizer-lab-org/aurora"
ACTOR = "aurora-catalog-requester[bot]"
AUTHORITY_NUMBER = 9


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _repository(tmp_path: Path) -> tuple[Path, CatalogRunRequestV1, str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_hash = sha256(public_der).hexdigest()
    key_path = root / "config/catalog_requester_public_key_v1.pem"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(public_pem)

    prompt = root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# prompt\n", encoding="utf-8")
    prompt_hash = sha256(prompt.read_bytes()).hexdigest()

    science_hash = "f" * 64
    entry = CatalogCampaignEntryV1(
        campaign_key="sp500-optimized-catalog-v1",
        engine_id="optimized_catalog_v1",
        definition_manifest_path=(
            "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json"
        ),
        optimization_policy_path="config/policy.json",
        campaign_contract_path="config/campaign.json",
        catalog_dir="config/catalog",
        selected_config_path="config/selected.json",
        admission_evidence_path="config/admission.json",
        data_contract_path="config/data.json",
        feature_contract_path="config/features.json",
        runtime_input_run_id=11,
        reference_run_id=12,
        scientific_contract_sha256=science_hash,
        max_free_workers=4,
        allowed_protected_branch="main",
        source_artifact_contracts=("runtime_input_pack_v1",),
        component_store_family="sp500_component_store_v1",
        reducer_family="catalog_hierarchical_reducer_v1",
        active=True,
    )
    for relative in entry.repository_paths:
        path = root / relative
        if relative == entry.catalog_dir:
            path.mkdir(parents=True)
        else:
            _write_json(path, {"boundaries": {"validation_opened": False, "locked_opened": False}} if relative == entry.campaign_contract_path else {})
    _write_json(
        root / "config/catalog_campaign_registry_v1.json",
        {"schema_version": "1", "campaigns": [entry.model_dump(mode="json")]},
    )
    source = root / "config/science.json"
    _write_json(source, {"science": "closed"})
    manifest = CatalogCampaignDefinitionManifestV1(
        schema_version="1",
        closure_algorithm="aurora-catalog-transitive-closure-v1",
        campaign_key=entry.campaign_key,
        registry_entry_sha256=registry_entry_sha256(entry),
        entries=(
            CatalogCampaignDefinitionEntryV1.from_bytes(
                path="config/science.json",
                role="science_code",
                content=source.read_bytes(),
            ),
        ),
    )
    manifest_path = root / entry.definition_manifest_path
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(canonical_model_bytes(manifest) + b"\n")
    _write_json(
        root / "config/catalog_controller_actors_v1.json",
        {
            "schema_version": "1",
            "production_enabled": True,
            "request_actors": [ACTOR],
            "required_request_actor_kind": "non_admin_github_app",
            "requester_public_key_path": "config/catalog_requester_public_key_v1.pem",
            "requester_public_key_sha256": key_hash,
            "ledger_actor": "github-actions[bot]",
            "authority_issue_repository_variable": "CATALOG_AUTHORITY_ISSUE_NUMBER",
            "deny_actor_if_repository_admin_credential_is_exposed": True,
        },
    )
    _write_json(
        root / "config/catalog_authority_anchor_v1.json",
        {
            "schema_version": "1",
            "production_enabled": True,
            "repository": REPOSITORY,
            "repository_node_id": "R_repo",
            "issue_number": AUTHORITY_NUMBER,
            "issue_node_id": "I_authority",
            "exact_title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
            "creator_login": "owner",
            "created_at": "2026-08-20T10:00:00Z",
        },
    )
    for relative in PROTOCOL_COMMON_PATHS:
        path = root.joinpath(*relative.split("/"))
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"test protocol fixture: {relative}\n", encoding="utf-8")

    intent = CatalogRunIntentV1(
        schema_version="1",
        request_id="018f47a2-6e91-7c34-8000-000000000001",
        campaign_key=entry.campaign_key,
        launch_generation=1,
        launch_ticket_sha256="1" * 64,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=prompt_hash,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    title = f"[AURORA CATALOG RUN REQUEST] {intent.request_id}"
    signature = private_key.sign(
        _attestation_payload(title, intent),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    request = CatalogRunRequestV1(
        **intent.model_dump(mode="json"),
        requester_public_key_sha256=key_hash,
        requester_attestation_algorithm="rsa-pss-sha256-v1",
        requester_attestation_b64=b64encode(signature).decode("ascii"),
    )
    return root, request, title, science_hash


def _request_issue(request: CatalogRunRequestV1, title: str) -> dict[str, object]:
    return {
        "id": 101,
        "node_id": "I_request",
        "number": 101,
        "title": title,
        "body": "```json\n" + canonical_model_bytes(request).decode() + "\n```\n",
        "user": {"login": ACTOR},
        "state": "open",
        "locked": False,
        "labels": [],
        "comments": 0,
        "created_at": "2026-08-21T09:59:00Z",
        "updated_at": "2026-08-21T09:59:00Z",
        "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
    }


def _authority_issue() -> dict[str, object]:
    return {
        "id": 9,
        "node_id": "I_authority",
        "number": AUTHORITY_NUMBER,
        "title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
        "body": "append-only",
        "user": {"login": "owner"},
        "state": "open",
        "locked": False,
        "labels": [],
        "comments": 0,
        "created_at": "2026-08-20T10:00:00Z",
        "updated_at": "2026-08-20T10:00:00Z",
        "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
    }


def _timeline(issue: dict[str, object]) -> dict[str, object]:
    return {
        "complete": True,
        "pagination_complete": True,
        "stable": True,
        "historical_events": [],
        "current_state": issue["state"],
        "current_state_reason": None,
        "current_labels": [],
    }


def _request_receipt(
    request_sha256: str,
    *,
    delivery_sequence: int = 0,
) -> CatalogRequestReceiptV1:
    summary = "Solicitud aplazada por capacidad ocupada."
    payload = {
        "schema_version": "1",
        "marker": "AURORA_CATALOG_REQUEST_RECEIPT_V1",
        "state": "DEFERRED",
        "reason_code": "CATALOG_CAPACITY_TEMPORARILY_BUSY",
        "issue_number": 101,
        "delivery_sequence": delivery_sequence,
        "request_sha256": request_sha256,
        "authority_id": None,
        "campaign_id": "c" * 64,
        "terminal_decision_sha256": None,
        "authority_record_sha256": None,
        "writer_run_id": 321,
        "writer_run_attempt": 1,
        "writer_job_id": "report_nonexecuting_decision",
        "writer_job_database_id": 654,
        "protected_commit_sha": HEAD,
        "summary_sha256": sha256(summary.encode("utf-8")).hexdigest(),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "retry_not_before": (NOW + timedelta(minutes=15)).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload["receipt_sha256"] = sha256(encoded).hexdigest()
    return CatalogRequestReceiptV1.model_validate(payload)


def _receipt_comment(
    receipt: CatalogRequestReceiptV1,
    *,
    comment_id: int = 987,
) -> dict[str, object]:
    return {
        "id": comment_id,
        "body": receipt.comment_body(
            "Solicitud aplazada por capacidad ocupada."
        ),
        "user": {"login": "github-actions[bot]"},
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _receipt_writer_snapshot() -> dict[str, object]:
    return {
        "run_id": 321,
        "run_attempt": 1,
        "head_sha": HEAD,
        "workflow_path": ".github/workflows/catalog-run-controller.yml",
        "event": "issues",
        "repository": REPOSITORY,
        "complete": True,
        "pagination_complete": True,
        "stable": True,
        "authenticated": True,
        "etag": '"receipt-etag"',
        "workflow_policy_verified": True,
        "jobs": [
            {
                "job_id": "report_nonexecuting_decision",
                "database_id": 654,
                "issues_write": True,
                "steps_are_allowlisted": True,
                "request_receipt_write": True,
            }
        ],
    }


def _bundle_with_receipt_evidence(
    tmp_path: Path,
    *,
    comment_mutator: object | None = None,
    writer_snapshots: tuple[object, ...] | None = None,
    artifact_receipts: tuple[object, ...] | None = None,
    additional_comments: tuple[object, ...] = (),
):
    root, request, title, _ = _repository(tmp_path)
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()
    receipt = _request_receipt(request.request_sha256)
    comment = _receipt_comment(receipt)
    if callable(comment_mutator):
        comment_mutator(comment)
    return build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=(comment, *additional_comments),
        request_timeline=_timeline(request_issue),
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="7" * 64,
        request_receipt_writer_snapshots=(
            (_receipt_writer_snapshot(),)
            if writer_snapshots is None
            else writer_snapshots
        ),
        request_receipt_artifacts=(
            (receipt,) if artifact_receipts is None else artifact_receipts
        ),
    )


def test_empty_verified_ledger_routes_one_fifo_request_without_privileged_inputs(
    tmp_path: Path,
) -> None:
    root, request, title, science_hash = _repository(tmp_path)
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()

    bundle = build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=(),
        request_timeline=_timeline(request_issue),
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="7" * 64,
    )

    assert bundle.command.request_sha256 == request.request_sha256
    assert bundle.command.campaign_id == catalog_campaign_id(
        campaign_key=request.campaign_key,
        scientific_contract_sha256=science_hash,
    )
    assert bundle.command.queue.eligible_open_issue_numbers == (101,)
    assert bundle.command.prerequisites.ledger_mirrors_verified is True
    decision = bundle.route()
    assert decision.outcome is CatalogRouteOutcome.ELIGIBLE
    assert decision.needs_live_audit is True


def test_request_lifecycle_mutation_blocks_even_when_current_text_is_valid(
    tmp_path: Path,
) -> None:
    root, request, title, _ = _repository(tmp_path)
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()
    timeline = _timeline(request_issue)
    timeline["historical_events"] = [
        {"id": 1, "event": "renamed", "actor": ACTOR}
    ]

    bundle = build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=(),
        request_timeline=timeline,
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="8" * 64,
    )

    assert bundle.route().reason_code == "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED"


def test_open_validation_boundary_blocks_before_live_audit(tmp_path: Path) -> None:
    root, request, title, _ = _repository(tmp_path)
    _write_json(
        root / "config/campaign.json",
        {"boundaries": {"validation_opened": True, "locked_opened": False}},
    )
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()

    bundle = build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=(),
        request_timeline=_timeline(request_issue),
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="9" * 64,
    )

    assert bundle.route().reason_code == "CATALOG_CLOSED_DATA_BOUNDARY_OPEN"


def test_request_receipt_requires_comment_writer_and_exact_artifact_mirror(
    tmp_path: Path,
) -> None:
    bundle = _bundle_with_receipt_evidence(tmp_path)
    document = bundle.request_receipts_document
    assert document["writer_receipt_history_valid"] is True
    assert document["writer_provenance_verified"] is True
    assert document["artifact_mirror_verified"] is True
    assert document["receipts"][0]["writer_provenance_verified"] is True
    assert document["receipts"][0]["artifact_mirror_verified"] is True


@pytest.mark.parametrize("mode", ("gap", "duplicate"))
def test_request_receipt_gap_or_duplicate_blocks_routing(
    tmp_path: Path,
    mode: str,
) -> None:
    root, request, title, _ = _repository(tmp_path)
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()
    receipt = _request_receipt(
        request.request_sha256,
        delivery_sequence=1 if mode == "gap" else 0,
    )
    comments = [_receipt_comment(receipt)]
    if mode == "duplicate":
        comments.append(_receipt_comment(receipt, comment_id=988))
    bundle = build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=tuple(comments),
        request_timeline=_timeline(request_issue),
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="7" * 64,
        request_receipt_writer_snapshots=(_receipt_writer_snapshot(),),
        request_receipt_artifacts=(receipt,),
    )

    document = bundle.request_receipts_document
    assert document["writer_receipt_history_valid"] is False
    if mode == "gap":
        assert document["sequence_valid"] is False
    assert bundle.route().reason_code == "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED"


@pytest.mark.parametrize("missing", ["writer", "mirror"])
def test_missing_request_receipt_proof_blocks_routing(
    tmp_path: Path,
    missing: str,
) -> None:
    bundle = _bundle_with_receipt_evidence(
        tmp_path,
        writer_snapshots=() if missing == "writer" else None,
        artifact_receipts=() if missing == "mirror" else None,
    )
    document = bundle.request_receipts_document
    assert document["writer_receipt_history_valid"] is False
    assert bundle.route().reason_code == "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED"


def test_wrong_request_receipt_writer_job_blocks_routing(tmp_path: Path) -> None:
    snapshot = _receipt_writer_snapshot()
    snapshot["jobs"][0]["database_id"] = 999
    bundle = _bundle_with_receipt_evidence(
        tmp_path,
        writer_snapshots=(snapshot,),
    )
    assert bundle.request_receipts_document["writer_provenance_verified"] is False
    assert bundle.route().reason_code == "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED"


def test_untrusted_request_receipt_marker_is_ignored(tmp_path: Path) -> None:
    def mutate(comment: dict[str, object]) -> None:
        comment["user"] = {"login": "human"}

    bundle = _bundle_with_receipt_evidence(
        tmp_path,
        comment_mutator=mutate,
        writer_snapshots=(),
        artifact_receipts=(),
    )
    receipt = bundle.request_receipts_document["receipts"][0]
    assert receipt["untrusted_marker_ignored"] is True
    assert bundle.request_receipts_document["writer_receipt_history_valid"] is True


def test_verified_request_receipt_tamper_incident_blocks_routing(
    tmp_path: Path,
) -> None:
    payload = {
        "schema_version": "1",
        "marker": "AURORA_CATALOG_REQUEST_COMMENT_TAMPER_V1",
        "relevant": True,
        "target_kind": "request_receipt",
        "issue_number": 101,
        "original_comment_id": 987,
        "event_action": "edited",
        "actor": "attacker",
        "writer_run_id": 400,
        "writer_run_attempt": 1,
        "protected_commit_sha": HEAD,
        "event_sha256": "1" * 64,
        "original_body_sha256": "2" * 64,
        "observed_body_sha256": "3" * 64,
        "artifact_name": "catalog-comment-tamper-400-1",
    }
    payload["incident_sha256"] = sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    incident = {
        "id": 988,
        "body": (
            "<!-- AURORA_CATALOG_REQUEST_COMMENT_TAMPER_V1 -->\n"
            f"```json\n{encoded}\n```\n"
        ),
        "user": {"login": "github-actions[bot]"},
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    bundle = _bundle_with_receipt_evidence(
        tmp_path,
        additional_comments=(incident,),
    )
    assert bundle.request_receipts_document["tamper_incident_verified"] is True
    assert bundle.route().reason_code == "CATALOG_REQUEST_RECEIPT_TAMPERED"
