"""Validate the owner-controlled stage-two contract without dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.stage_two_protection import (
    REQUIRED_CHECK_CONTEXT,
    build_policy,
)
from scripts.generate_gtbi_v7_codeowners_contract import (
    CODEOWNERS,
    build_codeowners,
    validate_contract,
)

POLICY = ROOT / "config/gtbi/governance/stage_two_owner_controlled_protection.json"
WORKFLOW = ROOT / ".github/workflows/gtbi-v7-stage-two-required.yml"


def validate() -> dict[str, Any]:
    errors: list[str] = []
    checked_policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if POLICY.read_bytes() != canonical_bytes(checked_policy) + b"\n":
        errors.append("stage-two policy is not canonical JSON")
    if checked_policy != build_policy():
        errors.append("stage-two policy differs from generated policy")
    try:
        validate_contract()
    except ValueError as exc:
        errors.append(f"CODEOWNERS contract invalid: {exc}")
    if CODEOWNERS.read_bytes() != build_codeowners():
        errors.append("CODEOWNERS differs from generated owner routing")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_fragments = (
        "pull_request:",
        f"name: {REQUIRED_CHECK_CONTEXT}",
        "runs-on: ubuntu-24.04",
        "permissions:\n  contents: read",
    )
    for fragment in required_fragments:
        if fragment not in workflow:
            errors.append(f"required workflow fragment missing: {fragment}")
    for forbidden in ("paths:", "self-hosted", "C:\\"):
        if forbidden in workflow:
            errors.append(f"forbidden workflow fragment present: {forbidden}")
    return {
        "schema_version": "gtbi_v7_stage_two_contract_validation_v1",
        "valid": not errors,
        "errors": errors,
        "required_check_context": REQUIRED_CHECK_CONTEXT,
    }


def main() -> int:
    report = validate()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
