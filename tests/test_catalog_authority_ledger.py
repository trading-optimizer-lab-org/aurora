from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from uuid import UUID

import jsonschema
import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityAnchorV1,
    CatalogAuthorityCheckpointV1,
    CatalogAuthorityRecordV1,
    CatalogControllerActorsV1,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
    parse_authority_comments,
    reconcile_authority_issue_tamper,
    reconcile_authority_mirrors,
    reconcile_request_tamper,
    select_campaign_authority,
    verify_authority_checkpoint,
    verify_authority_issue_anchor,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
BOT = "github-actions[bot]"
REPOSITORY = "trading-optimizer-lab-org/aurora"
HEAD = "5" * 40
AUTHORITY_ID = UUID("018f47a2-6e91-7c34-8000-000000000101")


def _canonical_sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _rehash_record(record: CatalogAuthorityRecordV1, **updates: object) -> CatalogAuthorityRecordV1:
    payload = record.model_dump(mode="json")
    payload.update(updates)
    payload.pop("record_sha256", None)
    payload["record_sha256"] = _canonical_sha256(payload)
    return CatalogAuthorityRecordV1.model_validate(payload)


def _first_record(**updates: object) -> CatalogAuthorityRecordV1:
    values: dict[str, object] = {
        "previous": None,
        "authority_id": AUTHORITY_ID,
        "request_issue_number": 101,
        "campaign_id": "c" * 64,
        "request_sha256": "1" * 64,
        "science_sha256": "2" * 64,
        "execution_plan_sha256": "3" * 64,
        "execution_protocol_sha256": "4" * 64,
        "state": AuthorityState.RESERVED,
        "run_id": 123,
        "run_attempt": 1,
        "writer_job_id": "reserve",
        "writer_job_database_id": 456,
        "protected_commit_sha": HEAD,
        "failure_fingerprint": None,
        "failure_occurrence_count": 0,
        "created_at": NOW,
    }
    values.update(updates)
    return append_authority_record(**values)


def _running_record(
    previous: CatalogAuthorityRecordV1 | None = None,
    **updates: object,
) -> CatalogAuthorityRecordV1:
    values: dict[str, object] = {
        "previous": previous or _first_record(),
        "state": AuthorityState.RUNNING,
        "run_id": 123,
        "run_attempt": 1,
        "writer_job_id": "record_running",
        "writer_job_database_id": 457,
        "protected_commit_sha": HEAD,
        "created_at": NOW + timedelta(seconds=1),
    }
    values.update(updates)
    return append_authority_record(**values)


def _comment(
    body: str,
    *,
    comment_id: int,
    author: str = BOT,
    edited: bool = False,
) -> dict[str, object]:
    created = NOW + timedelta(seconds=comment_id)
    return {
        "id": comment_id,
        "user": {"login": author},
        "body": body,
        "created_at": created.isoformat(),
        "updated_at": (
            (created + timedelta(seconds=1)).isoformat() if edited else created.isoformat()
        ),
    }


def _writer_run_snapshot(
    records: tuple[CatalogAuthorityRecordV1, ...],
) -> dict[int, dict[str, object]]:
    jobs = []
    for record in records:
        jobs.append(
            {
                "job_id": record.writer_job_id,
                "database_id": record.writer_job_database_id,
                "issues_write": True,
                "steps_are_allowlisted": True,
                "allowed_states": [record.state.value],
            }
        )
    return {
        123: {
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": HEAD,
            "workflow_path": ".github/workflows/catalog-run-controller.yml",
            "event": "issues",
            "repository": REPOSITORY,
            "complete": True,
            "pagination_complete": True,
            "stable": True,
            "authenticated": True,
            "etag": '"writer-run-123-v1"',
            "workflow_policy_verified": True,
            "jobs": jobs,
        }
    }


def _valid_chain() -> tuple[CatalogAuthorityRecordV1, CatalogAuthorityRecordV1]:
    first = _first_record()
    return first, _running_record(first)


def _parse_chain(
    records: tuple[CatalogAuthorityRecordV1, ...],
    *,
    snapshots: dict[int, dict[str, object]] | None = None,
) -> VerifiedAuthorityLedgerV1:
    comments = [
        _comment(record.to_comment(), comment_id=index + 1) for index, record in enumerate(records)
    ]
    return parse_authority_comments(
        comments,
        expected_author=BOT,
        writer_run_snapshots=(_writer_run_snapshot(records) if snapshots is None else snapshots),
    )


def _long_chain(length: int) -> tuple[CatalogAuthorityRecordV1, ...]:
    assert length >= 1
    records = [_first_record()]
    for index in range(1, length):
        records.append(
            append_authority_record(
                previous=records[-1],
                state=AuthorityState.RUNNING,
                run_id=123,
                run_attempt=1,
                writer_job_id="record_running",
                writer_job_database_id=1000 + index,
                protected_commit_sha=HEAD,
                created_at=NOW + timedelta(seconds=index),
            )
        )
    return tuple(records)


def test_valid_chain_round_trips_and_preserves_order() -> None:
    first, second = _valid_chain()
    ledger = _parse_chain((second, first), snapshots=_writer_run_snapshot((first, second)))
    assert ledger.latest == second
    assert ledger.records == (first, second)
    assert ledger.verified_writer_run_ids == (123,)
    assert first.artifact_name.endswith("-0000000000")


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("edited", "CATALOG_LEDGER_COMMENT_EDITED"),
        ("wrong_author", "CATALOG_LEDGER_AUTHOR_INVALID"),
        ("missing_middle", "CATALOG_LEDGER_SEQUENCE_GAP"),
        ("wrong_previous", "CATALOG_LEDGER_CHAIN_INVALID"),
        ("wrong_hash", "CATALOG_LEDGER_HASH_INVALID"),
        ("duplicate_sequence", "CATALOG_LEDGER_SEQUENCE_DUPLICATE"),
    ],
)
def test_any_ledger_tampering_fails_closed(mutation: str, reason: str) -> None:
    first, second = _valid_chain()
    third = append_authority_record(
        previous=second,
        state=AuthorityState.RUNNING,
        writer_job_database_id=458,
        created_at=NOW + timedelta(seconds=2),
    )
    snapshots = _writer_run_snapshot((first, second, third))
    comments = [
        _comment(first.to_comment(), comment_id=1),
        _comment(second.to_comment(), comment_id=2),
    ]
    if mutation == "edited":
        comments[0] = _comment(first.to_comment(), comment_id=1, edited=True)
    elif mutation == "wrong_author":
        comments[0] = _comment(first.to_comment(), comment_id=1, author="human")
    elif mutation == "missing_middle":
        comments = [comments[0], _comment(third.to_comment(), comment_id=3)]
    elif mutation == "wrong_previous":
        wrong = _rehash_record(second, previous_record_sha256="f" * 64)
        comments[1] = _comment(wrong.to_comment(), comment_id=2)
    elif mutation == "wrong_hash":
        broken_body = second.to_comment().replace(second.record_sha256, "f" * 64)
        comments[1] = _comment(broken_body, comment_id=2)
    elif mutation == "duplicate_sequence":
        comments.append(_comment(first.to_comment(), comment_id=3))
    with pytest.raises(ValueError, match=reason):
        parse_authority_comments(
            comments,
            expected_author=BOT,
            writer_run_snapshots=snapshots,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "writer_run_missing",
        "writer_attempt_mismatch",
        "writer_head_sha_mismatch",
        "writer_workflow_not_allowed",
        "writer_job_not_allowed_for_state",
        "writer_job_has_arbitrary_steps_with_issues_write",
        "writer_run_snapshot_incomplete",
    ],
)
def test_ledger_writer_provenance_is_mandatory(mutation: str) -> None:
    first, second = _valid_chain()
    snapshots = deepcopy(_writer_run_snapshot((first, second)))
    snapshot = snapshots[123]
    if mutation == "writer_run_missing":
        snapshots = {}
    elif mutation == "writer_attempt_mismatch":
        snapshot["run_attempt"] = 2
    elif mutation == "writer_head_sha_mismatch":
        snapshot["head_sha"] = "9" * 40
    elif mutation == "writer_workflow_not_allowed":
        snapshot["workflow_path"] = ".github/workflows/arbitrary.yml"
    elif mutation == "writer_job_not_allowed_for_state":
        snapshot["jobs"][0]["allowed_states"] = ["success"]
    elif mutation == "writer_job_has_arbitrary_steps_with_issues_write":
        snapshot["jobs"][0]["steps_are_allowlisted"] = False
    elif mutation == "writer_run_snapshot_incomplete":
        snapshot["pagination_complete"] = False
    with pytest.raises(ValueError, match="CATALOG_LEDGER_WRITER_PROVENANCE_INVALID"):
        _parse_chain((first, second), snapshots=snapshots)


def test_terminal_authority_cannot_return_to_running() -> None:
    first = _first_record()
    running = _running_record(first)
    terminal = append_authority_record(
        previous=running,
        state=AuthorityState.SUCCESS,
        writer_job_id="finalize",
        writer_job_database_id=458,
        evidence_sha256="e" * 64,
        created_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_TERMINAL"):
        append_authority_record(
            previous=terminal,
            state=AuthorityState.RUNNING,
            run_id=999,
            created_at=NOW + timedelta(seconds=3),
        )


def test_terminal_authority_requires_bound_evidence() -> None:
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_TERMINAL_EVIDENCE_REQUIRED"):
        append_authority_record(
            previous=_running_record(),
            state=AuthorityState.SUCCESS,
            writer_job_id="finalize",
            writer_job_database_id=458,
            created_at=NOW + timedelta(seconds=2),
        )


def test_nonterminal_authority_cannot_move_backwards() -> None:
    running = _running_record()
    recovering = append_authority_record(
        previous=running,
        state=AuthorityState.RECOVERING,
        writer_job_id="record_nonterminal_wait",
        writer_job_database_id=458,
        created_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_TRANSITION_INVALID"):
        append_authority_record(
            previous=recovering,
            state=AuthorityState.RUNNING,
            run_id=999,
            created_at=NOW + timedelta(seconds=3),
        )


def test_failure_count_cannot_decrease_skip_or_reach_three_without_blocking() -> None:
    running = _running_record()
    one = append_authority_record(
        previous=running,
        state=AuthorityState.RECOVERING,
        writer_job_id="record_nonterminal_wait",
        writer_job_database_id=458,
        failure_fingerprint="f" * 64,
        failure_occurrence_count=1,
        created_at=NOW + timedelta(seconds=2),
    )
    two = append_authority_record(
        previous=one,
        state=AuthorityState.RECOVERING,
        writer_job_database_id=459,
        failure_fingerprint="f" * 64,
        failure_occurrence_count=2,
        created_at=NOW + timedelta(seconds=3),
    )
    for count in (1, 4):
        with pytest.raises(ValueError, match="CATALOG_FAILURE_COUNT_INVALID"):
            append_authority_record(
                previous=two,
                state=AuthorityState.RECOVERING,
                failure_fingerprint="f" * 64,
                failure_occurrence_count=count,
                created_at=NOW + timedelta(seconds=4),
            )
    with pytest.raises(ValueError, match="CATALOG_FAILURE_LIMIT_REACHED"):
        append_authority_record(
            previous=two,
            state=AuthorityState.RECOVERING,
            failure_fingerprint="f" * 64,
            failure_occurrence_count=3,
            created_at=NOW + timedelta(seconds=4),
        )


def test_different_failure_fingerprint_restarts_at_one() -> None:
    running = _running_record()
    one = append_authority_record(
        previous=running,
        state=AuthorityState.RECOVERING,
        failure_fingerprint="a" * 64,
        failure_occurrence_count=1,
        created_at=NOW + timedelta(seconds=2),
    )
    changed = append_authority_record(
        previous=one,
        state=AuthorityState.RECOVERING,
        failure_fingerprint="b" * 64,
        failure_occurrence_count=1,
        created_at=NOW + timedelta(seconds=3),
    )
    assert changed.failure_occurrence_count == 1


def test_identity_and_protocol_are_immutable_without_safe_replan() -> None:
    previous = _running_record()
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_IDENTITY_CHANGED"):
        append_authority_record(
            previous=previous,
            state=AuthorityState.RUNNING,
            science_sha256="9" * 64,
            created_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="CATALOG_EXECUTION_PROTOCOL_CHANGED"):
        append_authority_record(
            previous=previous,
            state=AuthorityState.RUNNING,
            execution_protocol_sha256="9" * 64,
            created_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="CATALOG_OPERATIONAL_REPLAN_UNPROVEN"):
        append_authority_record(
            previous=previous,
            state=AuthorityState.RUNNING,
            execution_plan_sha256="9" * 64,
            created_at=NOW + timedelta(seconds=2),
        )


def test_deleted_tail_is_detected_from_mirror_and_must_be_restored() -> None:
    first, second = _valid_chain()
    result = reconcile_authority_mirrors(
        comment_records=(first,),
        artifact_records=(first, second),
        tamper_incidents=(),
        now=NOW,
    )
    assert result.status == "repair_required"
    assert result.missing_comment_records == (second,)
    assert result.safe_to_schedule_compute is False


def test_differing_comment_and_artifact_copy_blocks() -> None:
    first = _first_record()
    conflicting = _rehash_record(first, reason_code="DIFFERENT")
    with pytest.raises(ValueError, match="CATALOG_LEDGER_MIRROR_CONFLICT"):
        reconcile_authority_mirrors(
            comment_records=(first,),
            artifact_records=(conflicting,),
            tamper_incidents=(),
            now=NOW,
        )


def test_verified_checkpoint_covers_expired_individual_prefix_mirrors() -> None:
    chain = _long_chain(500)
    checkpoint = CatalogAuthorityCheckpointV1.build(
        records=chain[:497],
        writer_provenance_sha256s=("a" * 64,),
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    verified = verify_authority_checkpoint(
        checkpoint,
        live_records=chain,
        now=NOW,
    )
    assert verified.covered_through_sequence == 496
    assert verified.artifact_name.endswith(verified.tail_record_sha256)
    result = reconcile_authority_mirrors(
        comment_records=chain,
        artifact_records=chain[-3:],
        checkpoints=(checkpoint,),
        tamper_incidents=(),
        now=NOW,
    )
    assert result.status == "verified"
    assert result.covered_through_sequence == 499
    assert result.safe_to_schedule_compute is True


def test_missing_or_conflicting_checkpoint_never_downgrades_to_comments_only() -> None:
    chain = _long_chain(20)
    checkpoint = CatalogAuthorityCheckpointV1.build(
        records=chain,
        writer_provenance_sha256s=("a" * 64,),
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    conflicting = checkpoint.model_copy(update={"tail_record_sha256": "f" * 64})
    for checkpoints in ((), (conflicting,)):
        with pytest.raises(ValueError, match="CATALOG_LEDGER_MIRROR_COVERAGE_INVALID"):
            reconcile_authority_mirrors(
                comment_records=chain,
                artifact_records=(),
                checkpoints=checkpoints,
                tamper_incidents=(),
                now=NOW,
            )


def test_any_authority_comment_edit_or_delete_incident_blocks() -> None:
    first = _first_record()
    for action in ("edited", "deleted"):
        with pytest.raises(ValueError, match="CATALOG_LEDGER_TAMPER_INCIDENT"):
            reconcile_authority_mirrors(
                comment_records=(first,),
                artifact_records=(first,),
                tamper_incidents=({"action": action, "verified": True},),
                now=NOW,
            )


def test_request_tamper_blocks_only_its_originating_authority() -> None:
    authority = _running_record()
    origin = {"issue_number": 101, "action": "edited", "verified": True}
    duplicate = {"issue_number": 202, "action": "edited", "verified": True}
    assert reconcile_request_tamper(authority, (origin,)).authority_blocked is True
    result = reconcile_request_tamper(authority, (duplicate,))
    assert result.authority_blocked is False
    assert result.blocked_request_numbers == (202,)


def test_request_receipt_comment_tamper_requires_writer_provenance() -> None:
    authority = _running_record()
    for action in ("edited", "deleted"):
        incident = {
            "kind": "request_receipt_comment",
            "issue_number": 101,
            "action": action,
            "verified": True,
            "original_receipt_writer_provenance": {"verified": True},
        }
        assert reconcile_request_tamper(authority, (incident,)).authority_blocked
        incident["original_receipt_writer_provenance"] = {"verified": False}
        with pytest.raises(ValueError, match="CATALOG_REQUEST_TAMPER_PROVENANCE_INVALID"):
            reconcile_request_tamper(authority, (incident,))


def test_terminal_authority_stays_immutable_after_request_ui_tamper() -> None:
    running = _running_record()
    success = append_authority_record(
        previous=running,
        state=AuthorityState.SUCCESS,
        writer_job_id="finalize",
        writer_job_database_id=458,
        evidence_sha256="e" * 64,
        created_at=NOW + timedelta(seconds=2),
    )
    result = reconcile_request_tamper(
        success,
        ({"issue_number": 101, "action": "deleted", "verified": True},),
    )
    assert result.authority_blocked is False
    assert result.request_ui_untrusted is True


def test_authority_issue_lifecycle_tamper_is_global_blocker() -> None:
    ledger = VerifiedAuthorityLedgerV1.from_records(_valid_chain())
    for action in (
        "edited",
        "deleted",
        "transferred",
        "closed",
        "reopened",
        "locked",
        "unlocked",
    ):
        result = reconcile_authority_issue_tamper(
            ledger=ledger,
            incident={"action": action, "verified": True},
        )
        assert result.all_catalog_authorities_blocked is True
        assert result.recreate_authority_issue_allowed is False
        assert result.append_to_damaged_authority_allowed is False


def test_restored_current_state_does_not_erase_historical_lifecycle_tamper() -> None:
    result = reconcile_authority_issue_tamper(
        ledger=VerifiedAuthorityLedgerV1.from_records(_valid_chain()),
        incident=None,
        complete_timeline={
            "complete": True,
            "pagination_complete": True,
            "stable": True,
            "current_state": "open",
            "historical_events": ["closed", "reopened"],
        },
    )
    assert result.all_catalog_authorities_blocked is True
    assert result.reason_code == "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_INVALID"


def _enabled_anchor() -> CatalogAuthorityAnchorV1:
    return CatalogAuthorityAnchorV1(
        schema_version="1",
        production_enabled=True,
        repository=REPOSITORY,
        repository_node_id="R_kgDOExample",
        issue_number=77,
        issue_node_id="I_kwDOExample",
        exact_title="AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
        creator_login=BOT,
        created_at=NOW,
    )


def _valid_anchor_inputs() -> dict[str, object]:
    return {
        "anchor": _enabled_anchor(),
        "repository_variable_number": "77",
        "repository_snapshot": {
            "full_name": REPOSITORY,
            "node_id": "R_kgDOExample",
        },
        "issue_snapshot": {
            "number": 77,
            "node_id": "I_kwDOExample",
            "title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
            "user": {"login": BOT},
            "created_at": NOW.isoformat(),
            "state": "open",
            "locked": False,
            "repository_url": "https://api.github.com/repos/trading-optimizer-lab-org/aurora",
        },
    }


def test_bound_authority_issue_matches_protected_anchor_and_variable() -> None:
    result = verify_authority_issue_anchor(**_valid_anchor_inputs())
    assert result.status == "ready"


@pytest.mark.parametrize(
    "mutation",
    [
        "repository_variable_number_changed",
        "issue_node_id_changed",
        "repository_id_changed",
        "title_changed",
        "creator_changed",
        "created_at_changed",
        "issue_missing",
    ],
)
def test_any_authority_anchor_mismatch_globally_blocks(mutation: str) -> None:
    inputs = deepcopy(_valid_anchor_inputs())
    if mutation == "repository_variable_number_changed":
        inputs["repository_variable_number"] = "78"
    elif mutation == "issue_node_id_changed":
        inputs["issue_snapshot"]["node_id"] = "I_other"
    elif mutation == "repository_id_changed":
        inputs["repository_snapshot"]["node_id"] = "R_other"
    elif mutation == "title_changed":
        inputs["issue_snapshot"]["title"] = "changed"
    elif mutation == "creator_changed":
        inputs["issue_snapshot"]["user"]["login"] = "other[bot]"
    elif mutation == "created_at_changed":
        inputs["issue_snapshot"]["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif mutation == "issue_missing":
        inputs["issue_snapshot"] = None
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_ANCHOR_INVALID"):
        verify_authority_issue_anchor(**inputs)


def test_checked_in_actor_policy_is_deliberately_nonoperational() -> None:
    payload = json.loads((ROOT / "config/catalog_controller_actors_v1.json").read_text("utf-8"))
    actors = CatalogControllerActorsV1.model_validate(payload)
    assert actors.production_enabled is False
    assert actors.request_actors == ()
    assert actors.requester_public_key_path is None


def test_production_actor_policy_requires_separate_nonadmin_bot_and_public_key() -> None:
    valid = {
        "schema_version": "1",
        "production_enabled": True,
        "request_actors": ["aurora-catalog-requester[bot]"],
        "required_request_actor_kind": "non_admin_github_app",
        "requester_public_key_path": "config/catalog_requester_public_key_v1.pem",
        "requester_public_key_sha256": "a" * 64,
        "ledger_actor": BOT,
        "authority_issue_repository_variable": "CATALOG_AUTHORITY_ISSUE_NUMBER",
        "deny_actor_if_repository_admin_credential_is_exposed": True,
    }
    assert CatalogControllerActorsV1.model_validate(valid).production_enabled
    for actors in (["gomez5757"], [BOT], ["UPPER[bot]"], []):
        with pytest.raises(ValueError):
            CatalogControllerActorsV1.model_validate({**valid, "request_actors": actors})
    with pytest.raises(ValueError):
        CatalogControllerActorsV1.model_validate(
            {**valid, "requester_public_key_path": "config/other.pem"}
        )


def test_checked_in_anchor_is_disabled_and_schema_is_closed() -> None:
    payload = json.loads((ROOT / "config/catalog_authority_anchor_v1.json").read_text("utf-8"))
    schema = json.loads(
        (ROOT / "schemas/catalog_authority_anchor_v1.schema.json").read_text("utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(payload, schema)
    assert CatalogAuthorityAnchorV1.model_validate(payload).production_enabled is False
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**payload, "token": "forbidden"}, schema)


def test_select_campaign_authority_returns_one_identity_or_blocks_duplicates() -> None:
    first, second = _valid_chain()
    ledger = VerifiedAuthorityLedgerV1.from_records((first, second))
    assert select_campaign_authority(ledger, "c" * 64) == second
    assert select_campaign_authority(ledger, "9" * 64) is None

    duplicate = _first_record(
        previous=second,
        authority_id=UUID("018f47a2-6e91-7c34-8000-000000000202"),
        request_issue_number=202,
        campaign_id="c" * 64,
        writer_job_database_id=999,
        created_at=NOW + timedelta(seconds=3),
    )
    conflicting = VerifiedAuthorityLedgerV1.from_records((first, second, duplicate))
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_DUPLICATE"):
        select_campaign_authority(conflicting, "c" * 64)
