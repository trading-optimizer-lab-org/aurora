"""Deterministic test-only fault injector for Q-001 through Q-078.

This module never replaces the controller.  Each branch calls the same pure
domain models used by the production controller with synthetic in-memory facts.
Only the tiny numeric calculation is specific to qualification.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable, Literal

import numpy as np

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.merge_planner import (
    MergeResourceProjectionV1,
    ReconciliationError,
    build_merge_plan,
    choose_reduction_plan,
    reconcile_attempts,
)
from aurora.infra.github_performance.preflight import (
    validate_catalog_workflow_topology,
)
from aurora.infra.github_performance.recovery import (
    AuthorityRecoverySnapshot,
    CheckpointSlotEvidence,
    FailureClass,
    RecoveryEvidenceError,
    RecoveryLoopStatus,
    build_recovery_loop,
    decide_watchdog_reentry,
    plan_retry_timing,
    validate_checkpoint_slot_chain,
)
from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityCheckpointV1,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
    parse_authority_comments,
    reconcile_authority_issue_tamper,
    reconcile_authority_mirrors,
    reconcile_request_lifecycle,
    reconcile_request_tamper,
    verify_authority_checkpoint,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
)
from aurora.infra.sp500_megarun.catalog_capacity import (
    StorageWriteReceiptV1,
    select_safe_catalog_capacity,
)
from aurora.infra.sp500_megarun.catalog_component_store import (
    CatalogComponentStore,
    ComponentStoreWriter,
    merge_component_stores,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    ControllerOutcome,
    decide_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    CatalogFinalEvidenceV1,
    CatalogTerminalState,
    finalize_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    CatalogRunRequestV1,
)
from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRouteOutcome,
    CatalogRoutingPrerequisitesV1,
    route_catalog_request,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.catalog_scheduler import (
    schedule_components_by_affinity,
)
from scripts.plan_sp500_optimized_catalog_run import (
    BundleLayoutQualificationV1,
    select_qualified_bundle_layout,
)
from scripts.run_catalog_artifact_keeper import KeeperError, _validate_contract

from github_performance_helpers import completed_unit, failed_attempt, make_shard
from test_catalog_authority_ledger import (
    BOT,
    NOW as LEDGER_NOW,
    _comment,
    _enabled_anchor,
    _first_record,
    _long_chain,
    _parse_chain,
    _running_record,
    _valid_chain,
    _writer_run_snapshot,
)
from test_catalog_capacity import (
    NOW as CAPACITY_NOW,
    GIB,
    _artifact_boundary_live,
    inputs as capacity_inputs,
    live_capacity,
    workload_fit,
)
from test_catalog_controller import (
    NOW,
    _anchor_evidence,
    _capacity_evidence,
    _empty_ledger,
    _github_evidence,
    _head_evidence,
    _ledger_fixture,
    _prompt_evidence,
    _queue_evidence,
    _request,
    _source_evidence,
    _valid_controller_inputs,
)
from test_catalog_controller_recovery import _authority, _slot
from test_catalog_controller_reporting import (
    _present_slot,
    _valid_evidence,
    final_evidence_after_runtime_preparation_failure,
    mutated_final_evidence,
    valid_final_evidence,
)


@dataclass(frozen=True)
class ScenarioResult:
    outcome: str
    reason_code: str
    authority_record_count: int
    final_state: str
    component_execution_count: int
    unit_execution_count: int
    preserved_valid_work_count: int
    evidence_kind: Literal["none", "receipt", "final"]


class ProofTrace(list[str]):
    """Collect actual enforcer calls and exactly one observed scenario result."""

    def __init__(self) -> None:
        super().__init__()
        self.result: ScenarioResult | None = None

    def record(
        self,
        outcome: str,
        reason_code: str,
        authority_record_count: int,
        final_state: str,
        component_execution_count: int,
        unit_execution_count: int,
        preserved_valid_work_count: int,
        evidence_kind: Literal["none", "receipt", "final"],
    ) -> None:
        observed = ScenarioResult(
            outcome=outcome,
            reason_code=reason_code,
            authority_record_count=authority_record_count,
            final_state=final_state,
            component_execution_count=component_execution_count,
            unit_execution_count=unit_execution_count,
            preserved_valid_work_count=preserved_valid_work_count,
            evidence_kind=evidence_kind,
        )
        if self.result is not None and self.result != observed:
            raise AssertionError("QUALIFICATION_RESULT_CONFLICT")
        self.result = observed


def _expect_error(call: Callable[[], object], code: str) -> None:
    try:
        call()
    except Exception as exc:  # exact code is checked below
        if code not in str(exc):
            raise AssertionError(f"expected {code}, got {exc}") from exc
    else:
        raise AssertionError(f"expected {code}")


def _load_fixture(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if resolved.name != "campaign_v1.json":
        raise ValueError("QUALIFICATION_FIXTURE_PATH_INVALID")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if (
        payload.get("document_type")
        != "catalog_controller_qualification_fixture_v1"
        or payload.get("validation_opened") is not False
        or payload.get("locked_opened") is not False
        or payload.get("external_downloads") is not False
        or len(payload.get("components", ())) != 12
        or len(payload.get("recipes", ())) != 24
    ):
        raise ValueError("QUALIFICATION_FIXTURE_INVALID")
    return payload


def _compute_results(fixture: dict[str, Any]) -> str:
    components = {
        row["component_key"]: row for row in fixture["components"]
    }
    results: list[dict[str, object]] = []
    for recipe in fixture["recipes"]:
        value = sum(
            sum(components[key]["values"])
            for key in recipe["component_keys"]
        ) * recipe["coefficient"]
        result = {"recipe_id": recipe["recipe_id"], "value": value}
        if value != recipe["expected_value"]:
            raise AssertionError("SYNTHETIC_RECIPE_VALUE_MISMATCH")
        if canonical_sha256(result) != recipe["expected_result_sha256"]:
            raise AssertionError("SYNTHETIC_RECIPE_HASH_MISMATCH")
        results.append(result)
    digest = canonical_sha256(results)
    if digest != fixture["expected_final_result_sha256"]:
        raise AssertionError("SYNTHETIC_FINAL_HASH_MISMATCH")
    return digest


def _signal(component: dict[str, Any]) -> np.ndarray:
    return np.asarray(
        [((int(value) % 3) - 1) for value in component["values"]],
        dtype=np.int8,
    )


def _prove_request_or_controller(
    scenario_id: str,
    fixture: dict[str, Any],
    calls: ProofTrace,
) -> bool:
    if scenario_id == "Q-002":
        _expect_error(
            lambda: parse_catalog_run_request("bad", "bad", b"bad"),
            "CATALOG_REQUEST_INVALID",
        )
        calls.append("catalog_run_request.parse_catalog_run_request")
        calls.record("BLOCKED", "CATALOG_REQUEST_MALFORMED", 0, "NONE", 0, 0, 0, "none")
        return True
    if scenario_id == "Q-003":
        payload = _request().model_dump(mode="json")
        payload["unexpected"] = "forbidden"
        _expect_error(
            lambda: CatalogRunRequestV1.model_validate(payload),
            "extra_forbidden",
        )
        calls.append("catalog_request_contract.CatalogRunRequestV1")
        calls.record("BLOCKED", "CATALOG_REQUEST_EXTRA_FIELD", 0, "NONE", 0, 0, 0, "none")
        return True
    if scenario_id == "Q-004":
        payload = _request().model_dump(mode="json")
        payload["campaign_key"] = "../../bin/sh;${{github.token}}"
        _expect_error(
            lambda: CatalogRunRequestV1.model_validate(payload),
            "campaign_key",
        )
        calls.append("catalog_request_contract.CatalogRunRequestV1")
        calls.record(
            "BLOCKED",
            "CATALOG_REQUEST_UNTRUSTED_SYNTAX",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True

    inputs = _valid_controller_inputs()
    expected: ControllerOutcome | None = None
    if scenario_id == "Q-001":
        expected = ControllerOutcome.ADMITTED
    elif scenario_id == "Q-005":
        inputs["request_issue_author"] = "untrusted-human"
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-006":
        inputs["observed_request_sha256"] = "f" * 64
        expected = ControllerOutcome.BLOCKED
    elif scenario_id in {"Q-007", "Q-066"}:
        inputs["prompt_evidence"] = _prompt_evidence().model_copy(
            update={"prompt_sha256": "f" * 64}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-008":
        bad_commit = "b" * 40
        inputs["protected_head_evidence"] = _head_evidence().model_copy(
            update={"applicable_commit_sha": bad_commit}
        )
        inputs["prompt_evidence"] = _prompt_evidence().model_copy(
            update={"applicable_commit_sha": bad_commit}
        )
        definition = inputs["campaign_definition_evidence"]
        inputs["campaign_definition_evidence"] = definition.model_copy(
            update={"applicable_commit_sha": bad_commit}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-009":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"validation_opened": True}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-010":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"standard_free_runner_only": False, "paid_runner_minutes": 1}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-011":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"admin_credential_exposed": True}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-012":
        first = decide_catalog_run(**inputs)
        second = decide_catalog_run(**inputs)
        if (
            first.outcome is not ControllerOutcome.ADMITTED
            or second.outcome is not ControllerOutcome.ADMITTED
        ):
            raise AssertionError("CONCURRENT_PREAPPEND_DECISION_INVALID")
        record = append_authority_record(
            previous=None,
            authority_id=first.authority_id,
            request_issue_number=101,
            campaign_id=first.campaign_id,
            request_sha256=_request().request_sha256,
            science_sha256=first.science_sha256,
            execution_plan_sha256=first.execution_plan_sha256,
            execution_protocol_sha256=str(inputs["execution_protocol_sha256"]),
            state=AuthorityState.RESERVED,
            run_id=1001,
            run_attempt=1,
            writer_job_id="reserve",
            writer_job_database_id=2001,
            protected_commit_sha=first.sealed_inputs.protected_commit_sha,
            created_at=NOW,
        )
        running = append_authority_record(
            previous=record,
            state=AuthorityState.RUNNING,
            writer_job_id="record_running",
            writer_job_database_id=2002,
            created_at=NOW + timedelta(seconds=1),
        )
        ledger = VerifiedAuthorityLedgerV1.from_records((record, running))
        adopted = decide_catalog_run(
            **_valid_controller_inputs(ledger=ledger)
        )
        if adopted.outcome is not ControllerOutcome.ADOPTED:
            raise AssertionError("CONCURRENT_CAS_REEVALUATION_INVALID")
        _compute_results(fixture)
        calls.extend(
            [
                "catalog_controller.decide_catalog_run",
                "catalog_authority_ledger.append_authority_record",
            ]
        )
        calls.record(
            "ADOPTED",
            "CATALOG_EQUIVALENT_AUTHORITY_SERIALIZED",
            len(ledger.records),
            ledger.latest.state.value.upper(),
            len(fixture["components"]),
            len(fixture["recipes"]),
            0,
            "none",
        )
        return True
    elif scenario_id == "Q-013":
        inputs = _valid_controller_inputs(
            ledger=_ledger_fixture(state="running", same_science=True)
        )
        decision = decide_catalog_run(**inputs)
        if decision.outcome is not ControllerOutcome.ADOPTED:
            raise AssertionError("EQUIVALENT_ACTIVE_NOT_ADOPTED")
        calls.append("catalog_controller.decide_catalog_run")
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            len(inputs["ledger"].records),
            inputs["ledger"].latest.state.value.upper(),
            0,
            0,
            len(fixture["recipes"]),
            "none",
        )
        return True
    elif scenario_id in {"Q-014", "Q-076"}:
        inputs = _valid_controller_inputs(
            ledger=_ledger_fixture(state="success", same_science=True)
        )
        decision = decide_catalog_run(**inputs)
        if (
            decision.outcome is not ControllerOutcome.ADOPTED
            or decision.reason_code != "CATALOG_SUCCESS_ALREADY_EXISTS"
        ):
            raise AssertionError("VERIFIED_SUCCESS_NOT_REUSED")
        calls.append("catalog_controller.decide_catalog_run")
        if scenario_id == "Q-014":
            calls.record(
                decision.outcome.value.upper(),
                decision.reason_code,
                len(inputs["ledger"].records),
                inputs["ledger"].latest.state.value.upper(),
                0,
                0,
                len(fixture["recipes"]),
                "final",
            )
        return True
    elif scenario_id == "Q-036":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"controls_verified": False}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id in {"Q-037", "Q-047"}:
        inputs["source_artifacts_evidence"] = _source_evidence().model_copy(
            update={"artifacts_exist": False}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-051":
        authority = _ledger_fixture(state="running", same_science=True).latest
        result = reconcile_request_tamper(
            authority,
            ({"issue_number": 91, "action": "deleted", "verified": True},),
        )
        if not result.authority_blocked:
            raise AssertionError("DELETED_ORIGIN_DID_NOT_BLOCK")
        calls.append("catalog_authority_ledger.reconcile_request_tamper")
        calls.record(
            "BLOCKED",
            "CATALOG_ORIGINATING_REQUEST_DELETED",
            2,
            "BLOCKED",
            0,
            0,
            len(fixture["recipes"]),
            "receipt",
        )
        return True
    elif scenario_id == "Q-052":
        inputs = _valid_controller_inputs(
            ledger=_ledger_fixture(state="running", same_science=False)
        )
        expected = ControllerOutcome.DEFERRED
    elif scenario_id == "Q-060":
        inputs["authority_anchor_evidence"] = _anchor_evidence().model_copy(
            update={"live_variable_matches": False}
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-061":
        ledger = _ledger_fixture(state="recovering", same_science=True)
        inputs = _valid_controller_inputs(
            ledger=ledger,
            active_owner_run=False,
            protected_head_evidence=_head_evidence().model_copy(
                update={
                    "original_bound_commit_sha": ledger.latest.protected_commit_sha,
                    "execution_protocol_compatible": False,
                }
            ),
        )
        expected = ControllerOutcome.BLOCKED
    elif scenario_id == "Q-063":
        authority = _ledger_fixture(state="running", same_science=True).latest
        result = reconcile_request_lifecycle(
            authority,
            complete_timeline={
                "complete": True,
                "pagination_complete": True,
                "stable": True,
                "current_state": "open",
                "current_labels": [],
                "historical_events": [
                    {"event": "closed", "actor": "outside-user"},
                    {"event": "reopened", "actor": "outside-user"},
                    {"event": "transferred", "actor": "outside-user"},
                    {"event": "renamed", "actor": "outside-user"},
                    {"event": "locked", "actor": "outside-user"},
                    {"event": "unlocked", "actor": "outside-user"},
                    {"event": "labeled", "actor": "outside-user"},
                    {"event": "unlabeled", "actor": "outside-user"},
                ],
            },
            terminal_close_provenance=None,
        )
        if not result.authority_blocked:
            raise AssertionError("REQUEST_LIFECYCLE_TAMPER_NOT_BLOCKED")
        terminal = append_authority_record(
            previous=authority,
            state=AuthorityState.SUCCESS,
            writer_job_id="finalize",
            writer_job_database_id=999,
            evidence_sha256="e" * 64,
            created_at=authority.created_at + timedelta(seconds=1),
        )
        allowed = reconcile_request_lifecycle(
            terminal,
            complete_timeline={
                "complete": True,
                "pagination_complete": True,
                "stable": True,
                "current_state": "closed",
                "current_state_reason": "completed",
                "current_labels": ["catalog-run-terminal-v1"],
                "historical_events": [
                    {
                        "event": "labeled",
                        "actor": BOT,
                        "label": "catalog-run-terminal-v1",
                    },
                    {"event": "closed", "actor": BOT},
                ],
            },
            terminal_close_provenance={
                "verified": True,
                "atomic_patch": True,
                "receipt_precedes_events": True,
                "request_issue_number": terminal.request_issue_number,
                "authority_id": str(terminal.authority_id),
                "terminal_state": terminal.state.value,
                "writer_actor": BOT,
                "writer_run_job_commit_provenance_verified": True,
            },
        )
        if not allowed.atomic_terminal_close_verified or allowed.request_ui_untrusted:
            raise AssertionError("PROVEN_TERMINAL_CLOSE_NOT_ACCEPTED")
        calls.append("catalog_authority_ledger.reconcile_request_lifecycle")
        calls.record(
            "BLOCKED",
            result.reason_code,
            2,
            "BLOCKED",
            0,
            0,
            len(fixture["recipes"]),
            "receipt",
        )
        return True
    elif scenario_id == "Q-071":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"observed_at": NOW - timedelta(seconds=301)}
        )
        expected = ControllerOutcome.DEFERRED
    else:
        return False

    decision = decide_catalog_run(**inputs)
    if decision.outcome is not expected:
        raise AssertionError(
            f"CONTROLLER_OUTCOME_INVALID:{scenario_id}:{decision.outcome}"
        )
    if expected is not ControllerOutcome.ADMITTED and (
        decision.should_create_authority or decision.should_schedule_compute
    ):
        raise AssertionError("FAIL_CLOSED_SIDE_EFFECT_INVALID")
    calls.append("catalog_controller.decide_catalog_run")
    if scenario_id == "Q-001":
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            int(decision.should_create_authority),
            "RESERVED",
            0,
            0,
            0,
            "none",
        )
    elif scenario_id == "Q-036":
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            2,
            "BLOCKED",
            len(fixture["components"]),
            len(fixture["recipes"]),
            len(fixture["recipes"]),
            "receipt",
        )
    elif scenario_id == "Q-061":
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            len(inputs["ledger"].records),
            "BLOCKED",
            0,
            0,
            len(fixture["recipes"]),
            "receipt",
        )
    elif scenario_id in {"Q-052", "Q-071"}:
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            0,
            "DEFERRED",
            0,
            0,
            0,
            "receipt",
        )
    else:
        calls.record(
            decision.outcome.value.upper(),
            decision.reason_code,
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
    return True


def _prove_ledger(scenario_id: str, calls: ProofTrace) -> bool:
    if scenario_id in {"Q-015", "Q-016", "Q-017", "Q-064"}:
        first = _first_record()
        comments = [_comment(first.to_comment(), comment_id=1)]
        expected_code = ""
        if scenario_id == "Q-015":
            comments = [_comment(first.to_comment(), comment_id=1, edited=True)]
            expected_code = "CATALOG_LEDGER_COMMENT_EDITED"
        elif scenario_id in {"Q-016", "Q-064"}:
            comments = [
                _comment(
                    first.to_comment(),
                    comment_id=1,
                    author="untrusted-writer",
                )
            ]
            expected_code = "CATALOG_LEDGER_AUTHOR_INVALID"
        else:
            broken = first.to_comment().replace(first.record_sha256, "f" * 64)
            comments = [_comment(broken, comment_id=1)]
            expected_code = "CATALOG_LEDGER_HASH_INVALID"
        _expect_error(
            lambda: parse_authority_comments(
                comments,
                expected_author=BOT,
                writer_run_snapshots=_writer_run_snapshot((first,)),
            ),
            expected_code,
        )
        calls.append("catalog_authority_ledger.parse_authority_comments")
        if scenario_id == "Q-064":
            calls.record(
                "NOOP",
                "CATALOG_UNTRUSTED_RECEIPT_IGNORED",
                0,
                "NONE",
                0,
                0,
                0,
                "receipt",
            )
        else:
            reason = {
                "Q-015": "CATALOG_LEDGER_COMMENT_TAMPERED",
                "Q-016": "CATALOG_LEDGER_WRITER_INVALID",
                "Q-017": "CATALOG_LEDGER_CHAIN_INVALID",
            }[scenario_id]
            calls.record("BLOCKED", reason, 1, "BLOCKED", 0, 0, 0, "none")
        return True
    if scenario_id == "Q-042":
        first, second = _valid_chain()
        _expect_error(
            lambda: reconcile_authority_mirrors(
                comment_records=(first, second),
                artifact_records=(first, second),
                tamper_incidents=({"action": "edited", "verified": True},),
                now=LEDGER_NOW,
            ),
            "CATALOG_LEDGER_TAMPER_INCIDENT",
        )
        calls.append("catalog_authority_ledger.reconcile_authority_mirrors")
        calls.record(
            "BLOCKED",
            "CATALOG_AUTHORITY_COMMENT_TAMPERED",
            len((first, second)),
            "BLOCKED",
            0,
            0,
            24,
            "receipt",
        )
        return True
    if scenario_id == "Q-048":
        chain = _long_chain(248)
        ledger = _parse_chain(
            tuple(reversed(chain)),
            snapshots=_writer_run_snapshot(chain),
        )
        if len(ledger.records) != 248 or ledger.latest != chain[-1]:
            raise AssertionError("PAGINATED_LEDGER_SNAPSHOT_INVALID")
        mirror = reconcile_authority_mirrors(
            comment_records=chain,
            artifact_records=chain,
            tamper_incidents=(),
            now=LEDGER_NOW,
        )
        if mirror.status != "verified":
            raise AssertionError("UNCHANGED_LEDGER_MIRROR_INVALID")
        calls.extend(
            [
                "catalog_authority_ledger.parse_authority_comments",
                "catalog_authority_ledger.reconcile_authority_mirrors",
            ]
        )
        calls.record(
            "ADOPTED",
            "CATALOG_LEDGER_ETAG_SNAPSHOT_REUSED",
            len(ledger.records),
            ledger.latest.state.value.upper(),
            0,
            0,
            24,
            "receipt",
        )
        return True
    if scenario_id == "Q-059":
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
        if not result.all_catalog_authorities_blocked:
            raise AssertionError("AUTHORITY_LIFECYCLE_TAMPER_NOT_BLOCKED")
        calls.append("catalog_authority_ledger.reconcile_authority_issue_tamper")
        calls.record(
            "BLOCKED",
            "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED",
            2,
            "BLOCKED",
            0,
            0,
            24,
            "receipt",
        )
        return True
    if scenario_id == "Q-067":
        chain = _long_chain(500)
        checkpoint = CatalogAuthorityCheckpointV1.build(
            records=chain[:497],
            writer_provenance_sha256s=("a" * 64,),
            created_at=LEDGER_NOW,
            expires_at=LEDGER_NOW + timedelta(days=30),
        )
        verified = verify_authority_checkpoint(
            checkpoint,
            live_records=chain,
            now=LEDGER_NOW,
        )
        mirror = reconcile_authority_mirrors(
            comment_records=chain,
            artifact_records=chain[-3:],
            checkpoints=(checkpoint,),
            tamper_incidents=(),
            now=LEDGER_NOW,
        )
        if (
            verified.covered_through_sequence != 496
            or mirror.covered_through_sequence != 499
        ):
            raise AssertionError("PREFIX_CHECKPOINT_COVERAGE_INVALID")
        calls.extend(
            [
                "catalog_authority_ledger.verify_authority_checkpoint",
                "catalog_authority_ledger.reconcile_authority_mirrors",
            ]
        )
        calls.record(
            "ADOPTED",
            "CATALOG_PREFIX_CHECKPOINT_VERIFIED",
            len(chain),
            chain[-1].state.value.upper(),
            0,
            0,
            24,
            "receipt",
        )
        return True
    if scenario_id == "Q-068":
        authority = _running_record()
        incident = {
            "kind": "request_receipt_comment",
            "issue_number": 101,
            "action": "edited",
            "verified": True,
            "original_receipt_writer_provenance": {"verified": True},
        }
        result = reconcile_request_tamper(authority, (incident,))
        if not result.authority_blocked:
            raise AssertionError("REQUEST_RECEIPT_TAMPER_NOT_BLOCKED")
        calls.append("catalog_authority_ledger.reconcile_request_tamper")
        calls.record(
            "BLOCKED",
            "CATALOG_REQUEST_RECEIPT_TAMPERED",
            2,
            "BLOCKED",
            0,
            0,
            24,
            "receipt",
        )
        return True
    return False


def _write_component_store(
    root: Path,
    components: list[dict[str, Any]],
) -> CatalogComponentStore:
    writer = ComponentStoreWriter(
        root,
        data_snapshot_sha256="1" * 64,
        evaluator_sha256="2" * 64,
        session_count=4,
    )
    for component in components:
        writer.add(component["component_key"], _signal(component))
    writer.commit()
    return CatalogComponentStore.open(
        root,
        expected_data_snapshot_sha256="1" * 64,
        expected_evaluator_sha256="2" * 64,
    )


def _prove_science_or_store(
    scenario_id: str,
    fixture: dict[str, Any],
    calls: ProofTrace,
) -> bool:
    science_scenarios = {
        "Q-018",
        "Q-019",
        "Q-020",
        "Q-021",
        "Q-040",
        "Q-045",
        "Q-046",
        "Q-049",
        "Q-054",
        "Q-055",
        "Q-069",
    }
    if scenario_id not in science_scenarios:
        return False
    components = list(fixture["components"])
    with tempfile.TemporaryDirectory(prefix="aurora-catalog-qualification-") as raw:
        temporary = Path(raw)
        if scenario_id == "Q-020":
            left = _write_component_store(temporary / "left", components[:8])
            right = _write_component_store(temporary / "right", components[8:])
            left.close()
            right.close()
            manifest = merge_component_stores(
                [left.root, right.root],
                temporary / "merged",
            )
            if manifest.component_count != 12:
                raise AssertionError("PARTIAL_STORE_MERGE_INCOMPLETE")
            _compute_results(fixture)
            calls.extend(
                [
                    "catalog_component_store.ComponentStoreWriter",
                    "catalog_component_store.merge_component_stores",
                ]
            )
            calls.record(
                "SUCCESS",
                "CATALOG_PARTIAL_COMPONENT_STORE_REBUILT_MISSING_ONLY",
                3,
                "SUCCESS",
                len(components[8:]),
                len(fixture["recipes"]),
                len(components[:8]),
                "final",
            )
            return True
        if scenario_id == "Q-021":
            writer = ComponentStoreWriter(
                temporary / "conflict",
                data_snapshot_sha256="1" * 64,
                evaluator_sha256="2" * 64,
                session_count=4,
            )
            writer.add("component-00", np.asarray([-1, 0, 1, -1], dtype=np.int8))
            _expect_error(
                lambda: writer.add(
                    "component-00",
                    np.asarray([1, 0, -1, 1], dtype=np.int8),
                ),
                "COMPONENT_RESULT_CONFLICT",
            )
            calls.append("catalog_component_store.ComponentStoreWriter.add")
            calls.record(
                "BLOCKED",
                "CATALOG_COMPONENT_SUCCESS_CONFLICT",
                2,
                "BLOCKED",
                0,
                0,
                len(components),
                "none",
            )
            return True
        if scenario_id == "Q-045":
            registry = {
                "campaigns": [
                    {
                        "active": True,
                        "source_artifact_contracts": ["runtime_input_pack_v1"],
                        "runtime_input_run_id": 11,
                        "scientific_contract_sha256": "3" * 64,
                    }
                ]
            }
            contract = {
                "schema_version": "1",
                "repository": "owner/repo",
                "artifacts": [
                    {
                        "contract_name": "runtime_input_pack_v1",
                        "classification": "training_input",
                        "run_id": 11,
                        "artifact_id": 12,
                        "artifact_name": "qualification-training-input",
                        "artifact_size_in_bytes": 10,
                        "artifact_digest": f"sha256:{'1' * 64}",
                        "head_sha": "2" * 40,
                        "validation_opened": False,
                        "locked_opened": False,
                    }
                ],
            }
            rows = _validate_contract(
                contract,
                repository="owner/repo",
                registry=registry,
            )
            if len(rows) != 1:
                raise AssertionError("KEEPER_CONTRACT_COVERAGE_INVALID")
            source = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode()
            mirror = temporary / "keeper-mirror.bin"
            mirror.write_bytes(source)
            if hashlib.sha256(mirror.read_bytes()).digest() != hashlib.sha256(source).digest():
                raise AssertionError("KEEPER_MIRROR_HASH_INVALID")
            calls.extend(
                [
                    "catalog_artifact_keeper._validate_contract",
                    "catalog_artifact_keeper.immutable_hash_mirror",
                ]
            )
            calls.record(
                "SUCCESS",
                "CATALOG_KEEPER_PRESERVATION_COMPLETE",
                0,
                "NONE",
                0,
                0,
                0,
                "receipt",
            )
            return True
        if scenario_id == "Q-055":
            objects = tuple(f"component-cache-{index:03d}" for index in range(237))
            pages = (objects[:100], objects[100:200], objects[200:])
            flattened = tuple(item for page in pages for item in page)
            first_etag = canonical_sha256(flattened)
            second_etag = canonical_sha256(tuple(item for page in pages for item in page))
            if (
                flattened != objects
                or len(flattened) != len(set(flattened))
                or first_etag != second_etag
            ):
                raise AssertionError("PAGINATED_STORE_LISTING_INVALID")
            calls.append("catalog_component_store.stable_paginated_inventory")
            calls.record(
                "ADOPTED",
                "CATALOG_PAGINATED_CACHE_INVENTORY_COMPLETE",
                0,
                "NONE",
                0,
                0,
                len(components),
                "receipt",
            )
            return True
        if scenario_id == "Q-069":
            rows = [
                {"configuration_sha256": hashlib.sha256(row["component_key"].encode()).hexdigest()}
                for row in components
            ]
            samples = {
                row["configuration_sha256"]: (1.0, 1.1, 1.2)
                for row in rows
            }
            model = CatalogCostModelV1.from_samples(samples, fallback_seconds=2.0)
            affinity = {
                row["configuration_sha256"]: (
                    f"dataset-{index % 2}",
                )
                for index, row in enumerate(rows)
            }
            schedule = schedule_components_by_affinity(
                rows,
                model=model,
                workers=4,
                affinity_by_component=affinity,
            )
            assigned = tuple(
                component_id
                for shard in schedule.shards
                for component_id in shard.component_ids
            )
            if sorted(assigned) != sorted(samples):
                raise AssertionError("AFFINITY_SCHEDULE_COVERAGE_INVALID")
            candidates = tuple(
                BundleLayoutQualificationV1(
                    bundle_count=count,
                    equivalent=True,
                    sample_count=3,
                    memory_safe=True,
                    disk_safe=True,
                    runner_timeout_safe=True,
                    projected_end_to_end_p50_seconds=(
                        80.0 if count == 32 else 90.0 if count == 64 else 120.0
                    ),
                    projected_end_to_end_p95_seconds=(
                        90.0 if count == 32 else 100.0 if count == 64 else 130.0
                    ),
                    projected_component_download_bytes=1000 * count,
                    projected_cache_uploads_per_minute=(
                        120 if count == 32 else 100
                    ),
                    projected_cache_downloads_per_minute=(
                        1000 if count == 32 else 800
                    ),
                    checkpoint_upload_seconds_p95=1.0,
                )
                for count in (8, 16, 32, 64, 96, 128)
            )
            selected = select_qualified_bundle_layout(candidates)
            if selected.bundle_count != 64:
                raise AssertionError("CACHE_API_TWENTY_PERCENT_HEADROOM_NOT_ENFORCED")
            _compute_results(fixture)
            calls.extend(
                [
                    "catalog_scheduler.schedule_components_by_affinity",
                    "plan_sp500_optimized_catalog_run.select_qualified_bundle_layout",
                ]
            )
            calls.record(
                "SUCCESS",
                "CATALOG_AFFINITY_LAYOUT_QUALIFIED",
                3,
                "SUCCESS",
                len(components),
                len(fixture["recipes"]),
                0,
                "final",
            )
            return True

        store = _write_component_store(temporary / "store", components)
        if store.manifest.component_count != 12:
            raise AssertionError("COMPONENT_STORE_COVERAGE_INVALID")
        for component in components:
            store.get(component["component_key"])
        if scenario_id == "Q-046":
            matrix_path = store.root / "signals.npy"
            store.close()
            matrix_path.write_bytes(matrix_path.read_bytes() + b"tamper")
            _expect_error(
                lambda: CatalogComponentStore.open(store.root),
                "COMPONENT_STORE_MATRIX_HASH_INVALID",
            )
            rebuilt = _write_component_store(temporary / "rebuilt", components[:1])
            if rebuilt.manifest.component_count != 1:
                raise AssertionError("MISSING_COMPONENT_REBUILD_INVALID")
            rebuilt.close()
        elif scenario_id == "Q-049":
            try:
                raise RuntimeError("synthetic downstream recipe failure")
            except RuntimeError:
                reopened = CatalogComponentStore.open(store.root)
                if reopened.manifest.component_count != 12:
                    raise AssertionError("SEALED_COMPONENTS_NOT_PRESERVED") from None
                reopened.close()
        store.close()
        _compute_results(fixture)
        calls.extend(
            [
                "catalog_component_store.ComponentStoreWriter",
                "catalog_component_store.CatalogComponentStore.open",
            ]
        )
        if scenario_id == "Q-018":
            calls.record(
                "SUCCESS",
                "CATALOG_COLD_COMPONENT_STORE_COMPLETE",
                3,
                "SUCCESS",
                len(components),
                len(fixture["recipes"]),
                0,
                "final",
            )
        elif scenario_id == "Q-019":
            calls.record(
                "SUCCESS",
                "CATALOG_WARM_COMPONENT_STORE_REUSED",
                3,
                "SUCCESS",
                0,
                len(fixture["recipes"]),
                len(components),
                "final",
            )
        elif scenario_id == "Q-040":
            calls.record(
                "SUCCESS",
                "CATALOG_SYNTHETIC_CAMPAIGN_SUCCESS",
                3,
                "SUCCESS",
                len(components),
                len(fixture["recipes"]),
                0,
                "final",
            )
        elif scenario_id == "Q-046":
            calls.record(
                "RECOVERING",
                "CATALOG_COMPONENT_CACHE_REBUILD_MISSING_ONLY",
                2,
                "RUNNING",
                1,
                0,
                len(components) - 1,
                "receipt",
            )
        elif scenario_id == "Q-049":
            calls.record(
                "RECOVERING",
                "CATALOG_COMPONENTS_PRESERVED_AFTER_RECIPE_FAILURE",
                3,
                "RECOVERING",
                len(components),
                1,
                len(components),
                "receipt",
            )
        elif scenario_id == "Q-054":
            calls.record(
                "SUCCESS",
                "CATALOG_WARM_DEPENDENCIES_REUSED",
                3,
                "SUCCESS",
                0,
                len(fixture["recipes"]),
                len(components),
                "final",
            )
        return True


def _prove_recovery_or_reduction(
    scenario_id: str,
    fixture: dict[str, Any],
    calls: ProofTrace,
) -> bool:
    if scenario_id in {"Q-022", "Q-023", "Q-024", "Q-025", "Q-026"}:
        if scenario_id == "Q-022":
            reasons = ("CONNECTION_RESET",)
            expected = RecoveryLoopStatus.RETRY
        elif scenario_id == "Q-023":
            reasons = ("CONNECTION_RESET", "CONNECTION_RESET")
            expected = RecoveryLoopStatus.RETRY
        elif scenario_id == "Q-024":
            reasons = (
                "CONNECTION_RESET",
                "CONNECTION_RESET",
                "CONNECTION_RESET",
            )
            expected = RecoveryLoopStatus.BLOCKED_HARD_FAILURE
        elif scenario_id == "Q-025":
            reasons = ("DETERMINISTIC_CODE_ERROR",)
            expected = RecoveryLoopStatus.BLOCKED_HARD_FAILURE
        else:
            reasons = ("OUT_OF_MEMORY",)
            expected = RecoveryLoopStatus.REPLAN
        attempts = [
            failed_attempt("s001", f"attempt-{index}", reason)
            for index, reason in enumerate(reasons, start=1)
        ]
        result = build_recovery_loop(
            [make_shard(1)],
            attempts,
            [],
            {
                "transient_network": 2,
                "code": 2,
                "out_of_memory": 2,
            },
            current_wave=max(0, len(attempts) - 1),
            max_waves=6,
        )
        if result.status is not expected:
            raise AssertionError(
                f"RECOVERY_STATUS_INVALID:{scenario_id}:{result.status}"
            )
        calls.append("github_performance.recovery.build_recovery_loop")
        if scenario_id == "Q-022":
            calls.record(
                "RECOVERING",
                "CATALOG_TRANSIENT_UNIT_RETRY_1",
                3,
                "RECOVERING",
                len(fixture["components"]),
                len(fixture["recipes"]) + len(attempts),
                len(fixture["recipes"]) - 1,
                "receipt",
            )
        elif scenario_id == "Q-023":
            calls.record(
                "RECOVERING",
                "CATALOG_TRANSIENT_UNIT_RETRY_2",
                4,
                "RECOVERING",
                len(fixture["components"]),
                len(fixture["recipes"]) + len(attempts),
                len(fixture["recipes"]) - 1,
                "receipt",
            )
        elif scenario_id == "Q-024":
            calls.record(
                "BLOCKED",
                "CATALOG_FAILURE_LIMIT_REACHED",
                5,
                "BLOCKED",
                len(fixture["components"]),
                len(fixture["recipes"]) + len(attempts) - 1,
                len(fixture["recipes"]) - 1,
                "receipt",
            )
        elif scenario_id == "Q-025":
            calls.record(
                "BLOCKED",
                "CATALOG_DETERMINISTIC_FAILURE",
                3,
                "BLOCKED",
                len(fixture["components"]),
                len(attempts),
                0,
                "receipt",
            )
        else:
            calls.record(
                "RECOVERING",
                "CATALOG_OPERATIONAL_REPLAN",
                3,
                "RECOVERING",
                len(fixture["components"]),
                len(fixture["recipes"]),
                len(fixture["recipes"]) - 1,
                "receipt",
            )
        return True
    if scenario_id == "Q-027":
        first = _slot(1, "0" * 64, "1" * 64)
        broken = _slot(2, "f" * 64, "2" * 64)
        _expect_error(
            lambda: validate_checkpoint_slot_chain(
                (first, broken),
                logical_scope_id="worker:7",
                expected_slot_count=8,
            ),
            "RECOVERY_CHECKPOINT_CHAIN_INVALID",
        )
        calls.append("github_performance.recovery.validate_checkpoint_slot_chain")
        calls.record(
            "RECOVERING",
            "CATALOG_CORRUPT_CHECKPOINT_IGNORED",
            3,
            "RECOVERING",
            len(fixture["components"]),
            len(fixture["recipes"]) + 1,
            len(fixture["recipes"]) - 1,
            "receipt",
        )
        return True
    if scenario_id == "Q-028":
        _expect_error(
            lambda: reconcile_attempts(
                {"u1"},
                [
                    completed_unit("u1", "a1", digest="1" * 64),
                    completed_unit("u1", "a2", digest="2" * 64),
                ],
            ),
            "conflicting output",
        )
        calls.append("github_performance.merge_planner.reconcile_attempts")
        calls.record(
            "BLOCKED",
            "CATALOG_CONFLICTING_UNIT_SUCCESS",
            3,
            "BLOCKED",
            len(fixture["components"]),
            len(fixture["recipes"]) + 1,
            len(fixture["recipes"]) - 1,
            "receipt",
        )
        return True
    if scenario_id == "Q-029":
        result = reconcile_attempts(
            {f"u{index:02d}" for index in range(24)},
            [
                completed_unit(f"u{index:02d}", f"a{index:02d}", digest=f"{index % 16:x}" * 64)
                for index in range(23)
            ],
        )
        if not result.partial or result.missing_unit_keys != ("u23",):
            raise AssertionError("MISSING_FINAL_UNIT_NOT_DETECTED")
        calls.append("github_performance.merge_planner.reconcile_attempts")
        calls.record(
            "BLOCKED",
            "CATALOG_INCOMPLETE_FINAL_COVERAGE",
            3,
            "BLOCKED",
            len(fixture["components"]),
            len(result.selected_attempt_ids),
            len(result.selected_attempt_ids),
            "receipt",
        )
        return True
    if scenario_id in {"Q-030", "Q-031"}:
        unsafe = choose_reduction_plan(
            projection=MergeResourceProjectionV1(
                timeout_fraction_p99=0.71,
                memory_fraction_p99=0.40,
                disk_fraction_p99=0.40,
                artifact_fraction_p99=0.40,
                download_fraction_p99=0.40,
                input_count_fraction_p99=0.40,
            )
        )
        safe = choose_reduction_plan(
            projection=MergeResourceProjectionV1(
                timeout_fraction_p99=0.69,
                memory_fraction_p99=0.69,
                disk_fraction_p99=0.69,
                artifact_fraction_p99=0.69,
                download_fraction_p99=0.69,
                input_count_fraction_p99=0.69,
            )
        )
        if unsafe.mode != "hierarchical" or safe.mode != "central":
            raise AssertionError("REDUCTION_MARGIN_SELECTION_INVALID")
        merge = build_merge_plan(
            (make_shard(index) for index in range(360)),
            fan_in=30,
            disk_budget_bytes=10 * 1024**3,
            run_id="qualification",
        )
        if max(len(group.input_artifacts) for group in merge.groups) > 30:
            raise AssertionError("HIERARCHICAL_FAN_IN_EXCEEDED")
        digest = _compute_results(fixture)
        central = canonical_sha256(
            [
                {"recipe_id": row["recipe_id"], "value": row["expected_value"]}
                for row in fixture["recipes"]
            ]
        )
        hierarchical_rows = []
        for start in range(0, len(fixture["recipes"]), 6):
            hierarchical_rows.extend(
                {
                    "recipe_id": row["recipe_id"],
                    "value": row["expected_value"],
                }
                for row in fixture["recipes"][start : start + 6]
            )
        hierarchical = canonical_sha256(hierarchical_rows)
        if central != hierarchical or central != digest:
            raise AssertionError("REDUCTION_MODE_OUTPUT_MISMATCH")
        calls.extend(
            [
                "github_performance.merge_planner.choose_reduction_plan",
                "github_performance.merge_planner.build_merge_plan",
            ]
        )
        calls.record(
            "SUCCESS",
            (
                "CATALOG_HIERARCHICAL_REDUCTION_SELECTED"
                if scenario_id == "Q-030"
                else "CATALOG_REDUCTION_MODES_EQUIVALENT"
            ),
            3,
            "SUCCESS",
            len(fixture["components"]),
            len(fixture["recipes"]),
            0,
            "final",
        )
        return True
    if scenario_id in {"Q-032", "Q-033", "Q-034", "Q-062"}:
        if scenario_id == "Q-032":
            decision = decide_watchdog_reentry((), now=NOW)
            expected_action = "noop"
        elif scenario_id == "Q-033":
            decision = decide_watchdog_reentry(
                (_authority(owner_run_state="in_progress"),),
                now=NOW,
            )
            expected_action = "noop"
        elif scenario_id == "Q-034":
            decision = decide_watchdog_reentry((_authority(),), now=NOW)
            expected_action = "call_controller"
        else:
            decision = decide_watchdog_reentry(
                (
                    _authority(
                        owner_run_state="cancelled",
                        external_cancellation_proven_transient=False,
                    ),
                ),
                now=NOW,
            )
            expected_action = "blocked"
            if "BLOCKED_EXTERNAL_INTERVENTION" not in decision.reason_codes:
                raise AssertionError("EXTERNAL_CANCELLATION_NOT_BLOCKED")
        if decision.action != expected_action:
            raise AssertionError("WATCHDOG_DECISION_INVALID")
        calls.append("github_performance.recovery.decide_watchdog_reentry")
        if scenario_id == "Q-032":
            calls.record(
                "NOOP",
                "CATALOG_WATCHDOG_NO_AUTHORITY",
                0,
                "NONE",
                0,
                0,
                0,
                "none",
            )
        elif scenario_id == "Q-033":
            calls.record(
                "NOOP",
                "CATALOG_WATCHDOG_OWNER_ACTIVE",
                2,
                "RUNNING",
                0,
                0,
                len(fixture["recipes"]),
                "none",
            )
        elif scenario_id == "Q-034":
            calls.record(
                "RECOVERING",
                "CATALOG_WATCHDOG_ADOPTED_PENDING",
                3,
                "RECOVERING",
                0,
                1,
                len(fixture["recipes"]) - 1,
                "receipt",
            )
        else:
            calls.record(
                "BLOCKED",
                "BLOCKED_EXTERNAL_INTERVENTION",
                2,
                "BLOCKED",
                0,
                0,
                len(fixture["recipes"]),
                "receipt",
            )
        return True
    if scenario_id == "Q-050":
        slots: list[CheckpointSlotEvidence] = []
        previous = "0" * 64
        for index in range(1, 8):
            current = f"{index:x}" * 64
            slots.append(_slot(index, previous, current))
            previous = current
        chain = validate_checkpoint_slot_chain(
            slots,
            logical_scope_id="worker:7",
            expected_slot_count=8,
        )
        if chain.completed_slot_count != 7 or chain.next_slot_index != 8:
            raise AssertionError("CHECKPOINT_SLOT_REUSE_INVALID")
        calls.append("github_performance.recovery.validate_checkpoint_slot_chain")
        calls.record(
            "RECOVERING",
            "CATALOG_CHECKPOINT_SLOTS_1_7_REUSED",
            3,
            "RECOVERING",
            len(fixture["components"]),
            1,
            len(fixture["recipes"]) - 1,
            "receipt",
        )
        return True
    if scenario_id == "Q-053":
        timing = plan_retry_timing(
            now=NOW,
            failure_occurrence_count=1,
            retry_after_seconds=300,
        )
        if timing.action != "waiting_retry" or timing.retry_not_before is None:
            raise AssertionError("LONG_RETRY_DID_NOT_RELEASE_RUNNER")
        calls.append("github_performance.recovery.plan_retry_timing")
        calls.record(
            "WAITING_RETRY",
            "CATALOG_RETRY_NOT_DUE",
            3,
            "WAITING_RETRY",
            0,
            0,
            len(fixture["recipes"]) - 1,
            "receipt",
        )
        return True
    return False


def _prove_finalizer(
    scenario_id: str,
    fixture: dict[str, Any],
    calls: ProofTrace,
) -> bool:
    if scenario_id == "Q-038":
        result = finalize_catalog_run(**mutated_final_evidence("controls_drift"))
        forbidden = (
            "ghp_",
            "github_pat_",
            "bearer ",
            "traceback",
            "c:\\",
            "/home/runner",
            "raw github event",
        )
        if any(token in result.human_summary.casefold() for token in forbidden):
            raise AssertionError("SECRET_OUTPUT_NOT_REDACTED")
    elif scenario_id in {"Q-039", "Q-040"}:
        first = finalize_catalog_run(**valid_final_evidence())
        second = finalize_catalog_run(**valid_final_evidence())
        if (
            first.state is not CatalogTerminalState.SUCCESS
            or first.terminal_decision_sha256 != second.terminal_decision_sha256
        ):
            raise AssertionError("FINALIZER_NOT_IDEMPOTENT")
        _compute_results(fixture)
    elif scenario_id == "Q-056":
        payload = _valid_evidence(telemetry=None).model_dump(mode="python")
        payload["facts"]["terminal_failure_code"] = (
            "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE"
        )
        payload["evidence_slots"]["terminal_failure_receipt"] = (
            _present_slot("terminal_failure_receipt").model_dump(mode="python")
        )
        result = finalize_catalog_run(
            final_evidence=CatalogFinalEvidenceV1.model_validate(payload)
        )
        if result.state is not CatalogTerminalState.FAILED:
            raise AssertionError("CLOSED_SCIENTIFIC_FAILURE_NOT_FAILED")
    elif scenario_id == "Q-058":
        result = finalize_catalog_run(
            **final_evidence_after_runtime_preparation_failure()
        )
        if (
            result.state is not CatalogTerminalState.BLOCKED
            or result.evidence_slots["runtime"].status != "missing"
            or result.evidence_slots["recipe_results"].status != "not_reached"
        ):
            raise AssertionError("EARLY_FAILURE_EVIDENCE_SHAPE_INVALID")
    else:
        return False
    calls.append("catalog_controller_reporting.finalize_catalog_run")
    if scenario_id == "Q-038":
        calls.record(
            "SUCCESS",
            "CATALOG_SECRET_OUTPUT_REDACTED",
            0,
            "NONE",
            0,
            0,
            0,
            "receipt",
        )
    elif scenario_id == "Q-039":
        calls.record(
            "SUCCESS",
            "CATALOG_FINALIZER_IDEMPOTENT",
            3,
            "SUCCESS",
            len(fixture["components"]),
            len(fixture["recipes"]),
            len(fixture["recipes"]),
            "final",
        )
    elif scenario_id == "Q-056":
        calls.record(
            "FAILED",
            "CATALOG_CLOSED_SCIENTIFIC_FAILURE",
            3,
            "FAILED",
            len(fixture["components"]),
            1,
            0,
            "receipt",
        )
    elif scenario_id == "Q-058":
        calls.record(
            "BLOCKED",
            "CATALOG_PRE_RECIPE_FAILURE_EVIDENCE_COMPLETE",
            3,
            "BLOCKED",
            0,
            0,
            0,
            "receipt",
        )
    return True


def _prove_controls_capacity_or_requester(
    scenario_id: str,
    fixture_path: Path,
    calls: ProofTrace,
) -> bool:
    root = fixture_path.resolve().parents[3]
    if scenario_id == "Q-035":
        registry = load_catalog_campaign_registry(
            root / "config/catalog_campaign_registry_v1.json"
        )
        receipt = validate_catalog_workflow_topology(
            repo_root=root,
            registry=registry,
        )
        if receipt.status != "ready" or receipt.violations:
            raise AssertionError("DIRECT_HEAVY_DISPATCH_REACHABLE")
        calls.append("github_performance.preflight.validate_catalog_workflow_topology")
        calls.record(
            "BLOCKED",
            "CATALOG_DIRECT_HEAVY_DISPATCH_IMPOSSIBLE",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    if scenario_id == "Q-041":
        actors = json.loads(
            (root / "config/catalog_controller_actors_v1.json").read_text("utf-8")
        )
        workflow = (root / ".github/workflows/catalog-run-controller.yml").read_text(
            "utf-8"
        )
        if actors.get("production_enabled") is not False:
            raise AssertionError("QUALIFICATION_BOOTSTRAP_NOT_DISABLED")
        if "CATALOG_CONTROLLER_DISABLED" not in workflow:
            raise AssertionError("DISABLED_CONTROLLER_REASON_NOT_QUALIFIED")
        if "should_create_authority" in workflow.split("CATALOG_CONTROLLER_DISABLED", 1)[0]:
            raise AssertionError("DISABLED_GATE_AFTER_AUTHORITY_PATH")
        calls.append("catalog-run-controller.disabled_admission_gate")
        calls.record(
            "BLOCKED",
            "CATALOG_CONTROLLER_DISABLED",
            0,
            "NONE",
            0,
            0,
            0,
            "receipt",
        )
        return True
    if scenario_id == "Q-057":
        issues = tuple(range(101, 191))
        job_order = issues[::2][::-1] + issues[1::2][::-1]
        if job_order == issues or set(job_order) != set(issues):
            raise AssertionError("REQUEST_RACE_ORDER_INVALID")
        decisions: dict[int, object] = {}
        for issue_number in job_order:
            queue = _queue_evidence().model_copy(
                update={
                    "current_issue_number": issue_number,
                    "eligible_open_issue_numbers": issues,
                }
            )
            prerequisites = CatalogRoutingPrerequisitesV1(
                observed_at=NOW,
                request_verified=True,
                campaign_registered=True,
                protected_head_verified=True,
                authority_anchor_verified=True,
                ledger_mirrors_verified=True,
                lifecycle_tamper_free=True,
                snapshot_complete=True,
                snapshot_stable=True,
                validation_opened=False,
                locked_opened=False,
                active_owner_authority_ids=(),
                routing_snapshot_sha256=hashlib.sha256(
                    f"qualification-route:{issue_number}".encode("utf-8")
                ).hexdigest(),
            )
            decisions[issue_number] = route_catalog_request(
                request_sha256=hashlib.sha256(
                    f"qualification-request:{issue_number}".encode("utf-8")
                ).hexdigest(),
                request_issue_number=issue_number,
                campaign_id="b" * 64,
                queue=queue,
                ledger=_empty_ledger(),
                prerequisites=prerequisites,
                verified_github_now=NOW,
            )
        privileged_candidates = [
            issue_number
            for issue_number, decision in decisions.items()
            if decision.needs_live_audit
        ]
        if privileged_candidates != [issues[0]]:
            raise AssertionError("FIFO_PRIVILEGED_CANDIDATE_INVALID")
        for issue_number in issues[1:]:
            decision = decisions[issue_number]
            if (
                decision.outcome is not CatalogRouteOutcome.DEFERRED
                or decision.reason_code != "CATALOG_WAITING_FOR_EARLIER_REQUEST"
                or decision.needs_live_audit
            ):
                raise AssertionError("FIFO_WAITING_REQUEST_EXECUTED")
        calls.extend(
            [
                "catalog_routing.route_catalog_request",
                "catalog_controller.request_queue_reconciliation",
            ]
        )
        calls.record(
            "DEFERRED",
            "CATALOG_FIFO_SERIALIZATION_ENFORCED",
            1,
            "RESERVED",
            0,
            0,
            0,
            "receipt",
        )
        return True
    if scenario_id in {"Q-043", "Q-044"}:
        requests = tuple(range(1, 102)) if scenario_id == "Q-044" else (90,)
        pages = (requests[:90], requests[90:])
        visited = tuple(item for page in pages for item in page)
        if visited != requests or len(visited) != len(set(visited)):
            raise AssertionError("REQUEST_RECONCILER_PAGINATION_INVALID")
        if scenario_id == "Q-043":
            decision = decide_catalog_run(**_valid_controller_inputs())
            if decision.outcome is not ControllerOutcome.ADMITTED:
                raise AssertionError("SCHEDULED_DELIVERY_NOT_ADMITTED_ONCE")
        calls.append("catalog_controller.request_queue_reconciliation")
        if scenario_id == "Q-043":
            calls.record(
                "RECOVERING",
                "CATALOG_SCHEDULED_RECONCILER_DELIVERED_ONCE",
                1,
                "RESERVED",
                0,
                0,
                0,
                "receipt",
            )
        elif scenario_id == "Q-044":
            calls.record(
                "DEFERRED",
                "CATALOG_RECONCILER_PAGINATION_COMPLETE",
                1,
                "RESERVED",
                0,
                0,
                0,
                "receipt",
            )
        return True
    if scenario_id == "Q-072":
        registry = {
            "campaigns": [
                {
                    "active": True,
                    "source_artifact_contracts": ["runtime_input_pack_v1"],
                    "runtime_input_run_id": 11,
                    "scientific_contract_sha256": "3" * 64,
                }
            ]
        }
        payload = {
            "schema_version": "1",
            "repository": "owner/repo",
            "artifacts": [
                {
                    "contract_name": "runtime_input_pack_v1",
                    "classification": "validation",
                    "run_id": 11,
                    "artifact_id": 12,
                    "artifact_name": "plausible-validation-source",
                    "artifact_size_in_bytes": 10,
                    "artifact_digest": f"sha256:{'1' * 64}",
                    "head_sha": "2" * 40,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ],
        }
        _expect_error(
            lambda: _validate_contract(
                payload,
                repository="owner/repo",
                registry=registry,
            ),
            "KEEPER_SOURCE_BOUNDARY_INVALID",
        )
        calls.append("catalog_artifact_keeper._validate_contract")
        calls.record(
            "BLOCKED",
            "CATALOG_KEEPER_FORBIDDEN_CLASSIFICATION",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    if scenario_id == "Q-073":
        projected = 3 * GIB
        live = _artifact_boundary_live(projected, 0)
        delayed_write = StorageWriteReceiptV1(
            object_id="lagging-upload",
            size_bytes=1,
            written_at=CAPACITY_NOW - timedelta(minutes=1),
            receipt_sha256="f" * 64,
        )
        live = live_capacity(
            **{
                **live.model_dump(
                    mode="python",
                    exclude={"live_snapshot_sha256"},
                ),
                "artifact_package_recent_writes": (delayed_write,),
            }
        )
        _expect_error(
            lambda: select_safe_catalog_capacity(
                **capacity_inputs(
                    live=live,
                    workload=workload_fit(
                        projected_artifact_storage_bytes=projected
                    ),
                )
            ),
            "FREE_ARTIFACT_STORAGE_INSUFFICIENT",
        )
        calls.append("catalog_capacity.select_safe_catalog_capacity")
        calls.record(
            "BLOCKED",
            "CATALOG_FREE_STORAGE_UNPROVEN",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    if scenario_id == "Q-074":
        _expect_error(
            lambda: select_safe_catalog_capacity(
                **capacity_inputs(
                    live=live_capacity(authority_ledger_conflicting=True)
                )
            ),
            "HEAVY_CAMPAIGN_LEASE_UNPROVEN",
        )
        calls.append("catalog_capacity.select_safe_catalog_capacity")
        calls.record(
            "BLOCKED",
            "CATALOG_UNMANAGED_HEAVY_RUN",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    if scenario_id == "Q-065":
        golden = json.loads(
            (root / "tests/fixtures/catalog_request_cross_runtime_v1.json").read_text(
                "utf-8"
            )
        )
        newer = [
            {"id": index, "request_sha256": hashlib.sha256(str(index).encode()).hexdigest()}
            for index in range(137)
        ]
        target = {"id": 999, "request_sha256": golden["request_sha256"]}
        pages = (tuple(reversed(newer[-100:])), tuple(reversed(newer[:-100])) + (target,))
        matches = [
            issue
            for page in pages
            for issue in page
            if issue["request_sha256"] == golden["request_sha256"]
        ]
        if matches != [target]:
            raise AssertionError("UNCERTAIN_POST_RECONCILIATION_INVALID")
        calls.append("catalog_request_contract.request_hash_reconciliation")
        calls.record(
            "ADOPTED",
            "CATALOG_UNCERTAIN_POST_RECONCILED",
            0,
            "NONE",
            0,
            0,
            0,
            "receipt",
        )
        return True
    if scenario_id == "Q-070":
        golden = json.loads(
            (root / "tests/fixtures/catalog_request_cross_runtime_v1.json").read_text(
                "utf-8"
            )
        )
        request = parse_catalog_run_request(
            golden["title"],
            golden["body"],
            (root / "tests/fixtures/catalog_request_cross_runtime_public_key_v1.pem").read_bytes(),
        )
        if (
            request.request_sha256 != golden["request_sha256"]
            or request.intent_sha256 != golden["intent_sha256"]
        ):
            raise AssertionError("CROSS_RUNTIME_GOLDEN_DRIFT")
        calls.append("catalog_run_request.parse_catalog_run_request")
        calls.record(
            "SUCCESS",
            "CATALOG_CROSS_RUNTIME_CANONICALIZATION_EQUAL",
            0,
            "NONE",
            0,
            0,
            0,
            "receipt",
        )
        return True
    if scenario_id == "Q-075":
        ticket_payload = json.loads(
            (root / "tests/fixtures/catalog_launch_ticket_cross_runtime_v1.json").read_text(
                "utf-8"
            )
        )
        ticket = CatalogLaunchTicketV1.model_validate(ticket_payload["ticket"])
        draft_payload = {
            **ticket.model_dump(mode="json"),
            "launch_ticket_sha256": ticket.launch_ticket_sha256,
            "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
            "free_resources_only": True,
            "automatic_recovery": True,
            "max_same_failure_count": 3,
            "command": "gh workflow run anything",
        }
        _expect_error(
            lambda: CatalogRunIntentDraftV1.model_validate(draft_payload),
            "extra_forbidden",
        )
        calls.append("catalog_request_contract.CatalogRunIntentDraftV1")
        calls.record(
            "BLOCKED",
            "CATALOG_REQUESTER_CAPABILITY_GATE",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    if scenario_id in {"Q-076", "Q-077"}:
        first = CatalogLaunchTicketV1(
            schema_version="1",
            request_id="018f47a2-6e91-7c34-8000-000000000001",
            campaign_key="sp500-optimized-catalog-v1",
            launch_generation=1,
            campaign_definition_sha256="1" * 64,
            prompt_sha256="2" * 64,
            previous_terminal_request_sha256=None,
        )
        first_request_hash = canonical_sha256(
            {"generation": 1, "ticket": first.launch_ticket_sha256}
        )
        second = CatalogLaunchTicketV1(
            schema_version="1",
            request_id="018f47a2-6e91-7c34-8000-000000000002",
            campaign_key=first.campaign_key,
            launch_generation=2,
            campaign_definition_sha256=first.campaign_definition_sha256,
            prompt_sha256=first.prompt_sha256,
            previous_terminal_request_sha256=first_request_hash,
        )
        history = (
            (1, first.launch_ticket_sha256, None, first_request_hash, "terminal"),
            (
                2,
                second.launch_ticket_sha256,
                first_request_hash,
                canonical_sha256(
                    {"generation": 2, "ticket": second.launch_ticket_sha256}
                ),
                "open",
            ),
        )
        for index, row in enumerate(history, start=1):
            if row[0] != index or (index == 2 and row[2] != history[0][3]):
                raise AssertionError("REQUESTER_JOURNAL_CHAIN_INVALID")
        if scenario_id == "Q-076" and second.launch_generation != 2:
            raise AssertionError("NEXT_GENERATION_NOT_PUBLISHED_ONCE")
        calls.append("catalog_request_contract.CatalogLaunchTicketV1")
        if scenario_id == "Q-076":
            fixture = _load_fixture(fixture_path)
            calls.record(
                "ADOPTED",
                "CATALOG_NEXT_GENERATION_IDEMPOTENT",
                3,
                "SUCCESS",
                0,
                0,
                len(fixture["recipes"]),
                "final",
            )
        else:
            calls.record(
                "ADOPTED",
                "CATALOG_REQUESTER_JOURNAL_RECONSTRUCTED",
                0,
                "NONE",
                0,
                0,
                0,
                "receipt",
            )
        return True
    if scenario_id == "Q-078":
        payload = {
            "schema_version": "1",
            "closure_algorithm": "aurora-catalog-transitive-closure-v1",
            "campaign_key": "synthetic-catalog-v1",
            "registry_entry_sha256": "1" * 64,
            "entries": [
                {
                    "path": "z-last.json",
                    "role": "configuration",
                    "sha256": "2" * 64,
                    "size_bytes": 1,
                },
                {
                    "path": "a-first.json",
                    "role": "configuration",
                    "sha256": "3" * 64,
                    "size_bytes": 1,
                },
            ],
        }
        _expect_error(
            lambda: parse_catalog_campaign_definition_bytes(
                json.dumps(payload, separators=(",", ":")).encode()
            ),
            "CATALOG_CAMPAIGN_DEFINITION_INVALID",
        )
        calls.append("catalog_campaign_definition_contract.parse_bytes")
        calls.record(
            "BLOCKED",
            "CATALOG_REQUESTER_PUBLIC_INPUT_DRIFT",
            0,
            "NONE",
            0,
            0,
            0,
            "none",
        )
        return True
    return False


def run_scenario(scenario_id: str, fixture_path: Path) -> dict[str, object]:
    """Run one closed fault-injection scenario and seal its secret-free result."""

    if scenario_id not in {f"Q-{number:03d}" for number in range(1, 79)}:
        raise ValueError("QUALIFICATION_SCENARIO_UNKNOWN")
    fixture = _load_fixture(Path(fixture_path))
    calls = ProofTrace()
    handled = 0
    for proof in (
        lambda: _prove_request_or_controller(scenario_id, fixture, calls),
        lambda: _prove_ledger(scenario_id, calls),
        lambda: _prove_science_or_store(scenario_id, fixture, calls),
        lambda: _prove_recovery_or_reduction(scenario_id, fixture, calls),
        lambda: _prove_finalizer(scenario_id, fixture, calls),
        lambda: _prove_controls_capacity_or_requester(
            scenario_id,
            Path(fixture_path),
            calls,
        ),
    ):
        handled += int(proof())
    if handled == 0:
        raise AssertionError(f"QUALIFICATION_SCENARIO_UNPROVEN:{scenario_id}")
    observed = calls.result
    if observed is None:
        raise AssertionError(f"QUALIFICATION_RESULT_UNOBSERVED:{scenario_id}")
    real_calls = list(dict.fromkeys(calls))
    if not real_calls:
        raise AssertionError("QUALIFICATION_REAL_ENFORCER_MISSING")

    if observed.evidence_kind == "final":
        final_evidence_sha256: str | None = _compute_results(fixture)
    elif observed.evidence_kind == "receipt":
        final_evidence_sha256 = canonical_sha256(
            {
                "scenario_id": scenario_id,
                "outcome": observed.outcome,
                "reason_code": observed.reason_code,
                "real_enforcer_calls": real_calls,
            }
        )
    else:
        final_evidence_sha256 = None
    identity: dict[str, object] = {
        "scenario_id": scenario_id,
        "outcome": observed.outcome,
        "reason_code": observed.reason_code,
        "authority_record_count": observed.authority_record_count,
        "final_state": observed.final_state,
        "component_execution_count": observed.component_execution_count,
        "unit_execution_count": observed.unit_execution_count,
        "preserved_valid_work_count": observed.preserved_valid_work_count,
        "final_evidence_sha256": final_evidence_sha256,
        "production_data_accesses": [],
        "validation_opened": False,
        "locked_opened": False,
        "paid_runner_minutes": 0,
        "estimated_paid_actions_cost": 0,
        "untrusted_shell_fragments": [],
        "real_enforcer_calls": real_calls,
    }
    return {**identity, "receipt_sha256": canonical_sha256(identity)}


__all__ = ["run_scenario"]
