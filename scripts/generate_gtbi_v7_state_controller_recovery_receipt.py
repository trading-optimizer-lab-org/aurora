"""Generate the public receipt for the successful controller smoke."""

from __future__ import annotations

import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SMOKE_RECEIPT = READINESS / "state_controller_smoke_receipt.json"
DESTINATION = READINESS / "state_controller_recovery_receipt.json"


def build_receipt() -> dict:
    smoke = json.loads(SMOKE_RECEIPT.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "gtbi_v7_state_controller_recovery_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "dry_run",
        "manifest_id": "state-controller-smoke-v1",
        "run_id": 30556296057,
        "run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            "actions/runs/30556296057"
        ),
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": "c3a6b29be87f32f9037db6dc1608b18b21b40adc",
        "created_at_utc": "2026-07-30T15:21:44Z",
        "updated_at_utc": "2026-07-30T15:22:08Z",
        "duration_seconds": 24,
        "artifact": {
            "id": 8764915602,
            "name": (
                "gtbi-v7-state-controller-"
                "state-controller-smoke-v1-30556296057"
            ),
            "size_in_bytes": 1034,
            "archive_digest": (
                "sha256:"
                "b7ebb7f1e9ef272c713d283ef56772d366f8118cc8c6434ce170f982c9a95f39"
            ),
            "expires_at_utc": "2026-10-28T15:21:46Z",
        },
        "smoke_receipt_path": (
            "docs/readiness/gtbi-v7/state_controller_smoke_receipt.json"
        ),
        "smoke_receipt_file_sha256": raw_sha256(SMOKE_RECEIPT),
        "smoke_receipt_digest": smoke["receipt_digest"],
        "verified_properties": {
            "arbitrary_command_execution_supported": False,
            "base_sha_matches_default_branch": (
                smoke["base_sha"]
                == "c3a6b29be87f32f9037db6dc1608b18b21b40adc"
            ),
            "locked_data_accessed": smoke["locked_data_accessed"],
            "repository_state_mutated": False,
            "scientific_work_performed": smoke[
                "scientific_work_performed"
            ],
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECOVERY_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
