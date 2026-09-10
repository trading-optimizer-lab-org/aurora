"""Protected, one-shot transient-fault hook for the catalog canary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from collections.abc import Sequence
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_worker_admission
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogPreparationIdentityV1,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import RunOptimizationContractV1
from aurora.infra.sp500_megarun.catalog_recovery_blocks import resolve_recovery_block
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.catalog_sealed_plan import verify_sealed_global_reuse_execution_plan


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_POLICY_PATH = _REPOSITORY_ROOT / "config/catalog_fast_canary_recovery_policy_v1.json"
_PUBLIC_KEY_PATH = _REPOSITORY_ROOT / "config/catalog_requester_public_key_v1.pem"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_mapping(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_CANARY_ACCEPTANCE_DOCUMENT_INVALID")
            result[key] = value
        return result

    def nonfinite(_value: str) -> None:
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_DOCUMENT_INVALID")

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_DOCUMENT_INVALID")
    value = json.loads(path.read_text("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_DOCUMENT_INVALID")
    return value


def _verify_authenticated_worker_inputs(
    *,
    request_context_path: Path,
    sealed_plan_root: Path,
    resolved_contract_path: Path,
    run_plan_path: Path,
    payload_descriptor_path: Path,
    assignment_path: Path,
    checkpoint_policy_path: Path,
    campaign_key: str,
    generation: int,
    context_sha256: str,
    request_sha256: str,
    execution_plan_sha256: str,
    worker_id: int,
    total_workers: int,
    checkpoint_slot_index: int,
    strategy_ids: Sequence[str],
    attempt_id: str,
    recovery_block_id: str,
) -> None:
    context = _read_mapping(request_context_path)
    context_identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if (
        context.get("schema_version") != "1"
        or context.get("document_type") != "catalog_fast_request_context_v1"
        or context.get("request_mode") != "admit_new"
        or context.get("content_sha256") != context_sha256
        or canonical_sha256(context_identity) != context_sha256
        or type(context.get("issue_number")) is not int
        or context["issue_number"] < 1
        or context.get("protected_commit_sha") != os.environ.get("GITHUB_SHA")
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_CONTEXT_INVALID")

    # Hashes bind bytes; only the existing requester signature authenticates the
    # campaign and generation. No caller-provided key or unsigned token is trusted.
    declared = CatalogRunRequestV1.model_validate(context.get("request"))
    request = parse_catalog_run_request(
        f"[AURORA CATALOG RUN REQUEST] {declared.request_id}",
        "```json\n" + json.dumps(declared.model_dump(mode="json"), sort_keys=True,
                                 separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n```\n",
        _PUBLIC_KEY_PATH.read_bytes(),
    )
    actors = _read_mapping(_REPOSITORY_ROOT / "config/catalog_controller_actors_v1.json")
    if (
        context.get("actor") not in actors.get("request_actors", [])
        or request.request_sha256 != request_sha256
        or request.campaign_key != campaign_key
        or request.launch_generation != generation
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_REQUEST_INVALID")
    registry = load_catalog_campaign_registry(_REPOSITORY_ROOT / "config/catalog_campaign_registry_v1.json")
    entry = resolve_catalog_campaign(registry, request.campaign_key, _REPOSITORY_ROOT)
    manifest = parse_catalog_campaign_definition_bytes(
        (_REPOSITORY_ROOT / entry.definition_manifest_path).read_bytes()
    )
    identity = CatalogPreparationIdentityV1.model_validate(context.get("identity"))
    if (
        manifest.campaign_key != request.campaign_key
        or manifest.campaign_definition_sha256 != request.campaign_definition_sha256
        or identity.campaign_key != request.campaign_key
        or identity.campaign_definition_sha256 != request.campaign_definition_sha256
        or identity.scientific_contract_sha256 != entry.scientific_contract_sha256
        or identity.protected_commit_sha != context["protected_commit_sha"]
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_CAMPAIGN_INVALID")
    decision = CatalogFastLaunchDecisionV1.model_validate(
        _read_mapping(request_context_path.parent / "catalog-fast-decision-v1.json")
    )
    if (
        not decision.launch_required or decision.selected_workers != total_workers
        or decision.request_sha256 != request.request_sha256
        or decision.submission_key_sha256 != request.submission_key_sha256
        or decision.campaign_key != request.campaign_key
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_DECISION_INVALID")

    receipt = verify_sealed_global_reuse_execution_plan(
        sealed_plan_root,
        expected_bindings={
            "request_sha256": request.request_sha256,
            "decision_sha256": decision.decision_sha256,
            "execution_plan_sha256": execution_plan_sha256,
            "protected_commit_sha": identity.protected_commit_sha,
            "science_sha256": entry.scientific_contract_sha256,
        },
    )
    controller = _read_mapping(sealed_plan_root / "controller_binding.json")
    binding = controller.get("binding")
    if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in {
        "request_sha256": request.request_sha256,
        "campaign_definition_sha256": request.campaign_definition_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "protected_commit_sha": identity.protected_commit_sha,
    }.items()):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_PLAN_INVALID")
    for actual, member in (
        (resolved_contract_path, "resolved_contract.json"),
        (run_plan_path, "run_plan.json"),
        (checkpoint_policy_path, "checkpoint_policy.json"),
    ):
        if actual.is_symlink() or actual.read_bytes() != (sealed_plan_root / member).read_bytes():
            raise ValueError("CATALOG_CANARY_ACCEPTANCE_WORKER_INPUT_MISMATCH")
    plan = verify_catalog_worker_admission(
        run_plan_path, admission_token_sha256=str(receipt["admission_token_sha256"]),
        shard_index=worker_id, total_shards=total_workers,
    )
    contract = RunOptimizationContractV1.model_validate(_read_mapping(resolved_contract_path))
    if (plan.qualification_only or plan.contract_sha256 != contract.contract_sha256
            or canonical_sha256(contract.science) != entry.scientific_contract_sha256):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_SCIENCE_INVALID")
    routes = [row for name in ("recipe_matrix_a", "recipe_matrix_b", "recipe_matrix_c")
              for row in _read_mapping(sealed_plan_root / f"{name}.json")["include"]
              if row["worker_id"] == worker_id]
    descriptor = _read_mapping(payload_descriptor_path)
    if (
        len(routes) != 1
        or hashlib.sha256(payload_descriptor_path.read_bytes()).hexdigest() != routes[0]["descriptor_sha256"]
        or descriptor.get("attempt_id") != attempt_id
        or attempt_id != f"{receipt['authority_id']}:worker:{worker_id:03d}:attempt:1"
        or descriptor.get("prior_checkpoint_chain_artifact") != ""
        or hashlib.sha256(assignment_path.read_bytes()).hexdigest() != descriptor.get("assignment_sha256")
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_DESCRIPTOR_INVALID")
    if resolve_recovery_block(
        _read_mapping(checkpoint_policy_path), science_sha256=entry.scientific_contract_sha256,
        worker_id=worker_id, slot_index=checkpoint_slot_index, strategy_ids=strategy_ids,
    ) != recovery_block_id:
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_BLOCK_INVALID")


def load_canary_recovery_policy() -> dict[str, Any]:
    """Load the literal protected policy used by both gate and worker."""

    payload = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_CANARY_RECOVERY_POLICY_INVALID")
    expected = {
        "schema_version",
        "campaign_key",
        "controlled_generation",
        "expected_worker_count",
        "target_worker_id",
        "target_checkpoint_slot_index",
        "expected_checkpoint_slot_count",
        "expected_strategy_count",
        "initial_attempt_suffix",
        "failure_exception",
        "failure_source_code",
        "failure_stage",
    }
    if (
        set(payload) != expected
        or payload["schema_version"] != "catalog-fast-canary-recovery-policy-v1"
    ):
        raise ValueError("CATALOG_CANARY_RECOVERY_POLICY_INVALID")
    return payload


def canary_policy_sha256() -> str:
    return canonical_sha256(load_canary_recovery_policy())


def controlled_failure_source_code() -> str:
    return str(load_canary_recovery_policy()["failure_source_code"])


def build_canary_acceptance_token(
    *,
    campaign_key: str,
    generation: int,
    context_sha256: str,
    request_sha256: str,
    execution_plan_sha256: str,
) -> str:
    """Bind the gate context and sealed execution plan to the worker hook."""

    policy = load_canary_recovery_policy()
    return canonical_sha256(
        {
            "schema_version": "catalog-fast-canary-acceptance-token-v1",
            "policy_sha256": canonical_sha256(policy),
            "campaign_key": campaign_key,
            "generation": generation,
            "context_sha256": context_sha256,
            "request_sha256": request_sha256,
            "execution_plan_sha256": execution_plan_sha256,
        }
    )


def should_inject_canary_failure(
    *,
    enabled: str,
    campaign_key: str,
    generation: int,
    context_sha256: str,
    request_sha256: str,
    execution_plan_sha256: str,
    acceptance_token: str,
    worker_id: int,
    total_workers: int,
    checkpoint_slot_index: int,
    checkpoint_slot_count: int,
    strategy_ids: Sequence[str],
    attempt_id: str,
    recovery_block_id: str | None,
    request_context_path: Path | None = None,
    sealed_plan_root: Path | None = None,
    resolved_contract_path: Path | None = None,
    run_plan_path: Path | None = None,
    payload_descriptor_path: Path | None = None,
    assignment_path: Path | None = None,
    checkpoint_policy_path: Path | None = None,
) -> bool:
    """Return true only for the authenticated first canary block.

    Any partially supplied or inconsistent activation is rejected instead of
    silently changing a production run. Recovery descriptors are never passed
    the activation fields; the attempt suffix check is an additional guard.
    """

    activation_fields = (
        context_sha256,
        request_sha256,
        execution_plan_sha256,
        acceptance_token,
        campaign_key,
    )
    if enabled in {"", "false"} and not any(activation_fields):
        return False
    if enabled != "true":
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_BINDING_INVALID")
    policy = load_canary_recovery_policy()
    hashes = (context_sha256, request_sha256, execution_plan_sha256, acceptance_token)
    if any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in hashes):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_BINDING_INVALID")
    if (
        campaign_key != policy["campaign_key"]
        or generation != policy["controlled_generation"]
        or total_workers != policy["expected_worker_count"]
        or worker_id != policy["target_worker_id"]
        or checkpoint_slot_index != policy["target_checkpoint_slot_index"]
        or checkpoint_slot_count != policy["expected_checkpoint_slot_count"]
        or len(strategy_ids) != policy["expected_strategy_count"]
        or not attempt_id.endswith(policy["initial_attempt_suffix"])
        or not recovery_block_id
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_SCOPE_INVALID")
    expected_token = build_canary_acceptance_token(
        campaign_key=campaign_key,
        generation=generation,
        context_sha256=context_sha256,
        request_sha256=request_sha256,
        execution_plan_sha256=execution_plan_sha256,
    )
    if acceptance_token != expected_token:
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_TOKEN_INVALID")
    if (
        request_context_path is None or sealed_plan_root is None
        or resolved_contract_path is None or run_plan_path is None
        or payload_descriptor_path is None or assignment_path is None
        or checkpoint_policy_path is None
    ):
        raise ValueError("CATALOG_CANARY_ACCEPTANCE_AUTHENTICATED_INPUTS_REQUIRED")
    _verify_authenticated_worker_inputs(
        request_context_path=request_context_path,
        sealed_plan_root=sealed_plan_root,
        resolved_contract_path=resolved_contract_path,
        run_plan_path=run_plan_path,
        payload_descriptor_path=payload_descriptor_path,
        assignment_path=assignment_path,
        checkpoint_policy_path=checkpoint_policy_path,
        campaign_key=campaign_key, generation=generation, context_sha256=context_sha256,
        request_sha256=request_sha256, execution_plan_sha256=execution_plan_sha256,
        worker_id=worker_id, total_workers=total_workers, checkpoint_slot_index=checkpoint_slot_index,
        strategy_ids=strategy_ids, attempt_id=attempt_id, recovery_block_id=recovery_block_id,
    )
    return True


__all__ = [
    "build_canary_acceptance_token",
    "canary_policy_sha256",
    "controlled_failure_source_code",
    "load_canary_recovery_policy",
    "should_inject_canary_failure",
]
