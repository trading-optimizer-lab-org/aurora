"""Regenerate the deterministic owner-controlled G0 foundation report."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes  # noqa: E402
from infra.gtbi_v7_readiness.g0_foundation import (  # noqa: E402
    FOUNDATION_REPORT_PATH,
    build_g0_foundation_report,
)


def main() -> int:
    report = build_g0_foundation_report()
    FOUNDATION_REPORT_PATH.write_bytes(canonical_bytes(report) + b"\n")
    print(
        json.dumps(
            {
                "g0_green_claimed": report["g0_green_claimed"],
                "pending_g0_task_ids": report["pending_g0_task_ids"],
                "report": str(FOUNDATION_REPORT_PATH),
                "report_digest": report["report_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
