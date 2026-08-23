#!/usr/bin/env python3
"""Bind one fresh terminal controls receipt into the pure finalizer input."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_terminal_adapter import (
    bind_terminal_controls,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind fresh terminal controls to prepared catalog evidence."
    )
    parser.add_argument("--prepared-root", required=True, type=Path)
    parser.add_argument("--terminal-controls", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        envelope = bind_terminal_controls(
            prepared_root=args.prepared_root,
            terminal_controls_path=args.terminal_controls,
            output_dir=args.output_dir,
        )
        path = args.output_dir / "finalizer-envelope.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if args.github_output is not None:
            if args.github_output.is_symlink():
                raise ValueError("CATALOG_TERMINAL_GITHUB_OUTPUT_INVALID")
            with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"envelope_sha256={digest}\n")
                stream.write(
                    "authority_id="
                    f"{envelope.final_evidence.authority_id}\n"
                )
        print(
            json.dumps(
                {
                    "authority_id": str(envelope.final_evidence.authority_id),
                    "envelope_sha256": digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(f"CATALOG_TERMINAL_DECISION_INPUT_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
