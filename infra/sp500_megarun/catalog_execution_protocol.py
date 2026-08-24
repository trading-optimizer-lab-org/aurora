"""Campaign-specific execution-protocol identity for admission and recovery."""

from __future__ import annotations

import hashlib
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256

from .catalog_campaign_registry import CatalogCampaignEntryV1


PROTOCOL_COMMON_PATHS = (
    ".github/actions/catalog-live-controls-audit/action.yml",
    ".github/workflows/catalog-ledger-guard.yml",
    ".github/workflows/catalog-request-reconciler.yml",
    ".github/workflows/catalog-run-controller.yml",
    ".github/workflows/catalog-run-watchdog.yml",
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_github_controls_v1.json",
    "config/catalog_keeper_source_artifacts_v1.json",
    "config/catalog_operational_qualification_v1.json",
    "config/catalog_run_prompt_policy_v1.json",
    "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    "infra/github_performance/contracts.py",
    "infra/github_performance/merge_planner.py",
    "infra/github_performance/recovery.py",
    "infra/sp500_megarun/catalog_admission.py",
    "infra/sp500_megarun/catalog_admission_adapter.py",
    "infra/sp500_megarun/catalog_authority_ledger.py",
    "infra/sp500_megarun/catalog_authority_writer.py",
    "infra/sp500_megarun/catalog_campaign_definition_builder.py",
    "infra/sp500_megarun/catalog_campaign_definition_contract.py",
    "infra/sp500_megarun/catalog_campaign_registry.py",
    "infra/sp500_megarun/catalog_capacity_qualification.py",
    "infra/sp500_megarun/catalog_comment_tamper.py",
    "infra/sp500_megarun/catalog_component_store.py",
    "infra/sp500_megarun/catalog_controller.py",
    "infra/sp500_megarun/catalog_controller_reporting.py",
    "infra/sp500_megarun/catalog_engine_outcome.py",
    "infra/sp500_megarun/catalog_execution_protocol.py",
    "infra/sp500_megarun/catalog_github_controls.py",
    "infra/sp500_megarun/catalog_github_snapshot.py",
    "infra/sp500_megarun/catalog_mirror_delivery.py",
    "infra/sp500_megarun/catalog_optimization_contract.py",
    "infra/sp500_megarun/catalog_rebuildable_store.py",
    "infra/sp500_megarun/catalog_rebuildable_store_index.py",
    "infra/sp500_megarun/catalog_request_contract.py",
    "infra/sp500_megarun/catalog_request_receipt.py",
    "infra/sp500_megarun/catalog_request_reconciler.py",
    "infra/sp500_megarun/catalog_resume.py",
    "infra/sp500_megarun/catalog_routing.py",
    "infra/sp500_megarun/catalog_routing_snapshot.py",
    "infra/sp500_megarun/catalog_run_request.py",
    "infra/sp500_megarun/catalog_runtime_audit.py",
    "infra/sp500_megarun/catalog_terminal_adapter.py",
    "infra/sp500_megarun/catalog_worker_failure.py",
    "requirements/catalog-controller-linux-py311.lock",
    "schemas/catalog_authority_anchor_v1.schema.json",
    "schemas/catalog_campaign_definition_manifest_v1.schema.json",
    "schemas/catalog_github_auditor_v1.schema.json",
    "schemas/catalog_github_controls_v1.schema.json",
    "schemas/catalog_run_prompt_policy_v1.schema.json",
    "scripts/audit_catalog_github_controls.py",
    "scripts/capture_catalog_routing_snapshot.py",
    "scripts/control_catalog_run.py",
    "scripts/finalize_catalog_controller_run.py",
    "scripts/prepare_catalog_admission_candidates.py",
    "scripts/prepare_catalog_admission_decision.py",
    "scripts/prepare_catalog_authority_record.py",
    "scripts/prepare_catalog_engine_outcome.py",
    "scripts/prepare_catalog_request_receipt.py",
    "scripts/prepare_catalog_terminal_decision.py",
    "scripts/prepare_catalog_terminal_evidence.py",
    "scripts/prepare_catalog_terminal_request_receipt.py",
    "scripts/prepare_catalog_worker_failure.py",
    "scripts/reconcile_catalog_mirror_delivery.py",
    "scripts/route_catalog_run.py",
    "scripts/run_catalog_recipe_worker_guarded.py",
    "scripts/select_catalog_request_reconciliation_candidates.py",
    "scripts/verify_catalog_authority_record.py",
    "scripts/verify_catalog_terminal_science.py",
)


def _repository_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("CATALOG_EXECUTION_PROTOCOL_PATH_INVALID")
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise ValueError("CATALOG_EXECUTION_PROTOCOL_SYMLINK_FORBIDDEN")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"CATALOG_EXECUTION_PROTOCOL_FILE_INVALID:{relative}:{exc}"
        ) from None
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_EXECUTION_PROTOCOL_PATH_INVALID")
    return resolved


def execution_protocol_sha256(
    *,
    root: Path,
    entry: CatalogCampaignEntryV1,
    manifest_sha256: str,
) -> str:
    """Hash common governance plus the selected engine's closed manifest."""

    resolved_root = root.resolve(strict=True)
    if root.is_symlink() or not resolved_root.is_dir():
        raise ValueError("CATALOG_EXECUTION_PROTOCOL_ROOT_INVALID")
    files = {
        relative: hashlib.sha256(
            _repository_file(resolved_root, relative).read_bytes()
        ).hexdigest()
        for relative in PROTOCOL_COMMON_PATHS
    }
    return canonical_sha256(
        {
            "schema_version": "catalog-execution-protocol-v1",
            "registry_entry": entry.model_dump(mode="json"),
            "campaign_definition_manifest_sha256": manifest_sha256,
            "common_protocol_files": files,
        }
    )
