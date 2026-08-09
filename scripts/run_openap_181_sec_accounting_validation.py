from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.sec_accounting_batch import (
    write_sec_accounting_validation_outputs,
)


_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _read_gate_evidence(
    path: Path,
    *,
    expected_gate: str,
    expected_run_url: str,
    expected_artifact: str,
    expected_commit: str,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{expected_gate} evidence must be a JSON object")
    required = {
        "gate",
        "verified",
        "blocking_reason",
        "verification_method",
        "evidence_run_url",
        "evidence_artifact",
        "verification_commit",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"{expected_gate} evidence is missing fields: {missing}")
    if payload["gate"] != expected_gate:
        raise ValueError(f"Expected {expected_gate} gate evidence")
    if not isinstance(payload["verified"], bool):
        raise ValueError(f"{expected_gate} verified must be a boolean")
    for field in (
        "blocking_reason",
        "verification_method",
        "evidence_run_url",
        "evidence_artifact",
        "verification_commit",
    ):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"{expected_gate} evidence requires non-empty {field}")
        payload[field] = payload[field].strip()
    if not payload["evidence_run_url"].startswith("https://"):
        raise ValueError(f"{expected_gate} evidence requires an HTTPS run URL")
    if not _COMMIT_RE.fullmatch(payload["verification_commit"]):
        raise ValueError(f"{expected_gate} evidence requires a 40-character commit")
    if payload["evidence_run_url"] != expected_run_url:
        raise ValueError(f"{expected_gate} evidence run URL does not match this run")
    if payload["evidence_artifact"] != expected_artifact:
        raise ValueError(f"{expected_gate} evidence artifact does not match this run")
    if payload["verification_commit"] != expected_commit:
        raise ValueError(f"{expected_gate} evidence commit does not match this run")
    blocker = payload["blocking_reason"]
    if payload["verified"] and blocker != "none":
        raise ValueError(f"Verified {expected_gate} evidence must use blocker 'none'")
    if not payload["verified"] and blocker == "none":
        raise ValueError(f"Blocked {expected_gate} evidence requires a blocker")
    return payload


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 SEC accounting validation"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--expected-universe", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--point-in-time-evidence", type=Path, required=True)
    parser.add_argument("--identity-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument(
        "--evidence-artifact",
        default="openap-181-sec-accounting-validation",
    )
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    if not _COMMIT_RE.fullmatch(args.implementation_commit):
        raise ValueError("Implementation commit must contain exactly 40 hex characters")
    point_in_time = _read_gate_evidence(
        args.point_in_time_evidence,
        expected_gate="point_in_time",
        expected_run_url=args.evidence_run_url,
        expected_artifact=args.evidence_artifact,
        expected_commit=args.implementation_commit,
    )
    identity = _read_gate_evidence(
        args.identity_evidence,
        expected_gate="identity",
        expected_run_url=args.evidence_run_url,
        expected_artifact=args.evidence_artifact,
        expected_commit=args.implementation_commit,
    )
    write_sec_accounting_validation_outputs(
        pd.read_csv(args.observations, low_memory=False),
        pd.read_csv(args.reference, low_memory=False),
        pd.read_csv(args.expected_universe, low_memory=False),
        pd.read_csv(args.source_manifest, low_memory=False),
        args.output_dir,
        point_in_time_verified=point_in_time["verified"],
        identity_verified=identity["verified"],
        evidence_run_url=args.evidence_run_url,
        evidence_artifact=args.evidence_artifact,
        implementation_commit=args.implementation_commit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    gate_evidence = {
        "identity": identity,
        "point_in_time": point_in_time,
    }
    (args.output_dir / "sec_accounting_batch_gate_evidence.json").write_text(
        json.dumps(gate_evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
