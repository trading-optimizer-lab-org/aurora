"""Normalize one complete GitHub routing snapshot into the pure route command."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from pydantic import field_validator

from .catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityAnchorV1,
    CatalogAuthorityCheckpointV1,
    CatalogAuthorityRecordV1,
    CatalogControllerActorsV1,
    VerifiedAuthorityLedgerV1,
    parse_authority_comments,
    reconcile_authority_issue_tamper,
    reconcile_authority_mirrors,
    select_campaign_authority,
    verify_authority_issue_anchor,
)
from .catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
    registry_entry_sha256,
)
from .catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from .catalog_comment_tamper import (
    REQUEST_TAMPER_MARKER,
    parse_catalog_comment_tamper_incident,
)
from .catalog_controller import (
    CatalogProtectedHeadEvidenceV1,
    CatalogRequestQueueEvidenceV1,
    catalog_campaign_id,
)
from .catalog_execution_protocol import execution_protocol_sha256
from .catalog_request_contract import FrozenModel, canonical_model_bytes
from .catalog_request_receipt import (
    CatalogRequestReceiptV1,
    REQUEST_RECEIPT_MARKER,
    next_request_receipt_sequence,
    parse_request_receipt_comment,
    verify_request_receipt_writer_provenance,
)
from .catalog_routing import (
    CatalogRoutingCommandV1,
    CatalogRoutingDecisionV1,
    CatalogRoutingPrerequisitesV1,
    route_catalog_command,
)
from .catalog_run_request import parse_catalog_run_request


_REQUEST_MUTATIONS = frozenset(
    {
        "edited",
        "deleted",
        "transferred",
        "closed",
        "reopened",
        "renamed",
        "locked",
        "unlocked",
        "labeled",
        "unlabeled",
    }
)


def _strict_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_ROUTING_REPOSITORY_JSON_INVALID")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_ROUTING_REPOSITORY_JSON_NONFINITE:{value}")
        ),
    )


def _repository_file(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise ValueError("CATALOG_ROUTING_REPOSITORY_SYMLINK_FORBIDDEN")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_ROUTING_REPOSITORY_INPUT_INVALID")
    return resolved


def _canonical_sha256(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _issue_author(issue: Mapping[str, object]) -> str:
    user = _mapping(issue.get("user"), "CATALOG_REQUEST_INVALID")
    author = user.get("login")
    if not isinstance(author, str):
        raise ValueError("CATALOG_REQUEST_INVALID")
    return author


def _timeline_mutated(timeline: Mapping[str, object]) -> bool:
    if any(
        timeline.get(flag) is not True
        for flag in ("complete", "pagination_complete", "stable")
    ):
        return True
    events = timeline.get("historical_events", timeline.get("events", ()))
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return True
    for raw in events:
        if not isinstance(raw, Mapping):
            return True
        if raw.get("event") in _REQUEST_MUTATIONS:
            return True
    return False


def _evidence_common(
    *,
    observed_at: datetime,
    source_sha256: str,
    content: object,
) -> dict[str, object]:
    content_sha256 = _canonical_sha256(content)
    return {
        "schema_version": "1",
        "status": "ready",
        "observed_at": observed_at,
        "source_sha256": source_sha256,
        "content_sha256": content_sha256,
        "receipt_sha256": _canonical_sha256(
            {"source_sha256": source_sha256, "content_sha256": content_sha256}
        ),
        "reason_codes": (),
    }


def _resolve_verified_request(
    *,
    root: Path,
    issue: Mapping[str, object],
    actors: CatalogControllerActorsV1,
    public_key: bytes,
) -> tuple[object, CatalogCampaignEntryV1]:
    if issue.get("state") != "open" or issue.get("locked") is not False:
        raise ValueError("CATALOG_REQUEST_INVALID")
    if _issue_author(issue) not in actors.request_actors:
        raise ValueError("CATALOG_REQUEST_ACTOR_INVALID")
    title = issue.get("title")
    body = issue.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("CATALOG_REQUEST_INVALID")
    request = parse_catalog_run_request(title, body, public_key)
    if request.requester_public_key_sha256 != actors.requester_public_key_sha256:
        raise ValueError("CATALOG_REQUESTER_PUBLIC_KEY_FINGERPRINT_MISMATCH")
    prompt_path = _repository_file(root, "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md")
    if hashlib.sha256(prompt_path.read_bytes()).hexdigest() != request.prompt_sha256:
        raise ValueError("CATALOG_PROMPT_HASH_MISMATCH")
    registry = load_catalog_campaign_registry(
        _repository_file(root, "config/catalog_campaign_registry_v1.json")
    )
    entry = resolve_catalog_campaign(registry, request.campaign_key, root)
    manifest = parse_catalog_campaign_definition_bytes(
        _repository_file(root, entry.definition_manifest_path).read_bytes()
    )
    if (
        manifest.registry_entry_sha256 != registry_entry_sha256(entry)
        or manifest.campaign_definition_sha256
        != request.campaign_definition_sha256
    ):
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_MISMATCH")
    return request, entry


class CatalogRoutingBundleV1(FrozenModel):
    command: CatalogRoutingCommandV1
    event_document: dict[str, object]
    authority_issue_document: dict[str, object]
    authority_comments_document: dict[str, object]
    request_timeline_document: dict[str, object]
    request_receipts_document: dict[str, object]
    request_queue_document: dict[str, object]
    protected_head_document: dict[str, object]
    snapshot_manifest: dict[str, object]

    @field_validator(
        "event_document",
        "authority_issue_document",
        "authority_comments_document",
        "request_timeline_document",
        "request_receipts_document",
        "request_queue_document",
        "protected_head_document",
        "snapshot_manifest",
    )
    @classmethod
    def _copy_documents(cls, value: dict[str, object]) -> dict[str, object]:
        return dict(value)

    def route(self) -> CatalogRoutingDecisionV1:
        return route_catalog_command(self.command)


def build_catalog_routing_bundle(
    *,
    repo_root: Path,
    repository_snapshot: Mapping[str, object],
    repository_variable_number: str | int,
    protected_head_sha: str,
    expected_protected_commit_sha: str,
    request_issue: Mapping[str, object],
    open_issues: Sequence[Mapping[str, object]],
    request_comments: Sequence[Mapping[str, object]],
    request_timeline: Mapping[str, object],
    authority_issue: Mapping[str, object],
    authority_comments: Sequence[Mapping[str, object]],
    authority_timeline: Mapping[str, object],
    writer_run_snapshots: Sequence[object],
    artifact_records: Sequence[object],
    checkpoints: Sequence[object],
    tamper_incidents: Sequence[object],
    active_owner_authority_ids: Sequence[UUID],
    observed_at: datetime,
    snapshot_source_sha256: str,
    request_receipt_writer_snapshots: Sequence[object] = (),
    request_receipt_artifacts: Sequence[object] = (),
    reachable_protected_commits: Sequence[str] = (),
) -> CatalogRoutingBundleV1:
    """Build all normalized files used by cheap routing and later admission."""

    root = Path(repo_root).resolve(strict=True)
    if repo_root.is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_ROUTING_REPOSITORY_ROOT_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("CATALOG_ROUTING_TIME_INVALID")
    observed_at = observed_at.astimezone(UTC)
    actors = CatalogControllerActorsV1.model_validate(
        _strict_json(_repository_file(root, "config/catalog_controller_actors_v1.json"))
    )
    if not actors.production_enabled or actors.requester_public_key_path is None:
        raise ValueError("CATALOG_REQUEST_ACTOR_NOT_BOOTSTRAPPED")
    public_key = _repository_file(root, actors.requester_public_key_path).read_bytes()
    request, entry = _resolve_verified_request(
        root=root,
        issue=request_issue,
        actors=actors,
        public_key=public_key,
    )
    campaign_id = catalog_campaign_id(
        campaign_key=request.campaign_key,
        scientific_contract_sha256=entry.scientific_contract_sha256,
    )
    campaign_contract = _mapping(
        _strict_json(_repository_file(root, entry.campaign_contract_path)),
        "CATALOG_CAMPAIGN_CONTRACT_INVALID",
    )
    boundaries = _mapping(
        campaign_contract.get("boundaries"),
        "CATALOG_CAMPAIGN_CONTRACT_INVALID",
    )
    validation_opened = boundaries.get("validation_opened")
    locked_opened = boundaries.get("locked_opened")
    if not isinstance(validation_opened, bool) or not isinstance(locked_opened, bool):
        raise ValueError("CATALOG_CAMPAIGN_CONTRACT_INVALID")

    anchor = CatalogAuthorityAnchorV1.model_validate(
        _strict_json(_repository_file(root, "config/catalog_authority_anchor_v1.json"))
    )
    anchor_verification = verify_authority_issue_anchor(
        anchor=anchor,
        repository_variable_number=repository_variable_number,
        repository_snapshot=repository_snapshot,
        issue_snapshot=authority_issue,
    )
    ledger = parse_authority_comments(
        authority_comments,
        expected_author="github-actions[bot]",
        writer_run_snapshots=writer_run_snapshots,
    )
    checked_artifacts = tuple(
        CatalogAuthorityRecordV1.model_validate(item) for item in artifact_records
    )
    checked_checkpoints = tuple(
        CatalogAuthorityCheckpointV1.model_validate(item) for item in checkpoints
    )
    mirrors = reconcile_authority_mirrors(
        comment_records=ledger.records,
        artifact_records=checked_artifacts,
        checkpoints=checked_checkpoints,
        tamper_incidents=tamper_incidents,
        now=observed_at,
    )
    authority_lifecycle = reconcile_authority_issue_tamper(
        ledger=ledger,
        incident=None,
        complete_timeline=authority_timeline,
    )

    eligible: list[int] = []
    for raw_issue in open_issues:
        issue = _mapping(raw_issue, "CATALOG_REQUEST_QUEUE_INVALID")
        if "pull_request" in issue:
            continue
        try:
            queue_request, _ = _resolve_verified_request(
                root=root,
                issue=issue,
                actors=actors,
                public_key=public_key,
            )
        except (ValueError, TypeError, OSError):
            continue
        number = issue.get("number")
        if (
            queue_request is not None
            and isinstance(number, int)
            and not isinstance(number, bool)
            and number > 0
        ):
            eligible.append(number)
    eligible_numbers = tuple(sorted(set(eligible)))
    request_number = request_issue.get("number")
    if (
        isinstance(request_number, bool)
        or not isinstance(request_number, int)
        or request_number < 1
    ):
        raise ValueError("CATALOG_REQUEST_ISSUE_INVALID")
    queue_content = {
        "current_issue_number": request_number,
        "eligible_open_issue_numbers": eligible_numbers,
    }
    queue = CatalogRequestQueueEvidenceV1(
        **_evidence_common(
            observed_at=observed_at,
            source_sha256=snapshot_source_sha256,
            content=queue_content,
        ),
        complete=True,
        stable=True,
        current_issue_number=request_number,
        eligible_open_issue_numbers=eligible_numbers,
        request_queue_snapshot_sha256=_canonical_sha256(queue_content),
    )

    matching = select_campaign_authority(ledger, campaign_id)
    manifest_bytes = _repository_file(root, entry.definition_manifest_path).read_bytes()
    current_execution_protocol_sha256 = execution_protocol_sha256(
        root=root,
        entry=entry,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    reachable = frozenset(reachable_protected_commits)
    applicable_commit = (
        matching.protected_commit_sha if matching is not None else protected_head_sha
    )
    head_content = {
        "current_protected_head_sha": protected_head_sha,
        "applicable_commit_sha": applicable_commit,
        "original_bound_commit_sha": (
            matching.protected_commit_sha if matching is not None else None
        ),
        "current_execution_protocol_sha256": current_execution_protocol_sha256,
    }
    protected_head = CatalogProtectedHeadEvidenceV1(
        **_evidence_common(
            observed_at=observed_at,
            source_sha256=snapshot_source_sha256,
            content=head_content,
        ),
        current_protected_head_sha=protected_head_sha,
        applicable_commit_sha=applicable_commit,
        original_bound_commit_sha=(
            matching.protected_commit_sha if matching is not None else None
        ),
        original_commit_reachable_from_protected_history=(
            matching is None
            or matching.protected_commit_sha == protected_head_sha
            or matching.protected_commit_sha in reachable
        ),
        execution_protocol_compatible=(
            matching is None
            or matching.execution_protocol_sha256
            == current_execution_protocol_sha256
        ),
        protected_ref_verified=(protected_head_sha == expected_protected_commit_sha),
    )

    receipt_writer_snapshots: dict[int, Mapping[str, object]] = {}
    for raw_snapshot in request_receipt_writer_snapshots:
        snapshot = _mapping(
            raw_snapshot,
            "CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID",
        )
        run_id = snapshot.get("run_id", snapshot.get("id"))
        if (
            isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id < 1
            or run_id in receipt_writer_snapshots
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
        receipt_writer_snapshots[run_id] = snapshot
    receipt_artifacts: dict[str, CatalogRequestReceiptV1] = {}
    for raw_receipt in request_receipt_artifacts:
        receipt = (
            raw_receipt
            if isinstance(raw_receipt, CatalogRequestReceiptV1)
            else CatalogRequestReceiptV1.model_validate(raw_receipt)
        )
        if receipt.receipt_sha256 in receipt_artifacts:
            raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_CONFLICT")
        receipt_artifacts[receipt.receipt_sha256] = receipt

    normalized_request_receipts: list[dict[str, object]] = []
    trusted_receipt_hashes: set[str] = set()
    trusted_receipts: list[CatalogRequestReceiptV1] = []
    request_receipt_comment_history_valid = True
    writer_provenance_verified = True
    artifact_mirror_verified = True
    request_tamper_incidents: list[dict[str, object]] = []
    request_tamper_incident_verified = False
    for raw_comment in request_comments:
        body = raw_comment.get("body")
        user = raw_comment.get("user")
        author = user.get("login") if isinstance(user, Mapping) else None
        if isinstance(body, str) and REQUEST_TAMPER_MARKER in body:
            if author == "github-actions[bot]":
                try:
                    incident = parse_catalog_comment_tamper_incident(
                        raw_comment,
                        expected_issue_number=request_number,
                        expected_marker=REQUEST_TAMPER_MARKER,
                    )
                except ValueError:
                    request_tamper_incident_verified = True
                else:
                    if incident is not None:
                        request_tamper_incident_verified = True
                        request_tamper_incidents.append(
                            incident.model_dump(mode="json")
                        )
            continue
        if not isinstance(body, str) or REQUEST_RECEIPT_MARKER not in body:
            continue
        receipt: CatalogRequestReceiptV1 | None = None
        comment_valid = False
        provenance_valid = False
        mirror_valid = False
        if author == "github-actions[bot]":
            try:
                receipt = parse_request_receipt_comment(
                    raw_comment,
                    expected_author="github-actions[bot]",
                )
                if receipt is None:
                    raise ValueError
                comment_valid = (
                    receipt.issue_number == request_number
                    and receipt.request_sha256 == request.request_sha256
                    and receipt.receipt_sha256 not in trusted_receipt_hashes
                )
                if not comment_valid:
                    raise ValueError
                trusted_receipt_hashes.add(receipt.receipt_sha256)
                snapshot = receipt_writer_snapshots.get(receipt.writer_run_id)
                if snapshot is not None:
                    verify_request_receipt_writer_provenance(
                        receipt,
                        snapshot,
                        expected_repository=str(repository_snapshot.get("full_name")),
                    )
                    provenance_valid = True
                mirrored = receipt_artifacts.get(receipt.receipt_sha256)
                mirror_valid = (
                    mirrored is not None
                    and canonical_model_bytes(mirrored)
                    == canonical_model_bytes(receipt)
                )
                if provenance_valid and mirror_valid:
                    trusted_receipts.append(receipt)
            except (ValueError, TypeError, IndexError):
                comment_valid = False
        if author == "github-actions[bot]":
            request_receipt_comment_history_valid &= comment_valid
            writer_provenance_verified &= provenance_valid
            artifact_mirror_verified &= mirror_valid
        normalized_request_receipts.append(
            {
                "comment_id": raw_comment.get("id"),
                "author": author,
                "created_at": raw_comment.get("created_at"),
                "updated_at": raw_comment.get("updated_at"),
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "receipt_sha256": (
                    receipt.receipt_sha256 if receipt is not None else None
                ),
                "receipt": (
                    receipt.model_dump(mode="json")
                    if receipt is not None and comment_valid
                    else None
                ),
                "writer_receipt_valid": comment_valid,
                "writer_provenance_verified": provenance_valid,
                "artifact_mirror_verified": mirror_valid,
                "untrusted_marker_ignored": author != "github-actions[bot]",
            }
        )
    if set(receipt_artifacts) != trusted_receipt_hashes:
        artifact_mirror_verified = False
    try:
        next_delivery_sequence = next_request_receipt_sequence(
            trusted_receipts,
            issue_number=request_number,
            request_sha256=request.request_sha256,
        )
        request_receipt_sequence_valid = True
    except ValueError:
        next_delivery_sequence = 0
        request_receipt_sequence_valid = False
        request_receipt_comment_history_valid = False
    request_receipt_history_valid = (
        request_receipt_comment_history_valid
        and writer_provenance_verified
        and artifact_mirror_verified
        and request_receipt_sequence_valid
    )
    authority_retry_not_before = None
    authority_retry_evidence_verified = True
    if matching is not None and matching.state is AuthorityState.WAITING_RETRY:
        retry_receipts = [
            receipt
            for receipt in trusted_receipts
            if receipt.state == "WAITING_RETRY"
            and receipt.authority_id == matching.authority_id
            and receipt.authority_record_sha256 == matching.record_sha256
            and receipt.retry_not_before is not None
        ]
        if retry_receipts:
            latest_retry = max(
                retry_receipts,
                key=lambda item: (
                    item.created_at,
                    item.writer_run_id,
                    item.writer_run_attempt,
                    item.receipt_sha256,
                ),
            )
            authority_retry_not_before = latest_retry.retry_not_before
        else:
            authority_retry_evidence_verified = False
    request_lifecycle_clean = (
        not _timeline_mutated(request_timeline)
        and request_receipt_history_valid
        and not request_tamper_incident_verified
    )
    snapshot_identity = {
        "source_sha256": snapshot_source_sha256,
        "request_sha256": request.request_sha256,
        "campaign_id": campaign_id,
        "queue_sha256": queue.request_queue_snapshot_sha256,
        "ledger_sha256": ledger.ledger_sha256,
        "protected_head_sha": protected_head_sha,
        "authority_anchor_status": anchor_verification.status,
        "authority_lifecycle": authority_lifecycle.reason_code,
        "request_lifecycle_clean": request_lifecycle_clean,
        "request_receipt_writer_provenance_verified": (
            writer_provenance_verified
        ),
        "request_receipt_artifact_mirror_verified": artifact_mirror_verified,
        "request_tamper_incident_verified": request_tamper_incident_verified,
        "authority_retry_evidence_verified": authority_retry_evidence_verified,
        "authority_retry_not_before": (
            authority_retry_not_before.isoformat().replace("+00:00", "Z")
            if authority_retry_not_before is not None
            else None
        ),
    }
    routing_snapshot_sha256 = _canonical_sha256(snapshot_identity)
    prerequisites = CatalogRoutingPrerequisitesV1(
        observed_at=observed_at,
        request_verified=True,
        campaign_registered=True,
        protected_head_verified=protected_head.protected_ref_verified,
        authority_anchor_verified=anchor_verification.status == "ready",
        ledger_mirrors_verified=mirrors.safe_to_schedule_compute,
        request_receipt_tamper_free=not request_tamper_incident_verified,
        authority_retry_evidence_verified=authority_retry_evidence_verified,
        authority_retry_not_before=authority_retry_not_before,
        lifecycle_tamper_free=(
            not authority_lifecycle.all_catalog_authorities_blocked
            and request_lifecycle_clean
        ),
        snapshot_complete=True,
        snapshot_stable=True,
        validation_opened=validation_opened,
        locked_opened=locked_opened,
        active_owner_authority_ids=tuple(
            sorted(set(active_owner_authority_ids), key=str)
        ),
        routing_snapshot_sha256=routing_snapshot_sha256,
    )
    command = CatalogRoutingCommandV1(
        request_sha256=request.request_sha256,
        request_issue_number=request_number,
        campaign_id=campaign_id,
        queue=queue,
        ledger=ledger,
        prerequisites=prerequisites,
        verified_github_now=observed_at,
    )
    authority_issue_document = {
        "repository_variable_number": repository_variable_number,
        "repository_snapshot": dict(repository_snapshot),
        "issue_snapshot": dict(authority_issue),
    }
    authority_comments_document = {
        "comments": [dict(comment) for comment in authority_comments],
        "writer_run_snapshots": list(writer_run_snapshots),
        "artifact_records": [record.model_dump(mode="json") for record in checked_artifacts],
        "checkpoints": [item.model_dump(mode="json") for item in checked_checkpoints],
        "tamper_incidents": list(tamper_incidents),
        "authority_tamper_incident": None,
        "complete_timeline": dict(authority_timeline),
        "current_writer_context": {},
    }
    request_timeline_document = {
        "schema_version": "1",
        "request_issue_number": request_number,
        "timeline": dict(request_timeline),
        "complete": True,
        "stable": True,
        "lifecycle_clean": request_lifecycle_clean,
    }
    request_receipts_document = {
        "schema_version": "1",
        "request_issue_number": request_number,
        "receipts": normalized_request_receipts,
        "complete": True,
        "stable": True,
        "writer_receipt_history_valid": request_receipt_history_valid,
        "sequence_valid": request_receipt_sequence_valid,
        "next_delivery_sequence": next_delivery_sequence,
        "writer_provenance_verified": writer_provenance_verified,
        "artifact_mirror_verified": artifact_mirror_verified,
        "tamper_incident_verified": request_tamper_incident_verified,
        "tamper_incidents": request_tamper_incidents,
        "authority_retry_evidence_verified": authority_retry_evidence_verified,
        "authority_retry_not_before": (
            authority_retry_not_before.isoformat().replace("+00:00", "Z")
            if authority_retry_not_before is not None
            else None
        ),
        "trusted_receipt_sha256s": sorted(trusted_receipt_hashes),
    }
    event_document = {
        "repository": {"full_name": str(repository_snapshot.get("full_name"))},
        "issue": dict(request_issue),
    }
    snapshot_manifest = {
        "schema_version": "1",
        "api_snapshot_source_sha256": snapshot_source_sha256,
        "routing_snapshot_sha256": routing_snapshot_sha256,
        "request_sha256": request.request_sha256,
        "campaign_id": campaign_id,
        "ledger_sha256": ledger.ledger_sha256,
        "queue_sha256": queue.request_queue_snapshot_sha256,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "complete": True,
        "stable": True,
    }
    return CatalogRoutingBundleV1(
        command=command,
        event_document=event_document,
        authority_issue_document=authority_issue_document,
        authority_comments_document=authority_comments_document,
        request_timeline_document=request_timeline_document,
        request_receipts_document=request_receipts_document,
        request_queue_document=queue.model_dump(mode="json"),
        protected_head_document=protected_head.model_dump(mode="json"),
        snapshot_manifest=snapshot_manifest,
    )


__all__ = ["CatalogRoutingBundleV1", "build_catalog_routing_bundle"]
