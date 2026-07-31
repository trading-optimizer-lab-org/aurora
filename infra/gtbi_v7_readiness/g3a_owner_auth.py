"""Owner-authorized G3A authentication alternative for GTBI V7."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .canonical import domain_digest
from .g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    G3A_BASELINE_TASK_IDS,
    REPOSITORY,
    REPOSITORY_OWNER_ACTOR_ID,
)

G3A_OWNER_AUTH_TASK_IDS = ("PREV7-0204", "PREV7-0210")
COMPLETION_MODE = "owner_controlled_ephemeral_github_token_alternative"
AUTHENTICATION_MODEL = "repository_scoped_ephemeral_github_token"


class G3AOwnerAuthError(ValueError):
    """Raised when the owner-authorized alternative is not fully evidenced."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise G3AOwnerAuthError(message)


def _task_statuses(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(row["id"]): str(row["status"])
        for row in rows
        if str(row["id"]) in G3A_OWNER_AUTH_TASK_IDS
    }


def build_owner_auth_receipt(
    *,
    owner_directive: Mapping[str, Any],
    owner_decisions: Mapping[str, Any],
    foundation: Mapping[str, Any],
    live_baseline: Mapping[str, Any],
    frozen_data_release: Mapping[str, Any],
    packages_inventory: Mapping[str, Any],
    task_rows: Sequence[Mapping[str, Any]],
    evidence_file_sha256: Mapping[str, str],
    recorded_at_utc: str,
) -> dict[str, Any]:
    """Validate all evidence and build the deterministic alternative receipt."""

    decisions = owner_decisions.get("decisions") or {}
    budget = decisions.get("budget") or {}
    private_resources = decisions.get("private_resources") or {}
    private_auth = foundation.get("private_authentication") or {}
    scientific = foundation.get("scientific_boundaries") or {}
    live_evaluation = live_baseline.get("evaluation") or {}
    live_tasks = live_evaluation.get("task_completion") or {}
    live_scientific = live_baseline.get("scientific_boundaries") or {}
    source_apps = live_baseline.get("source_github_apps") or {}
    task_statuses = _task_statuses(task_rows)

    _require(owner_directive.get("accepted") is True, "owner directive not accepted")
    _require(
        owner_directive.get("owner_actor_id") == REPOSITORY_OWNER_ACTOR_ID,
        "owner directive actor mismatch",
    )
    _require(
        owner_decisions.get("execution_status")
        == "TECHNICAL_PREPARATION_AUTHORIZED",
        "technical preparation is not authorized",
    )
    _require(
        private_resources.get("owner_authorization")
        == "authorized_explicitly",
        "private resources are not owner-authorized",
    )
    _require(
        budget.get("maximum_incremental_net_spend_usd") == 0,
        "incremental spend cap is not zero",
    )
    _require(foundation.get("owner_controlled_model") is True, "owner model missing")
    _require(
        foundation.get("maximum_incremental_net_spend_usd") == 0,
        "foundation spend cap is not zero",
    )
    _require(
        private_auth.get("model") == AUTHENTICATION_MODEL,
        "unexpected private authentication model",
    )
    _require(
        private_auth.get("owner_simplification_applied") is True,
        "owner authentication simplification is not applied",
    )
    _require(
        private_auth.get("external_github_app_required") is False,
        "external GitHub App is still required",
    )
    _require(
        private_auth.get("external_key_broker_required") is False,
        "external key broker is still required",
    )
    _require(
        private_auth.get("long_lived_token_in_workflow") is False,
        "long-lived workflow token is forbidden",
    )
    _require(
        foundation.get("read_packages_scope_present") is True,
        "foundation does not confirm read:packages",
    )
    _require(
        packages_inventory.get("read_packages_scope_present") is True,
        "read:packages scope is not verified",
    )
    _require(
        "read:packages" in packages_inventory.get("token_scopes", []),
        "read:packages is absent from the verified scopes",
    )
    _require(
        live_baseline.get("repository") == REPOSITORY,
        "live baseline repository mismatch",
    )
    _require(
        int(live_evaluation.get("environment_count", -1))
        == len(CANONICAL_SOURCE_ENVIRONMENTS),
        "canonical environment count mismatch",
    )
    live_environment_names = tuple(
        item.get("name")
        for item in live_baseline.get("canonical_source_environments", [])
    )
    _require(
        live_environment_names == CANONICAL_SOURCE_ENVIRONMENTS,
        "canonical environment set or order mismatch",
    )
    _require(
        all(live_tasks.get(task_id) is True for task_id in G3A_BASELINE_TASK_IDS),
        "minimum G3A baseline tasks are not complete",
    )
    _require(
        int(source_apps.get("installation_count", -1)) == 0,
        "unexpected source GitHub App installation",
    )
    valid_task_states = (
        {task_id: "blocked" for task_id in G3A_OWNER_AUTH_TASK_IDS},
        {task_id: "done" for task_id in G3A_OWNER_AUTH_TASK_IDS},
    )
    _require(
        task_statuses in valid_task_states,
        "owner-auth tasks are not consistently blocked or done",
    )
    _require(
        frozen_data_release.get("status") == "verified_published_private",
        "frozen data release is not verified",
    )
    _require(
        frozen_data_release.get("repository_private") is True,
        "frozen data repository is not private",
    )
    _require(
        frozen_data_release.get("github_only_verification") is True,
        "frozen data release lacks GitHub-only verification",
    )
    _require(
        frozen_data_release.get("requires_local_machine") is False,
        "frozen data release depends on the local machine",
    )
    _require(
        frozen_data_release.get("provider_download_performed") is False,
        "provider data was downloaded during publication",
    )
    _require(
        frozen_data_release.get("scientific_processing_performed") is False,
        "scientific processing occurred during publication",
    )
    _require(
        frozen_data_release.get("scientific_cutoff") == "2020-12-31",
        "scientific cutoff mismatch",
    )
    _require(
        frozen_data_release.get("locked_start") == "2021-01-01",
        "frozen release locked boundary mismatch",
    )
    _require(
        scientific.get("locked_data_opened") is False,
        "foundation opened locked data",
    )
    _require(
        scientific.get("scientific_processing_performed") is False,
        "foundation performed scientific processing",
    )
    _require(
        live_scientific.get("locked_data_accessed") is False,
        "live baseline accessed locked data",
    )
    _require(
        live_scientific.get("scientific_processing_performed") is False,
        "live baseline performed scientific processing",
    )

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3a_owner_auth_completion_receipt_v1",
        "repository": REPOSITORY,
        "owner_actor_id": REPOSITORY_OWNER_ACTOR_ID,
        "recorded_at_utc": recorded_at_utc,
        "completion_mode": COMPLETION_MODE,
        "authorization_basis": {
            "owner_controlled_model": True,
            "private_resources_authorized": True,
            "maximum_incremental_net_spend_usd": 0,
            "owner_simplification_applied": True,
        },
        "authentication": {
            "model": AUTHENTICATION_MODEL,
            "source_github_apps_required": False,
            "source_github_app_installation_count": 0,
            "external_key_broker_required": False,
            "long_lived_token_in_workflow": False,
            "credential_persistence": "none",
        },
        "github_governance": {
            "environment_count": len(CANONICAL_SOURCE_ENVIRONMENTS),
            "environment_names": list(CANONICAL_SOURCE_ENVIRONMENTS),
            "minimum_baseline_task_completion": {
                task_id: True for task_id in G3A_BASELINE_TASK_IDS
            },
            "read_packages_scope_present": True,
        },
        "private_data_transport": {
            "repository": frozen_data_release["repository"],
            "release_tag": frozen_data_release["release_tag"],
            "release_id": frozen_data_release["release_id"],
            "repository_private": True,
            "github_only_verification": True,
            "verification_run_id": frozen_data_release["verification_run_id"],
            "requires_local_machine": False,
            "provider_download_performed": False,
        },
        "task_completion": {
            task_id: True for task_id in G3A_OWNER_AUTH_TASK_IDS
        },
        "scientific_boundaries": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "local_research_run_performed": False,
        },
        "evidence_file_sha256": dict(sorted(evidence_file_sha256.items())),
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3A_OWNER_AUTH_COMPLETION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt
