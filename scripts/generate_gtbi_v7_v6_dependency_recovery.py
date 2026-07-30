"""Generate the canonical GTBI V6 dependency recovery evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes  # noqa: E402
from infra.gtbi_v7_readiness.v6_dependency_recovery import (  # noqa: E402
    RECOVERY_REPORT_PATH,
    build_dependency_recovery_report,
)
from scripts.generate_gtbi_v7_v6_durable_preservation import (  # noqa: E402
    SCIENTIFIC_MANIFEST_PATH,
    build_scientific_manifest,
)


def main() -> int:
    report = build_dependency_recovery_report()
    manifest = build_scientific_manifest()
    RECOVERY_REPORT_PATH.write_bytes(canonical_bytes(report) + b"\n")
    SCIENTIFIC_MANIFEST_PATH.write_bytes(canonical_bytes(manifest) + b"\n")
    print(
        json.dumps(
            {
                "recovery_report": str(RECOVERY_REPORT_PATH),
                "recovery_report_digest": report["report_digest"],
                "scientific_manifest": str(SCIENTIFIC_MANIFEST_PATH),
                "scientific_manifest_digest": manifest[
                    "asset_manifest_digest"
                ],
                "missing_layers": report["missing_layers"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
