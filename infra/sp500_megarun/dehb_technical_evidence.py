"""System-level reproducibility gates for the official DEHB mega-run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from aurora.infra.sp500_megarun.dehb_campaign_runtime import (
    build_checkpoint_envelope,
    build_job_payload,
    controller_decision,
    validate_checkpoint_envelope,
)
from aurora.infra.sp500_megarun.dehb_job_runner import (
    DehbJobRunnerError,
    load_verified_job_payload,
)
from aurora.infra.sp500_megarun.dehb_official_smoke import (
    validate_official_smoke_report,
)


class TechnicalEvidenceError(ValueError):
    """Raised when system reproducibility evidence is open or incomplete."""


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fault_injection_receipt(contract: Any, work_dir: Path) -> Mapping[str, bool]:
    root = Path(work_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise TechnicalEvidenceError("FAULT_WORK_DIR_MUST_START_EMPTY")
    root.mkdir(parents=True, exist_ok=True)

    retry = controller_decision(contract, [], wave=0)
    controller_retries = (
        retry.get("action") == "retry_jobs"
        and retry.get("retry_job_indices") == list(range(contract.job_count))
        and retry.get("terminal_no_strategy") is False
    )

    payload = dict(
        build_job_payload(
            contract,
            job_index=0,
            wave=0,
            restart_ordinal=0,
        )
    )
    payload["wave"] = 99
    payload_path = root / "tampered_job_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_verified_job_payload(payload_path)
    except DehbJobRunnerError as exc:
        payload_rejected = "JOB_PAYLOAD_SHA256_MISMATCH" in str(exc)
    else:
        payload_rejected = False

    envelope = build_checkpoint_envelope(
        contract,
        island_id="F001-R1",
        wave=0,
        restart_ordinal=0,
        evaluations=64,
        dehb_state_sha256="d" * 64,
        ledger_tail_hash="e" * 64,
    )
    changed = dict(envelope)
    changed["validation_opened"] = True
    try:
        validate_checkpoint_envelope(
            contract,
            changed,
            expected_island_id="F001-R1",
        )
    except ValueError as exc:
        checkpoint_rejected = "CHECKPOINT_BOUNDARY_OPEN" in str(exc)
    else:
        checkpoint_rejected = False
    return {
        "controller_retries_missing_jobs": bool(controller_retries),
        "tampered_job_payload_rejected": bool(payload_rejected),
        "tampered_checkpoint_rejected": bool(checkpoint_rejected),
    }


def build_technical_evidence(
    contract: Any,
    *,
    official_report_path: Path,
    work_dir: Path,
    github_sha: str,
) -> Mapping[str, Any]:
    """Combine official 1/2/4-worker, resume, and injected-failure evidence."""

    report_path = Path(official_report_path).resolve()
    try:
        report = json.loads(report_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TechnicalEvidenceError("OFFICIAL_SMOKE_REPORT_INVALID") from exc
    if not isinstance(report, Mapping):
        raise TechnicalEvidenceError("OFFICIAL_SMOKE_REPORT_NOT_MAPPING")
    validate_official_smoke_report(report)
    faults = _fault_injection_receipt(contract, work_dir)
    if not all(faults.values()):
        raise TechnicalEvidenceError("FAULT_INJECTION_GATE_FAILED")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "github_sha": github_sha,
        "official_smoke_report_sha256": _sha256_file(report_path),
        "official_smoke": {
            "official_dehb_version": report["official_dehb_version"],
            "configspace_version": report["configspace_version"],
            "worker_equivalence_1_2_4": report["worker_equivalence_1_2_4"],
            "checkpoint_resume_exact": report["checkpoint_resume_exact"],
            "forbidden_config_rejection_safe": report[
                "forbidden_config_rejection_safe"
            ],
            "f015_parameter_grid_finite": report[
                "f015_parameter_grid_finite"
            ],
            "actual_four_worker_run": report["actual_four_worker_run"],
        },
        "fault_injection": dict(faults),
        "gates": {
            "55": {
                "status": "PASS",
                "evidence": "official_smoke.worker_equivalence_1_2_4",
            },
            "56": {
                "status": "PASS",
                "evidence": "official_smoke.checkpoint_resume_exact",
            },
            "60": {
                "status": "PASS",
                "evidence": "fault_injection",
            },
        },
        "validation_opened": False,
        "locked_opened": False,
    }
    payload["technical_evidence_sha256"] = _canonical_hash(payload)
    return payload


def validate_technical_evidence(
    evidence: Mapping[str, Any],
    *,
    campaign_sha256: str,
) -> None:
    """Fail closed unless gates 55, 56 and 60 are hash-bound and closed."""

    if (
        evidence.get("validation_opened") is not False
        or evidence.get("locked_opened") is not False
    ):
        raise TechnicalEvidenceError("TECHNICAL_EVIDENCE_BOUNDARY_OPEN")
    if evidence.get("campaign_contract_sha256") != campaign_sha256:
        raise TechnicalEvidenceError("TECHNICAL_EVIDENCE_CAMPAIGN_MISMATCH")
    gates = evidence.get("gates")
    if not isinstance(gates, Mapping) or any(
        not isinstance(gates.get(gate_id), Mapping)
        or gates[gate_id].get("status") != "PASS"
        for gate_id in ("55", "56", "60")
    ):
        raise TechnicalEvidenceError("TECHNICAL_EVIDENCE_GATE_FAILED")
    expected_hash = evidence.get("technical_evidence_sha256")
    preimage = {
        key: value
        for key, value in evidence.items()
        if key != "technical_evidence_sha256"
    }
    if expected_hash != _canonical_hash(preimage):
        raise TechnicalEvidenceError("TECHNICAL_EVIDENCE_SHA256_MISMATCH")


__all__ = [
    "TechnicalEvidenceError",
    "build_technical_evidence",
    "validate_technical_evidence",
]
