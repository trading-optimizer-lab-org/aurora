from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.completion import (
    build_completion_manifest,
    write_completion_outputs,
)
from aurora.research.openap_93.registry import load_signal_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-doc", type=Path, required=True)
    parser.add_argument(
        "--signals-93", type=Path, default=Path("config/openap_93/signals_93.yaml")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission("OpenAP 181 completion audit")
    signal_doc = pd.read_csv(args.signal_doc)
    registry = load_signal_registry(args.signals_93)
    manifest = build_completion_manifest(signal_doc, registry_93=registry)
    write_completion_outputs(manifest, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
