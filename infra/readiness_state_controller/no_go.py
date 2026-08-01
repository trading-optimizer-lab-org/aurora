"""Fail-closed GTBI V7 terminal no-go receipt generation."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

NO_GO_CLOSE_ID_RE = re.compile(r"^NO_GO_CLOSE-[1-9][0-9]*$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
READINESS_RELATIVE = Path("docs/readiness/gtbi-v7")


class NoGoClosureError(ValueError):
    """Raised when terminal no-go closure cannot be proved safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NoGoClosureError(message)


def _canonical_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing evidence: {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"evidence is not an object: {path.name}")
    _require(
        path.read_bytes() == canonical_bytes(payload) + b"\n",
        f"evidence is not canonical: {path.name}",
    )
    return payload


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NoGoClosureError("closed_at_utc is invalid") from exc
    _require(parsed.tzinfo is not None, "closed_at_utc must include a timezone")


def _digest_file_set(root: Path, names: list[str], domain: str) -> tuple[str, list[dict[str, str]]]:
    entries = []
    for name in names:
        path = root / READINESS_RELATIVE / name
        _canonical_json(path)
        entries.append(
            {
                "path": (READINESS_RELATIVE / name).as_posix(),
                "sha256": raw_sha256(path),
            }
        )
    return domain_digest(domain, entries), entries


def validate_no_go_prerequisites(repository_root: Path, base_sha: str) -> dict[str, Any]:
    """Validate the exact safe-closure predicates without mutating state."""

    root = repository_root.resolve()
    _require(bool(COMMIT_SHA_RE.fullmatch(base_sha)), "invalid evaluated commit SHA")
    current = validate_current_readiness_records(root)
    readiness = root / READINESS_RELATIVE
    tasks = {row["id"]: row for row in _csv_rows(readiness / "task_status.csv")}
    gates = {row["gate_id"]: row for row in _csv_rows(readiness / "gate_status.csv")}

    _require(tasks["PREV7-0000"]["status"] == "done", "PREV7-0000 is not done")
    _require(gates["G0"]["status"] == "green", "G0 is not green")
    _require(tasks["PREV7-0307"]["status"] == "done", "PREV7-0307 is not done")

    trigger = _canonical_json(readiness / "g2_v6_input_identity_decision_receipt.json")
    _require(
        trigger["decision"] == "no_authenticated_v6_input_identity",
        "hard no-go trigger decision mismatch",
    )
    _require(trigger["no_go_close_required"] is True, "no-go closure is not required")
    _require(trigger["current_v7_baseline_authorized"] is False, "V7 baseline is authorized")
    boundaries = trigger["scientific_boundaries"]
    _require(boundaries["locked_start"] == "2021-01-01", "locked boundary changed")
    for key in (
        "locked_data_accessed",
        "provider_download_performed",
        "scientific_processing_performed",
        "strategy_evaluation_performed",
    ):
        _require(boundaries[key] is False, f"scientific boundary violated: {key}")

    attempt_rows = _jsonl_rows(readiness / "task_attempts.jsonl")
    scientific_attempts = [
        row
        for row in attempt_rows
        if str(row["task_id"]).startswith(("PREV7-07", "PREV7-08"))
    ]
    _require(not scientific_attempts, "a G7 or full scientific attempt exists")
    for gate_id in ("G7", "G8", "G9", "G9X", "G10"):
        _require(gates[gate_id]["status"] == "red", f"{gate_id} is not red")

    owner = _canonical_json(readiness / "owner_decisions.json")
    budget = owner["decisions"]["budget"]
    _require(budget["maximum_incremental_net_spend_usd"] == 0, "budget permits spend")
    _require(budget["current_actions_net_amount_usd"] == 0, "Actions net cost is nonzero")

    envelope = _canonical_json(readiness / "g2_github_actions_envelope_receipt.json")
    billing = envelope["billing_envelope"]
    _require(billing["maximum_incremental_net_spend_usd"] == 0, "Actions envelope permits spend")
    _require(billing["new_billable_resources_authorized"] is False, "billable resources authorized")
    _require(envelope["capacity_topology"]["local_machine_allowed"] is False, "local execution allowed")
    _require(envelope["scientific_boundaries"]["locked_data_accessed"] is False, "locked accessed")

    preservation = _canonical_json(readiness / "v6_preservation_lease_public_receipt.json")
    _require(preservation["status"] == "verified", "V6 preservation lease is not verified")
    _require(preservation["locked_or_scientific_processing_performed"] is False, "preservation crossed boundary")
    locked = _canonical_json(readiness / "locked_evidence_preservation_report.json")
    _require(locked["locked_data_opened_during_preservation"] is False, "locked opened during preservation")
    _require(locked["locked_data_opened_during_verification"] is False, "locked opened during verification")

    return {
        "current_counts": current,
        "trigger": trigger,
        "owner": owner,
        "envelope": envelope,
        "preservation": preservation,
        "locked": locked,
        "scientific_attempt_count": 0,
    }


def _event(
    *,
    close_id: str,
    sequence: int,
    state: str,
    timestamp: str,
    previous_digest: str | None,
    base_sha: str,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": "gtbi_v7_no_go_close_event_v1",
        "event_id": f"{close_id}-{sequence:04d}",
        "no_go_close_id": close_id,
        "sequence": sequence,
        "state": state,
        "recorded_at_utc": timestamp,
        "evaluated_commit_sha": base_sha,
        "previous_event_digest_or_null": previous_digest,
        "event_digest": "",
    }
    event["event_digest"] = domain_digest(
        "GTBI_V7_NO_GO_CLOSE_EVENT_V1",
        event,
        omit_top_level_fields=("event_digest",),
    )
    return event


def build_no_go_receipt(
    repository_root: Path,
    *,
    base_sha: str,
    close_id: str,
    closed_at_utc: str,
    run_id: int,
    run_url: str,
) -> dict[str, Any]:
    """Build the exact immutable NO_GO_CLOSED controller receipt."""

    _require(bool(NO_GO_CLOSE_ID_RE.fullmatch(close_id)), "invalid no-go close id")
    _require(run_id > 0, "run id must be positive")
    _require(run_url == f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run_id}", "run URL mismatch")
    _validate_timestamp(closed_at_utc)
    root = repository_root.resolve()
    validated = validate_no_go_prerequisites(root, base_sha)
    readiness = root / READINESS_RELATIVE

    task_and_gate_entries = [
        {
            "path": (READINESS_RELATIVE / name).as_posix(),
            "sha256": raw_sha256(readiness / name),
        }
        for name in (
            "task_status.csv",
            "task_events.jsonl",
            "task_attempts.jsonl",
            "gate_status.csv",
            "gate_events.jsonl",
        )
    ]
    task_and_gate_head_digest = domain_digest(
        "GTBI_V7_NO_GO_TASK_AND_GATE_HEAD_V1", task_and_gate_entries
    )

    retention_digest, retention_entries = _digest_file_set(
        root,
        [
            "v6_preservation_lease_public_receipt.json",
            "locked_evidence_preservation_report.json",
            "g2_retention_policy_receipt.json",
        ],
        "GTBI_V7_NO_GO_RETAINED_EVIDENCE_MANIFEST_V1",
    )
    cleanup_digest, cleanup_entries = _digest_file_set(
        root,
        ["legacy_run_cleanup_receipt.json"],
        "GTBI_V7_NO_GO_CLEANUP_RECEIPT_SET_V1",
    )
    billing_digest, billing_entries = _digest_file_set(
        root,
        [
            "billing_baseline_public_receipt.json",
            "g2_github_actions_envelope_receipt.json",
            "owner_decisions.json",
        ],
        "GTBI_V7_NO_GO_BILLING_DOMAIN_MANIFEST_V1",
    )
    resource_inventory = {
        "temporary_cloud_resources_created": 0,
        "self_hosted_runners_created": 0,
        "billable_resources_created": 0,
        "v7_g7_or_full_scientific_runs_dispatched": 0,
        "retained_evidence_entries": retention_entries,
        "github_repository_retained_as_canonical_evidence": True,
        "controller_artifact_retained_under_approved_evidence_policy": True,
    }
    resource_inventory_digest = domain_digest(
        "GTBI_V7_NO_GO_RESOURCE_INVENTORY_V1", resource_inventory
    )
    teardown_manifest = {
        "required_teardown_actions": [],
        "no_op_reason": "no_temporary_or_billable_infrastructure_created",
        "legacy_cleanup_receipts": cleanup_entries,
    }
    teardown_manifest_digest = domain_digest(
        "GTBI_V7_NO_GO_TEARDOWN_MANIFEST_V1", teardown_manifest
    )
    financial_closure = {
        "billing_entries": billing_entries,
        "maximum_incremental_net_spend_usd": 0,
        "current_actions_net_amount_usd": 0,
        "unreconciled_cost_domains": [],
        "terminal_financial_exception_required": False,
    }
    financial_closure_digest = domain_digest(
        "GTBI_V7_NO_GO_FINANCIAL_CLOSURE_RECEIPT_SET_V1", financial_closure
    )

    events: list[dict[str, Any]] = []
    previous: str | None = None
    for sequence, state in enumerate(
        (
            "created",
            "inventory_frozen",
            "cleanup_running",
            "reconciliation",
            "NO_GO_CLOSED",
        )
    ):
        event = _event(
            close_id=close_id,
            sequence=sequence,
            state=state,
            timestamp=closed_at_utc,
            previous_digest=previous,
            base_sha=base_sha,
        )
        events.append(event)
        previous = event["event_digest"]

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_no_go_close_controller_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "no_go_close_id": close_id,
        "trigger_receipt_digest": validated["trigger"]["receipt_digest"],
        "bootstrap_g0_incomplete": False,
        "failed_g0_predicate_set_digest_or_null": None,
        "bootstrap_close_receipt_digest_or_null": None,
        "evaluated_commit_sha": base_sha,
        "task_and_gate_head_digest": task_and_gate_head_digest,
        "resource_inventory_digest": resource_inventory_digest,
        "billing_domain_manifest_digest": billing_digest,
        "teardown_manifest_digest": teardown_manifest_digest,
        "retained_evidence_manifest_digest": retention_digest,
        "cleanup_receipt_set_digest": cleanup_digest,
        "financial_closure_receipt_set_digest": financial_closure_digest,
        "terminal_financial_exception_or_null": None,
        "terminal_state": "NO_GO_CLOSED",
        "closed_at_utc": closed_at_utc,
        "event_chain_head_digest": events[-1]["event_digest"],
        "run": {
            "id": run_id,
            "url": run_url,
            "github_only": True,
            "requires_local_machine": False,
        },
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
            "provider_download_performed": False,
        },
        "resource_inventory": resource_inventory,
        "teardown_manifest": teardown_manifest,
        "financial_closure": financial_closure,
        "events": events,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_NO_GO_CLOSE_CONTROLLER_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt
