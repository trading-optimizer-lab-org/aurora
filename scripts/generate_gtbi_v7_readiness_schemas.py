"""Generate the ten versioned GTBI V7 readiness record schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.records import write_schema_documents  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    paths = write_schema_documents(args.repository_root.resolve())
    print(
        json.dumps(
            {
                "schema_count": len(paths),
                "paths": [
                    path.relative_to(args.repository_root.resolve()).as_posix()
                    for path in paths
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
