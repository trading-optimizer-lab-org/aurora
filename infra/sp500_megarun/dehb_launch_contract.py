"""Immutable launch receipt binding one DEHB campaign to exact GitHub artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_technical_evidence import (
    validate_technical_evidence,
)


class LaunchContractError(ValueError):
    """Raised when exact launch lineage or hidden-data boundaries cannot be proved."""


@dataclass(frozen=True)
class FrozenLaunchContract:
    source_path: Path
    sha256: str
    raw: Mapping[str, Any]
    repository: str
    campaign_contract_sha256: str
    code_commit_sha: str
    runtime_input_run_id: str
    runtime_input_artifact_name: str
    runtime_input_artifact_digest_sha256: str
    runtime_input_aggregate_sha256: str
    runtime_scientific_input_binding_sha256: str
    technical_evidence_run_id: str
    technical_evidence_artifact_name: str
    technical_evidence_artifact_digest_sha256: str
    technical_evidence_sha256: str
    technical_evidence_github_sha: str
    validation_opened: bool
    locked_opened: bool
    validation_partition_mounted: bool
    locked_partition_mounted: bool


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LaunchContractError("LAUNCH_VALUE_NOT_CANONICAL_JSON") from exc


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LaunchContractError(f"LAUNCH_MAPPING_REQUIRED:{field}")
    return value


def _sha256(value: object, field: str) -> str:
    text = str(value).removeprefix("sha256:")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise LaunchContractError(f"LAUNCH_SHA256_INVALID:{field}")
    return text


def _commit_sha(value: object) -> str:
    text = str(value)
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise LaunchContractError("LAUNCH_CODE_COMMIT_SHA_INVALID")
    return text


def _run_id(value: object, field: str) -> str:
    text = str(value)
    if not text.isascii() or not text.isdigit() or int(text) <= 0:
        raise LaunchContractError(f"LAUNCH_RUN_ID_INVALID:{field}")
    return text


def _load_technical_evidence(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchContractError("TECHNICAL_EVIDENCE_READ_FAILED") from exc
    return _mapping(value, "technical_evidence")


def _validate_artifact_name(name: object, *, prefix: str, run_id: str) -> str:
    text = str(name)
    if text != f"{prefix}{run_id}":
        raise LaunchContractError("LAUNCH_ARTIFACT_NAME_MISMATCH")
    return text


def build_launch_contract(
    campaign: Any,
    *,
    code_commit_sha: str,
    repository: str,
    runtime_input_pack: Path,
    runtime_input_run_id: str,
    runtime_input_artifact_name: str,
    runtime_input_artifact_digest_sha256: str,
    technical_evidence_path: Path,
    technical_evidence_run_id: str,
    technical_evidence_artifact_name: str,
    technical_evidence_artifact_digest_sha256: str,
    output_path: Path,
) -> FrozenLaunchContract:
    """Build a deterministic receipt after verifying exact train and system evidence."""

    code_sha = _commit_sha(code_commit_sha)
    runtime_run = _run_id(runtime_input_run_id, "runtime_inputs")
    technical_run = _run_id(technical_evidence_run_id, "technical_evidence")
    runtime_name = _validate_artifact_name(
        runtime_input_artifact_name,
        prefix="sp500-megarun-dehb-runtime-inputs-",
        run_id=runtime_run,
    )
    technical_name = _validate_artifact_name(
        technical_evidence_artifact_name,
        prefix="sp500-megarun-official-dehb-smoke-",
        run_id=technical_run,
    )
    runtime_manifest = verify_runtime_input_pack(
        Path(runtime_input_pack),
        expected_scientific_input_binding_sha256=(
            scientific_input_binding_sha256(campaign)
        ),
    )
    if (
        runtime_manifest.get("source_run_id") != campaign.train_source_run_id
        or runtime_manifest.get("train_artifact_digest_sha256")
        != campaign.train_artifact_digest_sha256
        or runtime_manifest.get("train_snapshot_manifest_sha256")
        != campaign.train_snapshot_manifest_sha256
        or runtime_manifest.get("train_spy_sha256") != campaign.train_spy_sha256
    ):
        raise LaunchContractError("RUNTIME_INPUT_CAMPAIGN_LINEAGE_MISMATCH")
    technical = _load_technical_evidence(technical_evidence_path)
    validate_technical_evidence(technical, campaign_sha256=campaign.sha256)
    if technical.get("github_sha") != code_sha:
        raise LaunchContractError("TECHNICAL_EVIDENCE_CODE_MISMATCH")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "launch_id": "sp500-megarun-official-dehb-launch-v1",
        "repository": str(repository),
        "campaign_contract_sha256": campaign.sha256,
        "code_commit_sha": code_sha,
        "runtime_inputs": {
            "workflow_run_id": runtime_run,
            "artifact_name": runtime_name,
            "artifact_digest_sha256": _sha256(
                runtime_input_artifact_digest_sha256, "runtime_artifact"
            ),
            "aggregate_sha256": _sha256(
                runtime_manifest.get("aggregate_sha256"), "runtime_aggregate"
            ),
            "scientific_input_binding_sha256": _sha256(
                runtime_manifest.get("scientific_input_binding_sha256"),
                "scientific_input_binding",
            ),
        },
        "technical_evidence": {
            "workflow_run_id": technical_run,
            "artifact_name": technical_name,
            "artifact_digest_sha256": _sha256(
                technical_evidence_artifact_digest_sha256,
                "technical_artifact",
            ),
            "technical_evidence_sha256": _sha256(
                technical.get("technical_evidence_sha256"),
                "technical_evidence",
            ),
            "github_sha": _commit_sha(technical.get("github_sha")),
        },
        "boundaries": {
            "validation_opened": False,
            "locked_opened": False,
            "validation_partition_mounted": False,
            "locked_partition_mounted": False,
        },
    }
    payload["launch_contract_sha256"] = _canonical_hash(payload)
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_and_validate_launch_contract(
        target,
        campaign,
        runtime_input_pack=runtime_input_pack,
        technical_evidence_path=technical_evidence_path,
        expected_code_commit_sha=code_sha,
    )


def load_and_validate_launch_contract(
    path: Path,
    campaign: Any,
    *,
    runtime_input_pack: Path | None = None,
    technical_evidence_path: Path | None = None,
    expected_code_commit_sha: str | None = None,
) -> FrozenLaunchContract:
    """Load a launch receipt and fail closed on any mismatch or opened tier."""

    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchContractError("LAUNCH_CONTRACT_READ_FAILED") from exc
    raw = _mapping(value, "root")
    boundaries = _mapping(raw.get("boundaries"), "boundaries")
    closed_flags = (
        "validation_opened",
        "locked_opened",
        "validation_partition_mounted",
        "locked_partition_mounted",
    )
    if any(boundaries.get(flag) is not False for flag in closed_flags):
        raise LaunchContractError("LAUNCH_BOUNDARY_OPEN")
    expected_hash = raw.get("launch_contract_sha256")
    preimage = {
        key: item for key, item in raw.items() if key != "launch_contract_sha256"
    }
    if expected_hash != _canonical_hash(preimage):
        raise LaunchContractError("LAUNCH_CONTRACT_SHA256_MISMATCH")
    if (
        raw.get("schema_version") != 1
        or raw.get("launch_id") != "sp500-megarun-official-dehb-launch-v1"
        or raw.get("campaign_contract_sha256") != campaign.sha256
    ):
        raise LaunchContractError("LAUNCH_CAMPAIGN_MISMATCH")
    code_sha = _commit_sha(raw.get("code_commit_sha"))
    if expected_code_commit_sha is not None and code_sha != _commit_sha(
        expected_code_commit_sha
    ):
        raise LaunchContractError("LAUNCH_CODE_COMMIT_MISMATCH")
    runtime = _mapping(raw.get("runtime_inputs"), "runtime_inputs")
    technical = _mapping(raw.get("technical_evidence"), "technical_evidence")
    runtime_run = _run_id(runtime.get("workflow_run_id"), "runtime_inputs")
    technical_run = _run_id(
        technical.get("workflow_run_id"), "technical_evidence"
    )
    runtime_name = _validate_artifact_name(
        runtime.get("artifact_name"),
        prefix="sp500-megarun-dehb-runtime-inputs-",
        run_id=runtime_run,
    )
    technical_name = _validate_artifact_name(
        technical.get("artifact_name"),
        prefix="sp500-megarun-official-dehb-smoke-",
        run_id=technical_run,
    )
    scientific_hash = _sha256(
        runtime.get("scientific_input_binding_sha256"),
        "scientific_input_binding",
    )
    if scientific_hash != scientific_input_binding_sha256(campaign):
        raise LaunchContractError("LAUNCH_SCIENTIFIC_INPUT_MISMATCH")
    aggregate = _sha256(runtime.get("aggregate_sha256"), "runtime_aggregate")
    technical_hash = _sha256(
        technical.get("technical_evidence_sha256"), "technical_evidence"
    )
    if _commit_sha(technical.get("github_sha")) != code_sha:
        raise LaunchContractError("TECHNICAL_EVIDENCE_CODE_MISMATCH")
    if runtime_input_pack is not None:
        verify_runtime_input_pack(
            Path(runtime_input_pack),
            expected_scientific_input_binding_sha256=scientific_hash,
            expected_aggregate_sha256=aggregate,
        )
    if technical_evidence_path is not None:
        evidence = _load_technical_evidence(technical_evidence_path)
        validate_technical_evidence(evidence, campaign_sha256=campaign.sha256)
        if (
            evidence.get("technical_evidence_sha256") != technical_hash
            or evidence.get("github_sha") != code_sha
        ):
            raise LaunchContractError("TECHNICAL_EVIDENCE_CONTENT_MISMATCH")
    return FrozenLaunchContract(
        source_path=source,
        sha256=str(expected_hash),
        raw=raw,
        repository=str(raw.get("repository")),
        campaign_contract_sha256=campaign.sha256,
        code_commit_sha=code_sha,
        runtime_input_run_id=runtime_run,
        runtime_input_artifact_name=runtime_name,
        runtime_input_artifact_digest_sha256=_sha256(
            runtime.get("artifact_digest_sha256"), "runtime_artifact"
        ),
        runtime_input_aggregate_sha256=aggregate,
        runtime_scientific_input_binding_sha256=scientific_hash,
        technical_evidence_run_id=technical_run,
        technical_evidence_artifact_name=technical_name,
        technical_evidence_artifact_digest_sha256=_sha256(
            technical.get("artifact_digest_sha256"), "technical_artifact"
        ),
        technical_evidence_sha256=technical_hash,
        technical_evidence_github_sha=code_sha,
        validation_opened=False,
        locked_opened=False,
        validation_partition_mounted=False,
        locked_partition_mounted=False,
    )


__all__ = [
    "FrozenLaunchContract",
    "LaunchContractError",
    "build_launch_contract",
    "load_and_validate_launch_contract",
]
