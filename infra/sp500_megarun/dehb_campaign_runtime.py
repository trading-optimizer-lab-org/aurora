"""Deterministic sharding, checkpoints, ledger, and controller for the mega-run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import AbstractSet, Any, Mapping, Sequence

from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    FrozenCampaignContract,
    build_campaign_manifest,
    build_island_schedule,
)


_ZERO_HASH = "0" * 64
_LEDGER_DOMAIN = b"aurora-sp500-megarun-ledger-v1\0"
_RESTART_DOMAIN = b"aurora-sp500-megarun-restart-v1\0"
_CHECKPOINT_DOMAIN = b"aurora-sp500-megarun-checkpoint-v1\0"


class CampaignRuntimeError(ValueError):
    """Raised when runtime state is incomplete, altered, or opens later data."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CampaignRuntimeError("RUNTIME_VALUE_NOT_CANONICAL_JSON") from exc


def _hash_payload(value: object, *, domain: bytes = b"") -> str:
    return hashlib.sha256(domain + _canonical_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def derive_restart_seed(
    contract: FrozenCampaignContract,
    *,
    island_id: str,
    restart_ordinal: int,
) -> int:
    """Derive a stable uint32 seed that changes for every population restart."""

    if restart_ordinal < 0:
        raise CampaignRuntimeError("NEGATIVE_RESTART_ORDINAL")
    try:
        lane_text, replicate_text = island_id.split("-R", maxsplit=1)
        lane_number = int(lane_text.removeprefix("F"))
        replicate = int(replicate_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CampaignRuntimeError(f"UNKNOWN_ISLAND:{island_id}") from exc
    if (
        lane_text != f"F{lane_number:03d}"
        or not 1 <= lane_number <= contract.lane_count
        or not 1 <= replicate <= contract.replicates_per_lane
    ):
        raise CampaignRuntimeError(f"UNKNOWN_ISLAND:{island_id}")
    preimage = (
        contract.sha256.encode("ascii")
        + b"\0"
        + island_id.encode("ascii")
        + b"\0"
        + str(restart_ordinal).encode("ascii")
    )
    return int.from_bytes(hashlib.sha256(_RESTART_DOMAIN + preimage).digest()[:4], "big")


def _job_payload(
    contract: FrozenCampaignContract,
    *,
    job: Any,
    wave: int,
    restart_ordinal: int,
    campaign_manifest_sha256: str,
    launch_contract_sha256: str | None,
    island_restart_ordinals: Mapping[str, int],
    resume_island_ids: AbstractSet[str],
) -> Mapping[str, Any]:
    island_rows: list[dict[str, Any]] = []
    for island in job.islands:
        island_ordinal = int(
            island_restart_ordinals.get(island.island_id, restart_ordinal)
        )
        if island_ordinal < 0:
            raise CampaignRuntimeError("NEGATIVE_RESTART_ORDINAL")
        island_rows.append(
            {
                "island_id": island.island_id,
                "lane_id": island.lane_id,
                "replicate": island.replicate,
                "base_seed": island.seed,
                "restart_ordinal": island_ordinal,
                "restart_seed": derive_restart_seed(
                    contract,
                    island_id=island.island_id,
                    restart_ordinal=island_ordinal,
                ),
                "resume_from_previous_wave": island.island_id in resume_island_ids,
                "n_workers": island.n_workers,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "campaign_manifest_sha256": campaign_manifest_sha256,
        "job_id": job.job_id,
        "job_index": job.job_index,
        "shard_id": job.shard_id,
        "wave": wave,
        "restart_ordinal": restart_ordinal,
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
        "islands": island_rows,
    }
    if launch_contract_sha256 is not None:
        if not _is_sha256(launch_contract_sha256):
            raise CampaignRuntimeError("INVALID_LAUNCH_CONTRACT_SHA256")
        payload["launch_contract_sha256"] = launch_contract_sha256
    payload["payload_sha256"] = _hash_payload(payload)
    return payload


def build_job_payload(
    contract: FrozenCampaignContract,
    *,
    job_index: int,
    wave: int,
    restart_ordinal: int,
    launch_contract_sha256: str | None = None,
    island_restart_ordinals: Mapping[str, int] | None = None,
    resume_island_ids: AbstractSet[str] | None = None,
) -> Mapping[str, Any]:
    """Build one two-island train-only payload for a 4-vCPU runner."""

    if wave < 0:
        raise CampaignRuntimeError("NEGATIVE_WAVE")
    schedule = build_island_schedule(contract)
    if not 0 <= job_index < len(schedule):
        raise CampaignRuntimeError(f"JOB_INDEX_OUT_OF_RANGE:{job_index}")
    manifest_hash = str(build_campaign_manifest(contract)["manifest_sha256"])
    return _job_payload(
        contract,
        job=schedule[job_index],
        wave=wave,
        restart_ordinal=restart_ordinal,
        campaign_manifest_sha256=manifest_hash,
        launch_contract_sha256=launch_contract_sha256,
        island_restart_ordinals=island_restart_ordinals or {},
        resume_island_ids=resume_island_ids or frozenset(),
    )


def build_shard_matrices(
    contract: FrozenCampaignContract,
    *,
    wave: int = 0,
    restart_ordinal: int = 0,
    launch_contract_sha256: str | None = None,
    island_restart_ordinals: Mapping[str, int] | None = None,
    resume_island_ids: AbstractSet[str] | None = None,
) -> Mapping[str, Mapping[str, list[Mapping[str, Any]]]]:
    """Return three 120-job matrices so GitHub can request 360 runners."""

    matrices: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        shard: {"include": []} for shard in "ABC"
    }
    schedule = build_island_schedule(contract)
    valid_island_ids = {
        island.island_id for job in schedule for island in job.islands
    }
    override_ids = set(island_restart_ordinals or {})
    resume_ids = set(resume_island_ids or ())
    unknown_ids = sorted((override_ids | resume_ids) - valid_island_ids)
    if unknown_ids:
        raise CampaignRuntimeError(
            f"UNKNOWN_ISLAND_RUNTIME_OVERRIDE:{','.join(unknown_ids)}"
        )
    manifest_hash = str(build_campaign_manifest(contract)["manifest_sha256"])
    for job in schedule:
        payload = _job_payload(
            contract,
            job=job,
            wave=wave,
            restart_ordinal=restart_ordinal,
            campaign_manifest_sha256=manifest_hash,
            launch_contract_sha256=launch_contract_sha256,
            island_restart_ordinals=island_restart_ordinals or {},
            resume_island_ids=resume_island_ids or frozenset(),
        )
        matrices[str(payload["shard_id"])]["include"].append(payload)
    if any(len(matrices[shard]["include"]) != 120 for shard in "ABC"):
        raise CampaignRuntimeError("SHARD_MATRIX_SIZE_MISMATCH")
    return matrices


def verify_event_ledger(
    path: Path,
    *,
    campaign_sha256: str,
) -> Mapping[str, Any]:
    """Verify every link in an append-only campaign event ledger."""

    ledger_path = Path(path)
    if not ledger_path.exists():
        return {"record_count": 0, "tail_hash": _ZERO_HASH}
    previous_hash = _ZERO_HASH
    count = 0
    try:
        lines = ledger_path.read_text("utf-8").splitlines()
    except OSError as exc:
        raise CampaignRuntimeError("LEDGER_READ_FAILED") from exc
    for expected_sequence, line in enumerate(lines):
        if not line.strip():
            raise CampaignRuntimeError("LEDGER_BLANK_LINE")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CampaignRuntimeError("LEDGER_INVALID_JSON") from exc
        if not isinstance(record, Mapping):
            raise CampaignRuntimeError("LEDGER_RECORD_NOT_MAPPING")
        if record.get("sequence") != expected_sequence:
            raise CampaignRuntimeError("LEDGER_SEQUENCE_MISMATCH")
        if record.get("campaign_contract_sha256") != campaign_sha256:
            raise CampaignRuntimeError("LEDGER_CAMPAIGN_MISMATCH")
        if record.get("previous_hash") != previous_hash:
            raise CampaignRuntimeError("LEDGER_PREVIOUS_HASH_MISMATCH")
        preimage = {key: value for key, value in record.items() if key != "event_hash"}
        expected_hash = _hash_payload(preimage, domain=_LEDGER_DOMAIN)
        if record.get("event_hash") != expected_hash:
            raise CampaignRuntimeError("LEDGER_EVENT_HASH_MISMATCH")
        previous_hash = expected_hash
        count += 1
    return {"record_count": count, "tail_hash": previous_hash}


def append_ledger_event(
    path: Path,
    *,
    campaign_sha256: str,
    event: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Append one hash-chained event after verifying the existing ledger."""

    if not _is_sha256(campaign_sha256):
        raise CampaignRuntimeError("INVALID_CAMPAIGN_SHA256")
    ledger_path = Path(path)
    verified = verify_event_ledger(
        ledger_path,
        campaign_sha256=campaign_sha256,
    )
    record: dict[str, Any] = {
        "schema_version": 1,
        "sequence": int(verified["record_count"]),
        "campaign_contract_sha256": campaign_sha256,
        "previous_hash": str(verified["tail_hash"]),
        "event": dict(event),
    }
    record["event_hash"] = _hash_payload(record, domain=_LEDGER_DOMAIN)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
    except OSError as exc:
        raise CampaignRuntimeError("LEDGER_APPEND_FAILED") from exc
    return record


def build_checkpoint_envelope(
    contract: FrozenCampaignContract,
    *,
    island_id: str,
    wave: int,
    restart_ordinal: int,
    evaluations: int,
    dehb_state_sha256: str,
    ledger_tail_hash: str,
    launch_contract_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Bind a DEHB state file to one exact train-only island and ledger tail."""

    if evaluations < 0:
        raise CampaignRuntimeError("NEGATIVE_CHECKPOINT_EVALUATIONS")
    if not _is_sha256(dehb_state_sha256) or not _is_sha256(ledger_tail_hash):
        raise CampaignRuntimeError("INVALID_CHECKPOINT_INPUT_HASH")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "island_id": island_id,
        "wave": wave,
        "restart_ordinal": restart_ordinal,
        "restart_seed": derive_restart_seed(
            contract,
            island_id=island_id,
            restart_ordinal=restart_ordinal,
        ),
        "evaluations": evaluations,
        "dehb_state_sha256": dehb_state_sha256,
        "ledger_tail_hash": ledger_tail_hash,
        "train_partition": contract.train_partition,
        "search_end": contract.search_end,
        "validation_opened": False,
        "locked_opened": False,
    }
    if launch_contract_sha256 is not None:
        if not _is_sha256(launch_contract_sha256):
            raise CampaignRuntimeError("INVALID_LAUNCH_CONTRACT_SHA256")
        payload["launch_contract_sha256"] = launch_contract_sha256
    payload["checkpoint_envelope_sha256"] = _hash_payload(
        payload,
        domain=_CHECKPOINT_DOMAIN,
    )
    return payload


def validate_checkpoint_envelope(
    contract: FrozenCampaignContract,
    envelope: Mapping[str, Any],
    *,
    expected_island_id: str,
    expected_launch_contract_sha256: str | None = None,
) -> None:
    """Fail closed before loading a checkpoint state file."""

    if envelope.get("validation_opened") is not False or envelope.get("locked_opened") is not False:
        raise CampaignRuntimeError("CHECKPOINT_BOUNDARY_OPEN")
    if envelope.get("campaign_contract_sha256") != contract.sha256:
        raise CampaignRuntimeError("CHECKPOINT_CAMPAIGN_MISMATCH")
    if expected_launch_contract_sha256 is not None and (
        envelope.get("launch_contract_sha256")
        != expected_launch_contract_sha256
    ):
        raise CampaignRuntimeError("CHECKPOINT_LAUNCH_CONTRACT_MISMATCH")
    if envelope.get("island_id") != expected_island_id:
        raise CampaignRuntimeError("CHECKPOINT_ISLAND_MISMATCH")
    if envelope.get("train_partition") != contract.train_partition:
        raise CampaignRuntimeError("CHECKPOINT_PARTITION_MISMATCH")
    if envelope.get("search_end") != contract.search_end:
        raise CampaignRuntimeError("CHECKPOINT_SEARCH_END_MISMATCH")
    preimage = {
        key: value
        for key, value in envelope.items()
        if key != "checkpoint_envelope_sha256"
    }
    expected_hash = _hash_payload(preimage, domain=_CHECKPOINT_DOMAIN)
    if envelope.get("checkpoint_envelope_sha256") != expected_hash:
        raise CampaignRuntimeError("CHECKPOINT_ENVELOPE_HASH_MISMATCH")
    expected_seed = derive_restart_seed(
        contract,
        island_id=expected_island_id,
        restart_ordinal=int(envelope["restart_ordinal"]),
    )
    if envelope.get("restart_seed") != expected_seed:
        raise CampaignRuntimeError("CHECKPOINT_RESTART_SEED_MISMATCH")


def _validate_worker_result(
    contract: FrozenCampaignContract,
    result: Mapping[str, Any],
    *,
    expected_payloads: Mapping[int, Mapping[str, Any]],
    launch_contract_sha256: str | None = None,
) -> tuple[int, str, list[Mapping[str, Any]]]:
    if result.get("validation_opened") is not False or result.get("locked_opened") is not False:
        raise CampaignRuntimeError("WORKER_BOUNDARY_OPEN")
    if result.get("campaign_contract_sha256") != contract.sha256:
        raise CampaignRuntimeError("WORKER_CAMPAIGN_MISMATCH")
    if launch_contract_sha256 is not None and (
        result.get("launch_contract_sha256") != launch_contract_sha256
    ):
        raise CampaignRuntimeError("WORKER_LAUNCH_CONTRACT_MISMATCH")
    job_index = int(result.get("job_index", -1))
    try:
        payload = expected_payloads[job_index]
    except KeyError as exc:
        raise CampaignRuntimeError(f"JOB_INDEX_OUT_OF_RANGE:{job_index}") from exc
    if result.get("job_id") != payload["job_id"]:
        raise CampaignRuntimeError("WORKER_JOB_ID_MISMATCH")
    if result.get("job_payload_sha256") != payload["payload_sha256"]:
        raise CampaignRuntimeError("WORKER_PAYLOAD_HASH_MISMATCH")
    rows = result.get("islands")
    if not isinstance(rows, list) or len(rows) != 2:
        raise CampaignRuntimeError("WORKER_ISLAND_ROWS_MISMATCH")
    expected_ids = {str(row["island_id"]) for row in payload["islands"]}
    actual_ids = {str(row.get("island_id")) for row in rows if isinstance(row, Mapping)}
    if actual_ids != expected_ids:
        raise CampaignRuntimeError("WORKER_ISLAND_ID_MISMATCH")
    expected_by_id = {str(row["island_id"]): row for row in payload["islands"]}
    normalized = [row for row in rows if isinstance(row, Mapping)]
    allowed_statuses = {"completed", "paused_at_runner_slice"}
    valid = True
    for row in normalized:
        expected = expected_by_id[str(row["island_id"])]
        if (
            row.get("lane_id") != expected["lane_id"]
            or int(row.get("replicate", -1)) != expected["replicate"]
            or int(row.get("restart_ordinal", -1)) != expected["restart_ordinal"]
            or row.get("status") not in allowed_statuses
            or not _is_sha256(row.get("checkpoint_sha256"))
            or int(row.get("evaluations", -1)) < 0
            or int(row.get("full_fidelity_evaluations", -1)) < 0
        ):
            valid = False
    if not valid:
        return job_index, "failed", normalized
    if any(row["status"] == "paused_at_runner_slice" for row in normalized):
        return job_index, "paused", normalized
    return job_index, "completed", normalized


def controller_decision(
    contract: FrozenCampaignContract,
    worker_results: Sequence[Mapping[str, Any]],
    *,
    wave: int,
    launch_contract_sha256: str | None = None,
    restart_ordinal: int | None = None,
    island_restart_ordinals: Mapping[str, int] | None = None,
    resume_island_ids: AbstractSet[str] | None = None,
    global_robustness: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Retry incomplete work, freeze a consensus winner, or open a diverse wave."""

    by_job: dict[int, tuple[str, list[Mapping[str, Any]]]] = {}
    matrices = build_shard_matrices(
        contract,
        wave=wave,
        restart_ordinal=wave if restart_ordinal is None else restart_ordinal,
        launch_contract_sha256=launch_contract_sha256,
        island_restart_ordinals=island_restart_ordinals,
        resume_island_ids=resume_island_ids,
    )
    expected_payloads = {
        int(payload["job_index"]): payload
        for shard in "ABC"
        for payload in matrices[shard]["include"]
    }
    for result in worker_results:
        job_index, state, islands = _validate_worker_result(
            contract,
            result,
            expected_payloads=expected_payloads,
            launch_contract_sha256=launch_contract_sha256,
        )
        if job_index in by_job:
            raise CampaignRuntimeError(f"DUPLICATE_WORKER_RESULT:{job_index}")
        by_job[job_index] = (state, islands)
    retry = [
        index
        for index in range(contract.job_count)
        if index not in by_job or by_job[index][0] == "failed"
    ]
    common: dict[str, Any] = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "wave": wave,
        "terminal_no_strategy": False,
        "validation_opened": False,
        "locked_opened": False,
    }
    if launch_contract_sha256 is not None:
        common["launch_contract_sha256"] = launch_contract_sha256
    if retry:
        return {
            **common,
            "action": "retry_jobs",
            "retry_job_indices": retry,
            "retry_job_payloads": [expected_payloads[index] for index in retry],
        }

    all_islands = [island for _, islands in by_job.values() for island in islands]
    budget_floor_complete = all(
        int(island.get("full_fidelity_evaluations", 0)) >= 1
        for island in all_islands
    )
    if global_robustness is not None:
        if (
            global_robustness.get("campaign_contract_sha256") != contract.sha256
            or global_robustness.get("validation_opened") is not False
            or global_robustness.get("locked_opened") is not False
        ):
            raise CampaignRuntimeError("GLOBAL_ROBUSTNESS_BINDING_INVALID")
        frozen = global_robustness.get("eligible_finalists")
        if not isinstance(frozen, list):
            raise CampaignRuntimeError("GLOBAL_ROBUSTNESS_FINALISTS_INVALID")
        eligible_global = [
            row
            for row in frozen
            if isinstance(row, Mapping)
            and row.get("train_freeze_eligible") is True
            and int(row.get("seed_consensus", 0)) >= 2
        ]
        if eligible_global and budget_floor_complete:
            best = min(
                eligible_global,
                key=lambda row: tuple(float(value) for value in row["archive_key"]),
            )
            return {
                **common,
                "action": "freeze_train_candidate",
                "strategy_fingerprint": str(best["strategy_fingerprint"]),
                "position_fingerprint": str(best["position_fingerprint"]),
                "lane_id": str(best["lane_id"]),
                "archive_key": list(best["archive_key"]),
                "seed_consensus": int(best["seed_consensus"]),
                "supporting_islands": list(best["supporting_islands"]),
                "candidate_frozen_before_validation": True,
                "train_robustness_gates_passed": True,
                "validation_gates_49_54_pending": True,
            }

    resume_ids_next = sorted(
        str(island["island_id"])
        for island in all_islands
        if island["status"] == "paused_at_runner_slice"
    )
    next_ordinals = {
        str(island["island_id"]): int(island["restart_ordinal"])
        + (0 if island["status"] == "paused_at_runner_slice" else 1)
        for island in all_islands
    }
    return {
        **common,
        "action": "dispatch_next_wave",
        "next_wave": wave + 1,
        "next_restart_ordinal": wave + 1,
        "next_island_restart_ordinals": dict(sorted(next_ordinals.items())),
        "resume_island_ids": resume_ids_next,
        "all_lanes_budget_floor_complete": budget_floor_complete,
    }


__all__ = [
    "CampaignRuntimeError",
    "append_ledger_event",
    "build_checkpoint_envelope",
    "build_job_payload",
    "build_shard_matrices",
    "controller_decision",
    "derive_restart_seed",
    "validate_checkpoint_envelope",
    "verify_event_ledger",
]
