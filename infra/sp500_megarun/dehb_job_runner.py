"""Sequential two-island GitHub job around four-slot official DEHB workers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)


class DehbJobRunnerError(ValueError):
    """Raised when a worker job cannot prove exact lineage and closed tiers."""


IslandRunner = Callable[..., Mapping[str, Any]]
PackVerifier = Callable[..., Mapping[str, Any]]


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def load_verified_job_payload(path: Path) -> Mapping[str, Any]:
    """Read a controller payload and reject any byte-level logical alteration."""

    try:
        value = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DehbJobRunnerError("JOB_PAYLOAD_INVALID") from exc
    if not isinstance(value, Mapping):
        raise DehbJobRunnerError("JOB_PAYLOAD_NOT_MAPPING")
    expected = value.get("payload_sha256")
    preimage = {key: item for key, item in value.items() if key != "payload_sha256"}
    if expected != _canonical_hash(preimage):
        raise DehbJobRunnerError("JOB_PAYLOAD_SHA256_MISMATCH")
    return value


def _validate_scientific_payload(
    contract: Any,
    launch_contract: Any,
    payload: Mapping[str, Any],
) -> None:
    if (
        launch_contract.campaign_contract_sha256 != contract.sha256
        or launch_contract.validation_opened is not False
        or launch_contract.locked_opened is not False
    ):
        raise DehbJobRunnerError("LAUNCH_CONTRACT_CAMPAIGN_OR_BOUNDARY_MISMATCH")
    expected = {
        "campaign_contract_sha256": contract.sha256,
        "launch_contract_sha256": launch_contract.sha256,
        "train_source_run_id": contract.train_source_run_id,
        "train_artifact_name": contract.train_artifact_name,
        "train_artifact_digest_sha256": contract.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": contract.train_snapshot_manifest_sha256,
        "train_spy_sha256": contract.train_spy_sha256,
        "train_partition": contract.train_partition,
        "search_start": contract.search_start,
        "search_end": contract.search_end,
        "validation_opened": False,
        "locked_opened": False,
    }
    for key, wanted in expected.items():
        if payload.get(key) != wanted:
            raise DehbJobRunnerError(f"JOB_SCIENTIFIC_INPUT_MISMATCH:{key}")


def run_dehb_job(
    contract: Any,
    feature_contract: Any,
    *,
    launch_contract: Any,
    payload: Mapping[str, Any],
    runtime_input_pack: Path,
    output_dir: Path,
    previous_worker_dir: Path | None = None,
    slice_seconds: float | None = None,
    island_runner: IslandRunner | None = None,
    pack_verifier: PackVerifier = verify_runtime_input_pack,
) -> Mapping[str, Any]:
    """Run exactly two assigned islands sequentially and write one worker result."""

    _validate_scientific_payload(contract, launch_contract, payload)
    islands = payload.get("islands")
    if not isinstance(islands, list) or len(islands) != 2:
        raise DehbJobRunnerError("JOB_ISLAND_ASSIGNMENTS_INVALID")
    expected_aggregate = getattr(
        launch_contract, "runtime_input_aggregate_sha256", None
    )
    if not isinstance(expected_aggregate, str) or len(expected_aggregate) != 64:
        raise DehbJobRunnerError("RUNTIME_INPUT_AGGREGATE_NOT_FROZEN")
    pack_verifier(
        Path(runtime_input_pack),
        expected_scientific_input_binding_sha256=(
            scientific_input_binding_sha256(contract)
        ),
        expected_aggregate_sha256=expected_aggregate,
    )
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise DehbJobRunnerError("WORKER_OUTPUT_MUST_START_EMPTY")
    root.mkdir(parents=True, exist_ok=True)
    pack = Path(runtime_input_pack).resolve()
    prior_root = (
        Path(previous_worker_dir).resolve()
        if previous_worker_dir is not None
        else None
    )
    if island_runner is None:
        from aurora.infra.sp500_megarun.dehb_island_runner import (
            run_official_dehb_island,
        )

        island_runner = run_official_dehb_island
    manifests: list[dict[str, Any]] = []
    for assignment in islands:
        if not isinstance(assignment, Mapping):
            raise DehbJobRunnerError("JOB_ISLAND_ASSIGNMENT_NOT_MAPPING")
        island_id = str(assignment.get("island_id"))
        resume = assignment.get("resume_from_previous_wave") is True
        prior_bundle = prior_root / "islands" / island_id if resume and prior_root else None
        if resume and (prior_bundle is None or not prior_bundle.is_dir()):
            raise DehbJobRunnerError(f"PRIOR_ISLAND_BUNDLE_MISSING:{island_id}")
        manifest = island_runner(
            contract,
            feature_contract,
            assignment=assignment,
            wave=int(payload["wave"]),
            train_snapshot=pack / "train_snapshot_1993_2010",
            baseline_feature_dirs={
                "price": pack / "baseline_price",
                "market": pack / "baseline_market",
                "macro": pack / "baseline_macro",
            },
            output_dir=root / "islands" / island_id,
            prior_bundle=prior_bundle,
            slice_seconds=slice_seconds,
            launch_contract_sha256=launch_contract.sha256,
        )
        manifests.append(
            {
                "island_id": island_id,
                "lane_id": str(assignment["lane_id"]),
                "replicate": int(assignment["replicate"]),
                "restart_ordinal": int(assignment["restart_ordinal"]),
                "status": manifest["status"],
                "stop_reason": manifest["stop_reason"],
                "checkpoint_sha256": manifest["checkpoint_sha256"],
                "evaluations": int(manifest["evaluations"]),
                "full_fidelity_evaluations": int(
                    manifest["full_fidelity_evaluations"]
                ),
                "champion": manifest.get("champion"),
            }
        )
    result = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "launch_contract_sha256": launch_contract.sha256,
        "job_id": str(payload["job_id"]),
        "job_index": int(payload["job_index"]),
        "shard_id": str(payload["shard_id"]),
        "wave": int(payload["wave"]),
        "job_payload_sha256": str(payload["payload_sha256"]),
        "islands": manifests,
        "validation_opened": False,
        "locked_opened": False,
    }
    (root / "worker_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


__all__ = [
    "DehbJobRunnerError",
    "load_verified_job_payload",
    "run_dehb_job",
]
