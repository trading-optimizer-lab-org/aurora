from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.implementation_status import (
    build_documentary_blocker_evidence,
    build_twelve_data_credential_blocker_evidence,
    merge_generated_and_explicit_evidence,
    write_implementation_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--documentary-blockers", action="store_true")
    parser.add_argument("--twelve-data-credential-check", action="store_true")
    parser.add_argument("--twelve-data-credential-available", action="store_true")
    parser.add_argument("--evidence-run-url")
    parser.add_argument("--evidence-artifact")
    parser.add_argument("--implementation-commit")
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 implementation status"
    )
    resolution = pd.read_csv(args.resolution)
    generated_evidence_frames = []
    explicit_evidence_frames = []
    evidence_requested = (
        args.documentary_blockers or args.twelve_data_credential_check
    )
    if args.twelve_data_credential_available and not args.twelve_data_credential_check:
        raise ValueError(
            "Twelve Data credential availability requires an explicit credential check"
        )
    if evidence_requested:
        if not all(
            (
                args.evidence_run_url,
                args.evidence_artifact,
                args.implementation_commit,
            )
        ):
            raise ValueError(
                "Generated blockers require run URL, artifact and commit evidence"
            )
    if args.documentary_blockers:
        generated_evidence_frames.append(
            build_documentary_blocker_evidence(
                resolution,
                evidence_run_url=args.evidence_run_url,
                evidence_artifact=args.evidence_artifact,
                implementation_commit=args.implementation_commit,
            )
        )
    if args.twelve_data_credential_check:
        generated_evidence_frames.append(
            build_twelve_data_credential_blocker_evidence(
                resolution,
                credential_available=args.twelve_data_credential_available,
                evidence_run_url=args.evidence_run_url,
                evidence_artifact=args.evidence_artifact,
                implementation_commit=args.implementation_commit,
            )
        )
    for evidence_path in args.evidence:
        explicit_evidence_frames.append(pd.read_csv(evidence_path))
    evidence = merge_generated_and_explicit_evidence(
        generated_evidence_frames,
        explicit_evidence_frames,
    )
    write_implementation_outputs(
        pd.read_csv(args.manifest),
        resolution,
        args.output_dir,
        evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
