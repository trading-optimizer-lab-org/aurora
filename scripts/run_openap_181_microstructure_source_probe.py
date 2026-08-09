from __future__ import annotations

import argparse
from pathlib import Path

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.microstructure_batch import (
    run_microstructure_source_probe,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument("--evidence-artifact", required=True)
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 microstructure source probe"
    )
    run_microstructure_source_probe(
        output_dir=args.output_dir,
        evidence_run_url=args.evidence_run_url,
        evidence_artifact=args.evidence_artifact,
        implementation_commit=args.implementation_commit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
