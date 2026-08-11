"""Build the exact launch receipt on GitHub before any DEHB worker starts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_launch_contract import build_launch_contract


def _require_github_only_execution(operation: str) -> None:
    """Keep this no-dependency preflight fail-closed outside GitHub Actions."""

    if os.environ.get("GITHUB_ACTIONS", "").casefold() == "true":
        return
    raise RuntimeError(
        "Run local bloqueado por politica GitHub-only de GTBI V7. "
        f"Operacion: {operation}. Debe ejecutarse en GitHub Actions."
    )


def main() -> int:
    _require_github_only_execution("SP500_MEGARUN_DEHB_LAUNCH_PREFLIGHT")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--code-commit-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--runtime-input-run-id", required=True)
    parser.add_argument("--runtime-input-artifact-name", required=True)
    parser.add_argument("--runtime-input-artifact-digest", required=True)
    parser.add_argument("--technical-evidence", type=Path, required=True)
    parser.add_argument("--technical-evidence-run-id", required=True)
    parser.add_argument("--technical-evidence-artifact-name", required=True)
    parser.add_argument("--technical-evidence-artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    launch = build_launch_contract(
        campaign,
        code_commit_sha=args.code_commit_sha,
        repository=args.repository,
        runtime_input_pack=args.runtime_input_pack,
        runtime_input_run_id=args.runtime_input_run_id,
        runtime_input_artifact_name=args.runtime_input_artifact_name,
        runtime_input_artifact_digest_sha256=(
            args.runtime_input_artifact_digest
        ),
        technical_evidence_path=args.technical_evidence,
        technical_evidence_run_id=args.technical_evidence_run_id,
        technical_evidence_artifact_name=(
            args.technical_evidence_artifact_name
        ),
        technical_evidence_artifact_digest_sha256=(
            args.technical_evidence_artifact_digest
        ),
        output_path=args.output,
    )
    github_output = args.github_output
    if github_output is None and os.environ.get("GITHUB_OUTPUT"):
        github_output = Path(os.environ["GITHUB_OUTPUT"])
    if github_output is not None:
        with github_output.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"launch_contract_sha256={launch.sha256}\n")
    print(
        json.dumps(
            {
                "launch_contract_sha256": launch.sha256,
                "code_commit_sha": launch.code_commit_sha,
                "runtime_input_run_id": launch.runtime_input_run_id,
                "technical_evidence_run_id": launch.technical_evidence_run_id,
                "validation_opened": False,
                "locked_opened": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
