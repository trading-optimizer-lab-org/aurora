"""Create and verify the independent GTBI V7 historical campaign plan."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts import gtbi_fast_strict as strict

CAMPAIGN_ID = "gtbi_v7_new_reference_v1"
PRODUCT_ID = "gtbi_v7_performance_engine_new_reference"
TRAIN_END = "2010-12-31"
VALIDATION_START = "2011-01-01"
VALIDATION_END = "2020-12-31"
HISTORICAL_EXCLUSION_START = "2021-01-01"
DEFAULT_LOGICAL_WORKERS = 360
DEFAULT_BLOCK_SIZE = 20
DEFAULT_EXECUTION_MODE = strict.DEFAULT_EXECUTION_MODE


class V7CampaignError(RuntimeError):
    """Raised when the V7 campaign contract fails closed."""


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V7CampaignError(f"JSON object expected: {path}")
    return dict(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _contract_digest(contract: dict[str, Any]) -> str:
    value = dict(contract)
    value.pop("contract_digest", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _receipt_digest(receipt: dict[str, Any]) -> str:
    value = dict(receipt)
    value.pop("receipt_digest", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _write_strict_campaign_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Preserve the strict engine's JSON number spelling and fingerprint."""
    Path(path).write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str) + "\n",
        encoding="utf-8",
    )


def _validated_authorization(path: Path) -> dict[str, Any]:
    authorization = _load_object(path)
    if authorization.get("campaign_id") != CAMPAIGN_ID:
        raise V7CampaignError("authorization campaign identity mismatch")
    if authorization.get("separate_from_v6") is not True:
        raise V7CampaignError("V7 must remain separate from V6")
    boundaries = dict(authorization.get("scientific_boundaries") or {})
    required = {
        "train_end": TRAIN_END,
        "validation_start": VALIDATION_START,
        "validation_end": VALIDATION_END,
        "historical_exclusion_start": HISTORICAL_EXCLUSION_START,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "provider_download_performed": False,
    }
    for field, expected in required.items():
        if boundaries.get(field) != expected:
            raise V7CampaignError(f"authorization boundary mismatch: {field}")
    policy = dict(authorization.get("execution_policy") or {})
    if policy.get("github_actions_only") is not True or policy.get("local_scientific_runs_allowed") is not False:
        raise V7CampaignError("authorization is not GitHub-only")
    if float(policy.get("maximum_incremental_net_spend_usd", -1)) != 0:
        raise V7CampaignError("campaign incremental spend must remain zero")
    return authorization


def _validated_data_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _load_object(path)
    contract = dict(manifest.get("v7_data_contract") or {})
    if contract.get("campaign_id") != CAMPAIGN_ID:
        raise V7CampaignError("data pack is not bound to the V7 campaign")
    if contract.get("contract_digest") != _contract_digest(contract):
        raise V7CampaignError("V7 data contract digest mismatch")
    if contract.get("locked_rows_in_execution_pack") is not False:
        raise V7CampaignError("V7 data pack contains locked rows")
    if contract.get("locked_data_accessed_by_evaluator") is not False:
        raise V7CampaignError("V7 data pack reports locked access")
    if manifest.get("locked_start") != HISTORICAL_EXCLUSION_START:
        raise V7CampaignError("data manifest locked boundary mismatch")
    if manifest.get("validation_end") != VALIDATION_END:
        raise V7CampaignError("data manifest validation boundary mismatch")
    return manifest, contract


def create_v7_campaign_plan(
    *,
    pack_path: Path,
    output_dir: Path,
    data_manifest_path: Path,
    authorization_path: Path,
    dependency_lock_path: Path,
    code_sha: str,
    logical_worker_count: int = DEFAULT_LOGICAL_WORKERS,
    execution_mode: str = DEFAULT_EXECUTION_MODE,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> dict[str, Any]:
    """Create the strict plan, then bind it to the independent V7 contract."""
    authorization = _validated_authorization(Path(authorization_path))
    data_manifest, data_contract = _validated_data_manifest(Path(data_manifest_path))
    manifest = strict.create_campaign_plan(
        Path(pack_path),
        Path(output_dir),
        worker_count=int(logical_worker_count),
        expected_strategy_count=strict.DEFAULT_EXPECTED_STRATEGY_COUNT,
        expected_unique_group_count=strict.DEFAULT_EXPECTED_UNIQUE_GROUP_COUNT,
        expected_unique_signal_bundle_count=strict.DEFAULT_EXPECTED_UNIQUE_SIGNAL_BUNDLE_COUNT,
        expected_exit_variants_per_signal=strict.DEFAULT_EXIT_VARIANTS_PER_SIGNAL,
        code_sha=str(code_sha),
        data_run_identity=str(data_manifest["data_pack_identity"]),
        train_end=TRAIN_END,
        validation_start=VALIDATION_START,
        validation_end=VALIDATION_END,
        locked_start=HISTORICAL_EXCLUSION_START,
        min_market_cap=float(data_manifest["min_market_cap"]),
        execution_mode=str(execution_mode),
        universe_identity=str(data_manifest["universe_identity"]),
        dependency_lock_identity=_sha256(Path(dependency_lock_path)),
        strategy_format="jsonl",
        block_size=int(block_size),
    )
    contract = {
        "schema_version": "gtbi_v7_new_reference_campaign_contract_v1",
        "campaign_id": CAMPAIGN_ID,
        "product_identity": PRODUCT_ID,
        "separate_from_v6": True,
        "v6_equivalence_claim_allowed": False,
        "campaign_fingerprint": manifest["campaign_fingerprint"],
        "authorization_receipt_digest": authorization["receipt_digest"],
        "authorization_file_sha256": _sha256(Path(authorization_path)),
        "data_contract_digest": data_contract["contract_digest"],
        "data_pack_identity": data_manifest["data_pack_identity"],
        "strategy_pack_digest": manifest["inputs"]["strategy_pack_digest"],
        "dependency_lock_identity": manifest["inputs"]["dependency_lock_identity"],
        "code_sha": str(code_sha),
        "execution_mode": str(execution_mode),
        "logical_worker_count": int(logical_worker_count),
        "block_size": int(block_size),
        "train_end": TRAIN_END,
        "validation_start": VALIDATION_START,
        "validation_end": VALIDATION_END,
        "historical_exclusion_start": HISTORICAL_EXCLUSION_START,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_actions_only": True,
        "local_scientific_execution_allowed": False,
        "maximum_incremental_net_spend_usd": 0,
        "survivorship_biased": True,
        "point_in_time_universe": False,
        "retrospectively_adjusted_reference": True,
        "historical_causal_claims_allowed": False,
    }
    contract["contract_digest"] = _contract_digest(contract)
    manifest["v7_campaign_contract"] = contract
    manifest_path = Path(output_dir) / "campaign_manifest.json"
    _write_strict_campaign_manifest(manifest_path, manifest)
    (Path(output_dir) / "v7_campaign_contract.json").write_bytes(canonical_bytes(contract) + b"\n")
    return manifest


def verify_v7_campaign_plan(
    *,
    plan_root: Path,
    authorization_path: Path | None = None,
    data_manifest_path: Path | None = None,
    expected_code_sha: str | None = None,
) -> dict[str, Any]:
    """Verify strict plan artifacts and every independent V7 binding."""
    root = Path(plan_root)
    strict.verify_campaign_artifacts(root)
    manifest = _load_object(root / "campaign_manifest.json")
    contract = dict(manifest.get("v7_campaign_contract") or {})
    if contract.get("contract_digest") != _contract_digest(contract):
        raise V7CampaignError("V7 campaign contract digest mismatch")
    if contract.get("campaign_id") != CAMPAIGN_ID or contract.get("separate_from_v6") is not True:
        raise V7CampaignError("invalid V7 campaign identity")
    if contract.get("locked_authorized") is not False or contract.get("locked_data_accessed") is not False:
        raise V7CampaignError("locked must remain closed")
    if contract.get("historical_exclusion_start") != HISTORICAL_EXCLUSION_START:
        raise V7CampaignError("V7 historical exclusion boundary mismatch")
    if str(manifest["inputs"]["validation_end"]) != VALIDATION_END:
        raise V7CampaignError("campaign validation end mismatch")
    if contract.get("campaign_fingerprint") != manifest.get("campaign_fingerprint"):
        raise V7CampaignError("V7 contract fingerprint mismatch")
    github_sha = os.environ.get("GITHUB_SHA") if os.environ.get("GITHUB_ACTIONS") == "true" else None
    code_sha = str(expected_code_sha or github_sha or "")
    if code_sha and contract.get("code_sha") != code_sha:
        raise V7CampaignError("campaign code SHA differs from the expected scientific commit")
    if authorization_path is not None:
        authorization = _validated_authorization(Path(authorization_path))
        if contract.get("authorization_receipt_digest") != authorization.get("receipt_digest"):
            raise V7CampaignError("campaign authorization binding mismatch")
    if data_manifest_path is not None:
        data_manifest, data_contract = _validated_data_manifest(Path(data_manifest_path))
        if contract.get("data_pack_identity") != data_manifest.get("data_pack_identity"):
            raise V7CampaignError("campaign data identity mismatch")
        if contract.get("data_contract_digest") != data_contract.get("contract_digest"):
            raise V7CampaignError("campaign data contract mismatch")
    return manifest


def validate_benchmark_evidence(
    *,
    campaign_manifest_path: Path,
    benchmark_path: Path,
) -> dict[str, Any]:
    """Bind an equivalent 1/2/4 benchmark to one exact campaign plan."""
    campaign = _load_object(Path(campaign_manifest_path))
    benchmark = _load_object(Path(benchmark_path))
    if benchmark.get("receipt_digest") != _receipt_digest(benchmark):
        raise V7CampaignError("benchmark receipt digest mismatch")
    required = {
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": campaign.get("campaign_fingerprint"),
        "equivalent": True,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_only_run": True,
        "queue_time_included": False,
    }
    for field, expected in required.items():
        if benchmark.get(field) != expected:
            raise V7CampaignError(f"benchmark evidence mismatch: {field}")
    selected = int(benchmark.get("selected_processes_per_runner", 0))
    symbol_workers = int(benchmark.get("selected_symbol_workers_per_process", 0))
    effective_cpus = int(benchmark.get("effective_cpu_count", 0))
    if selected not in {1, 2, 4} or symbol_workers not in {1, 2, 4}:
        raise V7CampaignError("benchmark selected worker allocation is invalid")
    if effective_cpus < selected or selected * symbol_workers > effective_cpus:
        raise V7CampaignError("benchmark selected allocation exceeds measured CPUs")
    if benchmark.get("worker_ids") != [0, 1, 2, 3]:
        raise V7CampaignError("benchmark did not evaluate the exact four-worker workload")
    return benchmark


def validate_smoke_evidence(
    *,
    campaign_manifest_path: Path,
    smoke_validation_path: Path,
) -> dict[str, Any]:
    """Bind a complete 100-job smoke receipt to one exact campaign plan."""
    campaign = _load_object(Path(campaign_manifest_path))
    smoke = _load_object(Path(smoke_validation_path))
    if smoke.get("receipt_digest") != _receipt_digest(smoke):
        raise V7CampaignError("smoke receipt digest mismatch")
    required = {
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": campaign.get("campaign_fingerprint"),
        "valid": True,
        "worker_count": 100,
        "historical_exclusion_start": HISTORICAL_EXCLUSION_START,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_only_run": True,
    }
    for field, expected in required.items():
        if smoke.get(field) != expected:
            raise V7CampaignError(f"smoke evidence mismatch: {field}")
    if smoke.get("worker_ids") != list(range(100)):
        raise V7CampaignError("smoke evidence does not cover exact workers 0 through 99")
    for field in (
        "strategies_timed_out",
        "strategies_runtime_error",
        "strategies_unsupported",
        "strategies_slow_deferred",
    ):
        if int(smoke.get(field, -1)) != 0:
            raise V7CampaignError(f"smoke evidence has nonzero {field}")
    return smoke


__all__ = [
    "CAMPAIGN_ID",
    "DEFAULT_EXECUTION_MODE",
    "DEFAULT_BLOCK_SIZE",
    "DEFAULT_LOGICAL_WORKERS",
    "HISTORICAL_EXCLUSION_START",
    "PRODUCT_ID",
    "TRAIN_END",
    "VALIDATION_END",
    "VALIDATION_START",
    "V7CampaignError",
    "create_v7_campaign_plan",
    "verify_v7_campaign_plan",
    "validate_benchmark_evidence",
    "validate_smoke_evidence",
]
