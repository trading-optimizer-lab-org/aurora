from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.implementation_status import (
    build_documentary_blocker_evidence,
    write_implementation_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--documentary-blockers", action="store_true")
    parser.add_argument("--evidence-run-url")
    parser.add_argument("--evidence-artifact")
    parser.add_argument("--implementation-commit")
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 implementation status"
    )
    resolution = pd.read_csv(args.resolution)
    evidence_frames = []
    if args.documentary_blockers:
        if not all(
            (
                args.evidence_run_url,
                args.evidence_artifact,
                args.implementation_commit,
            )
        ):
            raise ValueError(
                "Documentary blockers require run URL, artifact and commit evidence"
            )
        evidence_frames.append(
            build_documentary_blocker_evidence(
                resolution,
                evidence_run_url=args.evidence_run_url,
                evidence_artifact=args.evidence_artifact,
                implementation_commit=args.implementation_commit,
            )
        )
    if args.evidence is not None:
        evidence_frames.append(pd.read_csv(args.evidence))
    evidence = (
        pd.concat(evidence_frames, ignore_index=True)
        if evidence_frames
        else None
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
