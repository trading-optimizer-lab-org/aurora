"""Prepare a date-bounded source dataset for the stock protocol workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.research.stock_protocol.dataset import build_research_pack
from aurora.research.stock_protocol.manifest import load_protocol_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_protocol_manifest(args.manifest)
    audit = build_research_pack(args.source_root, args.output_root, manifest)
    print(audit.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
