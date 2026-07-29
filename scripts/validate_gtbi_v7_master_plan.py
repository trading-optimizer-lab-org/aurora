"""Validate GTBI V7 plan structure and external quality receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.gtbi_v7_readiness.quality import validate_quality_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--trusted-key-registry", type=Path)
    args = parser.parse_args()
    result = validate_quality_evidence(
        repository_root=args.repository_root,
        trusted_key_registry_path=args.trusted_key_registry,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if result.status == "CLEAN":
        return 0
    if result.status == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
