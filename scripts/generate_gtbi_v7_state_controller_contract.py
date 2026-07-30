"""Generate the public contract manifest for the readiness controller."""

from __future__ import annotations

from pathlib import Path

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.readiness_state_controller.engine import (
    CONTROLLER_VERSION,
    MUTABLE_FILENAMES,
)

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = (
    ROOT / "docs/readiness/gtbi-v7/state_controller_manifest.json"
)
SOURCE_PATHS = (
    ".github/workflows/gtbi-v7-readiness-state-controller.yml",
    "infra/readiness_state_controller/engine.py",
    "infra/readiness_state_controller/policy.py",
    "infra/readiness_state_controller/schemas.py",
    "scripts/run_gtbi_v7_readiness_state_controller.py",
)


def build_manifest() -> dict:
    manifest = {
        "schema_version": "gtbi_v7_state_controller_manifest_v1",
        "controller_version": CONTROLLER_VERSION,
        "workflow": "gtbi-v7-readiness-state-controller.yml",
        "workflow_trigger": "workflow_dispatch_only",
        "runner": "ubuntu-24.04",
        "repository_permissions": {"contents": "write"},
        "modes": ["apply", "dry_run"],
        "reviewed_manifest_directory": (
            "docs/readiness/gtbi-v7/transition_manifests"
        ),
        "mutable_readiness_files": [
            f"docs/readiness/gtbi-v7/{filename}"
            for filename in MUTABLE_FILENAMES
        ],
        "source_sha256": {
            path: raw_sha256(ROOT / path) for path in SOURCE_PATHS
        },
        "security_properties": {
            "arbitrary_command_execution_supported": False,
            "arbitrary_evidence_paths_supported": False,
            "external_auditor_required": False,
            "external_custodian_required": False,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "self_hosted_runner_used": False,
            "windows_local_path_used": False,
        },
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_manifest()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
