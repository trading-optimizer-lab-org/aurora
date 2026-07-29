"""Generate the provisional, fail-closed GTBI V7 readiness projections."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.genesis import (  # noqa: E402
    validate_initial_records,
    write_initial_records,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=ROOT,
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    paths = write_initial_records(root)
    validate_initial_records(root)
    for path in paths:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
