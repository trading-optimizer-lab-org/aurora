"""Apply or validate the deterministic GTBI V7 PR-1 reconciliation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.formal_genesis import (  # noqa: E402
    validate_formal_genesis_records,
    write_formal_genesis_records,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.apply:
        write_formal_genesis_records(root)
    result = validate_formal_genesis_records(root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
