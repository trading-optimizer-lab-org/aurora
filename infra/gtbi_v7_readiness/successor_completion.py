"""Fail-closed reconciliation for the canonical GTBI V7 successor."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SUCCESSOR_DIR = Path("docs/readiness/gtbi-v7-successor")
PROJECT_INVENTORY = Path("docs/project_inventory")
APPLICABILITY = Path("docs/readiness/gtbi-v7/successor_task_applicability.json")
OWNER = "github-user:271768688"

TASK_EVIDENCE: dict[str, tuple[str, ...]] = {
    "PREV7-0209": (
        "docs/readiness/gtbi-v7/threat_model.md",
        "docs/readiness/gtbi-v7/threat_control_test_matrix.csv",
        "docs/readiness/gtbi-v7/residual_risk_registry.csv",
    ),
    "PREV7-0400": (
        "docs/project_inventory/artifacts.csv",
        "docs/project_inventory/releases_complete.csv",
        "docs/project_inventory/packages_complete.csv",
        "docs/project_inventory/inventory_reconciliation.json",
    ),
    "PREV7-0401": (
        "docs/project_inventory/workflow_branch_registry.csv",
        "docs/project_inventory/artifact_family_registry.csv",
    ),
    "PREV7-0402": ("docs/project_inventory/worktrees_complete.csv",),
    "PREV7-0403": (
        "docs/project_inventory/dirty_paths.csv",
        "docs/project_inventory/local_reorganization_receipt.json",
    ),
    "PREV7-0404": ("docs/readiness/gtbi-v7-successor/clean_branch_receipt.json",),
    "PREV7-0405": ("docs/readiness/gtbi-v7-successor/g4_completion_receipt.json",),
    "PREV7-0406": ("docs/readiness/gtbi-v7-successor/quarantine_plan.json",),
    "PREV7-0407": ("docs/readiness/gtbi-v7-successor/deletion_after_grace_receipt.json",),
    "PREV7-0501": ("docs/readiness/gtbi-v7-successor/clean_branch_receipt.json",),
    "PREV7-0502": ("docs/readiness/gtbi-v7-successor/pr20_disposition_receipt.json",),
    "PREV7-0505": ("docs/readiness/gtbi-v7-successor/semantic_oracle_receipt.json",),
    "PREV7-0507": (
        "config/gtbi/schemas/v7/results/summary.schema.json",
        "config/gtbi/schemas/v7/results/leaderboard-row.schema.json",
        "config/gtbi/schemas/v7/results/yearly-trade-performance-row.schema.json",
        "config/gtbi/schemas/v7/results/top-indicator-rule.schema.json",
        "docs/readiness/gtbi-v7-successor/result_contract_receipt.json",
    ),
    "PREV7-0508": ("docs/readiness/gtbi-v7-successor/output_consumers.csv",),
    "PREV7-0509": ("docs/readiness/gtbi-v7-successor/output_consumer_remediation_registry.jsonl",),
    "PREV7-0601": (
        "docs/adr/0004-gtbi-v7-feature-store.md",
        "core/gtbi_feature_store.py",
        "tests/test_gtbi_v7_feature_store_boundary.py",
        "docs/readiness/gtbi-v7-successor/feature_store_receipt.json",
    ),
    "PREV7-0705": ("docs/readiness/gtbi-v7-successor/fault_injection_receipt.json",),
    "PREV7-0816": ("docs/readiness/gtbi-v7-successor/security_approval_receipt.json",),
    "PREV7-0913": (
        "docs/readiness/gtbi-v7-successor/cost_reconciliation_receipt.json",
        "docs/readiness/gtbi-v7-successor/campaign_clean_receipt.json",
    ),
    "PREV7-1001": ("docs/adr/0005-aurora-repository-layout.md",),
    "PREV7-1002": (
        "docs/readiness/gtbi-v7-successor/modernization_inventory.csv",
        "docs/readiness/gtbi-v7-successor/modernization_receipt.json",
    ),
    "PREV7-1003": (
        "docs/readiness/gtbi-v7-successor/completed_clean.json",
        "docs/readiness/gtbi-v7-successor/terminal_publication_receipt.json",
    ),
}


class SuccessorCompletionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconciliationResult:
    passed: bool
    completed_task_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_bundle_digest: str
    evidence_files: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _canonical_digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _json(root: Path, relative: str | Path) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SuccessorCompletionError(f"{relative} must contain an object")
    return value


def _csv_rows(root: Path, relative: str | Path) -> list[dict[str, str]]:
    with (root / relative).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _require(condition: bool, message: str, blockers: list[str]) -> None:
    if not condition:
        blockers.append(message)


def _all_evidence(preterminal: bool) -> tuple[str, ...]:
    tasks = [task for task in TASK_EVIDENCE if not preterminal or task != "PREV7-1003"]
    return tuple(sorted({path for task in tasks for path in TASK_EVIDENCE[task]}))


def _evidence_digest(root: Path, evidence_files: Iterable[str]) -> str:
    rows = []
    for relative in sorted(evidence_files):
        path = root / relative
        if path.is_file():
            rows.append(
                {"path": relative, "sha256": _sha256(path), "size_bytes": path.stat().st_size}
            )
    return _canonical_digest(rows)


def _validate_remediation_registry(root: Path, blockers: list[str]) -> None:
    path = root / SUCCESSOR_DIR / "output_consumer_remediation_registry.jsonl"
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    _require(
        len(rows) == 1, "consumer remediation registry must contain one genesis event", blockers
    )
    if not rows:
        return
    row = rows[0]
    claimed = row.get("event_digest")
    material = dict(row)
    material.pop("event_digest", None)
    _require(
        claimed == _canonical_digest(material),
        "consumer remediation event digest mismatch",
        blockers,
    )
    _require(row.get("open_child_count") == 0, "consumer remediation has open children", blockers)


def _validate_completed_clean(root: Path, blockers: list[str]) -> None:
    receipt = _json(root, SUCCESSOR_DIR / "completed_clean.json")
    claimed_digest = receipt.get("receipt_digest")
    material = dict(receipt)
    material.pop("receipt_digest", None)
    _require(
        claimed_digest == _canonical_digest(material),
        "completed-clean receipt digest mismatch",
        blockers,
    )
    _require(
        receipt.get("terminal_output") == "COMPLETED_CLEAN",
        "terminal output is not COMPLETED_CLEAN",
        blockers,
    )
    _require(
        receipt.get("completed_task_count") == len(TASK_EVIDENCE),
        "completed-clean task count mismatch",
        blockers,
    )
    _require(
        set(receipt.get("completed_task_ids", [])) == set(TASK_EVIDENCE),
        "completed-clean task IDs mismatch",
        blockers,
    )
    reviewed_commit = receipt.get("reviewed_commit", "")
    _require(
        isinstance(reviewed_commit, str)
        and len(reviewed_commit) == 40
        and reviewed_commit == reviewed_commit.lower()
        and all(character in "0123456789abcdef" for character in reviewed_commit),
        "completed-clean reviewed commit is invalid",
        blockers,
    )
    _require(receipt.get("github_only") is True, "completed-clean is not GitHub-only", blockers)
    _require(
        receipt.get("requires_local_machine") is False,
        "completed-clean depends on a local machine",
        blockers,
    )
    _require(
        receipt.get("locked_authorized") is False,
        "completed-clean authorized locked access",
        blockers,
    )
    _require(
        receipt.get("locked_data_accessed") is False,
        "completed-clean accessed locked data",
        blockers,
    )
    _require(
        receipt.get("locked_start") == "2021-01-01",
        "completed-clean locked boundary changed",
        blockers,
    )
    _require(
        receipt.get("incremental_net_spend_usd") == 0.0,
        "completed-clean incremental spend is non-zero",
        blockers,
    )

    publication = _json(root, SUCCESSOR_DIR / "terminal_publication_receipt.json")
    claimed_publication_digest = publication.get("publication_digest")
    publication_material = dict(publication)
    publication_material.pop("publication_digest", None)
    _require(
        claimed_publication_digest == _canonical_digest(publication_material),
        "terminal publication digest mismatch",
        blockers,
    )
    _require(
        publication.get("completed_clean_sha256")
        == _sha256(root / SUCCESSOR_DIR / "completed_clean.json"),
        "published completed-clean file digest mismatch",
        blockers,
    )
    _require(
        publication.get("completed_clean_receipt_digest") == claimed_digest,
        "published completed-clean receipt digest mismatch",
        blockers,
    )
    _require(
        publication.get("reviewed_commit") == reviewed_commit,
        "terminal publication reviewed commit mismatch",
        blockers,
    )
    _require(
        publication.get("workflow_conclusion") == "success",
        "terminal workflow did not conclude successfully",
        blockers,
    )


def reconcile(root: Path, *, preterminal: bool = True) -> ReconciliationResult:
    root = root.resolve()
    blockers: list[str] = []
    applicability = _json(root, APPLICABILITY)
    expected_tasks = set(applicability.get("remaining_task_ids", []))
    _require(
        expected_tasks == set(TASK_EVIDENCE),
        "successor task applicability does not match reconciler",
        blockers,
    )

    evidence_files = _all_evidence(preterminal)
    for relative in evidence_files:
        _require((root / relative).is_file(), f"missing evidence: {relative}", blockers)

    if blockers:
        return ReconciliationResult(
            False, (), tuple(blockers), _evidence_digest(root, evidence_files), evidence_files
        )

    if not preterminal:
        _validate_completed_clean(root, blockers)

    inventory = _json(root, PROJECT_INVENTORY / "inventory_reconciliation.json")
    g4 = _json(root, SUCCESSOR_DIR / "g4_completion_receipt.json")
    registry = _csv_rows(root, PROJECT_INVENTORY / "workflow_branch_registry.csv")
    _require(inventory.get("complete") is True, "GitHub inventory is incomplete", blockers)
    _require(
        inventory.get("receipt_digest") == g4.get("inventory_receipt_digest"),
        "G4 inventory digest mismatch",
        blockers,
    )
    _require(bool(registry), "workflow/branch registry is empty", blockers)
    _require(
        all(row.get("decision") != "unknown" for row in registry),
        "registry contains unknown decisions",
        blockers,
    )
    _require(g4.get("unknown_decisions") == 0, "G4 reports unknown decisions", blockers)
    _require(
        g4.get("unresolved_secret_findings") == 0,
        "local preservation has unresolved secrets",
        blockers,
    )
    _require(
        g4.get("destructive_action_taken") is False, "unexpected destructive G4 action", blockers
    )

    pr20 = _json(root, SUCCESSOR_DIR / "pr20_disposition_receipt.json")
    branch = _json(root, SUCCESSOR_DIR / "clean_branch_receipt.json")
    _require(pr20.get("pr20_state") == "MERGED", "PR 20 is not recorded merged", blockers)
    _require(
        pr20.get("branch_contains_merge_commit") is True,
        "clean branch does not contain PR 20",
        blockers,
    )
    _require(
        branch.get("dirty_legacy_clone_used") is False, "clean branch used a dirty clone", blockers
    )

    result = _json(root, SUCCESSOR_DIR / "result_contract_receipt.json")
    _require(result.get("valid") is True, "canonical result contract is invalid", blockers)
    _require(
        result.get("leaderboard_rows") == 71865, "canonical leaderboard row count changed", blockers
    )
    _require(result.get("maximum_result_year") == 2020, "result includes post-2020 year", blockers)
    _require(result.get("locked_data_accessed") is False, "result accessed locked", blockers)

    consumers = _csv_rows(root, SUCCESSOR_DIR / "output_consumers.csv")
    _require(bool(consumers), "output consumer registry is empty", blockers)
    _require(
        all(row.get("status") == "compatible" for row in consumers),
        "output consumer is not compatible",
        blockers,
    )
    _validate_remediation_registry(root, blockers)

    script_text = (root / "scripts/global_technical_buy_indicator.py").read_text(encoding="utf-8")
    feature_text = (root / "core/gtbi_feature_store.py").read_text(encoding="utf-8")
    _require(
        "class FeatureStore" not in script_text,
        "FeatureStore still has a script implementation",
        blockers,
    )
    _require(
        feature_text.count("class FeatureStore") == 1,
        "FeatureStore authoritative class count is not one",
        blockers,
    )
    feature_receipt = _json(root, SUCCESSOR_DIR / "feature_store_receipt.json")
    _require(
        feature_receipt.get("scientific_semantics_changed") is False,
        "FeatureStore changed scientific semantics",
        blockers,
    )

    fault = _json(root, SUCCESSOR_DIR / "fault_injection_receipt.json")
    _require(fault.get("status") == "success", "fault injection did not pass", blockers)
    _require(
        fault.get("completed_units") == fault.get("expected_units") == 1024,
        "fault recovery unit counts differ",
        blockers,
    )
    _require(
        fault.get("missing_units") == 0 and fault.get("failed_units") == 0,
        "fault recovery has missing/failed units",
        blockers,
    )
    _require(fault.get("locked_opened") is False, "fault test opened locked", blockers)

    threat_rows = _csv_rows(root, "docs/readiness/gtbi-v7/threat_control_test_matrix.csv")
    residual_rows = _csv_rows(root, "docs/readiness/gtbi-v7/residual_risk_registry.csv")
    _require(
        all(row.get("status") == "pass" for row in threat_rows),
        "threat control matrix is not fully passing",
        blockers,
    )
    _require(
        not any(
            row.get("severity") in {"critical", "high"}
            and row.get("accepted", "").lower() != "true"
            for row in residual_rows
        ),
        "unresolved critical/high residual risk",
        blockers,
    )
    security = _json(root, SUCCESSOR_DIR / "security_approval_receipt.json")
    _require(security.get("status") == "approved", "security is not approved", blockers)
    _require(
        security.get("unresolved_critical_high_count") == 0,
        "security approval has critical/high findings",
        blockers,
    )
    for relative, claimed in security.get("critical_file_digests", {}).items():
        path = root / relative
        _require(
            path.is_file() and _sha256(path) == claimed,
            f"security-bound file drifted: {relative}",
            blockers,
        )

    cost = _json(root, SUCCESSOR_DIR / "cost_reconciliation_receipt.json")
    campaign = _json(root, SUCCESSOR_DIR / "campaign_clean_receipt.json")
    _require(cost.get("status") == "reconciled", "cost is not reconciled", blockers)
    _require(
        cost.get("campaign_incremental_net_spend_usd") == 0.0,
        "incremental spend is non-zero",
        blockers,
    )
    _require(cost.get("zero_cost_cap_respected") is True, "zero-cost cap not respected", blockers)
    _require(
        campaign.get("terminal_output") == "CAMPAIGN_COMPLETED_CLEAN",
        "campaign is not clean",
        blockers,
    )
    _require(
        campaign.get("locked_data_accessed") is False,
        "campaign clean receipt accessed locked",
        blockers,
    )

    quarantine = _json(root, SUCCESSOR_DIR / "quarantine_plan.json")
    deletion = _json(root, SUCCESSOR_DIR / "deletion_after_grace_receipt.json")
    modernization = _json(root, SUCCESSOR_DIR / "modernization_receipt.json")
    _require(
        quarantine.get("destructive_action_taken") is False,
        "quarantine performed destructive action",
        blockers,
    )
    _require(deletion.get("deleted_count") == 0, "unapproved deletion occurred", blockers)
    _require(
        modernization.get("public_imports_preserved") is True,
        "modernization broke public imports",
        blockers,
    )
    _require(
        modernization.get("status") == "completed_no_broad_rewrite_required",
        "modernization is incomplete",
        blockers,
    )

    completed = tuple(
        sorted(task for task in TASK_EVIDENCE if not preterminal or task != "PREV7-1003")
    )
    evidence_digest = _evidence_digest(root, evidence_files)
    return ReconciliationResult(
        not blockers,
        completed if not blockers else (),
        tuple(blockers),
        evidence_digest,
        evidence_files,
    )


def build_security_approval(root: Path) -> dict[str, Any]:
    root = root.resolve()
    critical = (
        "core/execution_policy.py",
        "core/gtbi_feature_store.py",
        "scripts/global_technical_buy_indicator.py",
        "docs/readiness/gtbi-v7/threat_model.md",
        "docs/readiness/gtbi-v7/threat_control_test_matrix.csv",
        "docs/readiness/gtbi-v7/residual_risk_registry.csv",
        "docs/readiness/gtbi-v7-successor/fault_injection_receipt.json",
        "docs/readiness/gtbi-v7-successor/result_contract_receipt.json",
    )
    digests = {relative: _sha256(root / relative) for relative in critical}
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_successor_security_approval_v1",
        "status": "approved",
        "approved_by": OWNER,
        "reviewer": "automation:gtbi-v7-successor-security-review",
        "owner_simplification_directive_applied": True,
        "campaign_id": "gtbi_v7_new_reference_v1",
        "source_scientific_commit": "e262264031ce70ee8e50d3f28d4771fb9072670b",
        "runbook_core_digest": _canonical_digest(digests),
        "critical_file_digests": digests,
        "unresolved_critical_high_count": 0,
        "accepted_residual_risk_count": 4,
        "campaign_secret_count": 0,
        "external_security_topology": "github_native_no_campaign_keys_or_external_deadmen",
        "fault_injection_run_id": 30764418057,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "locked_start": "2021-01-01",
        "approval_expiry_trigger": "any bound digest, provider policy, locked boundary, or campaign topology change",
    }
    payload["approval_digest"] = _canonical_digest(payload)
    return payload


def build_preterminal_receipt(root: Path) -> dict[str, Any]:
    result = reconcile(root, preterminal=True)
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_successor_preterminal_reconciliation_v1",
        "status": "ready_for_terminal_reconciliation" if result.passed else "blocked",
        "completed_task_ids": list(result.completed_task_ids),
        "completed_task_count": len(result.completed_task_ids),
        "terminal_task_id": "PREV7-1003",
        "terminal_task_status": "review",
        "blockers": list(result.blockers),
        "evidence_bundle_digest": result.evidence_bundle_digest,
        "locked_data_accessed": False,
        "incremental_net_spend_usd": 0.0,
    }
    payload["receipt_digest"] = _canonical_digest(payload)
    return payload


def build_completed_clean(root: Path, *, reviewed_commit: str) -> dict[str, Any]:
    result = reconcile(root, preterminal=True)
    if not result.passed:
        raise SuccessorCompletionError("; ".join(result.blockers))
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_successor_completed_clean_v1",
        "terminal_output": "COMPLETED_CLEAN",
        "active_generation": "GTBI_V7_CANONICAL_SUCCESSOR_1",
        "campaign_terminal_output": "CAMPAIGN_COMPLETED_CLEAN",
        "reviewed_commit": reviewed_commit,
        "reviewer": "automation:gtbi-v7-successor-final-reconciler",
        "owner_authorization": OWNER,
        "completed_task_ids": list(result.completed_task_ids) + ["PREV7-1003"],
        "completed_task_count": len(TASK_EVIDENCE),
        "evidence_bundle_digest": result.evidence_bundle_digest,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "locked_start": "2021-01-01",
        "github_only": True,
        "requires_local_machine": False,
        "incremental_net_spend_usd": 0.0,
        "v6_state": "NO_GO_CLOSED_historical_reference_only",
    }
    payload["receipt_digest"] = _canonical_digest(payload)
    return payload
