"""Regenerate the deterministic GTBI V7 locked-evidence public report."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes  # noqa: E402
from infra.gtbi_v7_readiness.locked_evidence import (  # noqa: E402
    PRESERVATION_REPORT_PATH,
    build_locked_evidence_preservation_report,
)


def main() -> int:
    """Write the report and print a small machine-readable receipt."""

    report = build_locked_evidence_preservation_report()
    PRESERVATION_REPORT_PATH.write_bytes(canonical_bytes(report) + b"\n")
    print(
        json.dumps(
            {
                "report": str(PRESERVATION_REPORT_PATH),
                "report_digest": report["report_digest"],
                "source_runs": len(report["source_run_ids"]),
                "preserved_remote_artifacts": len(
                    report["preserved_remote_artifacts"]
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
