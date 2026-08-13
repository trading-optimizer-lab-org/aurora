"""Build a read-only cache-savings report from ordered train-only wave roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_cache_savings_audit import (
    audit_historical_records,
    load_legacy_wave_records,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave-root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_historical_records([load_legacy_wave_records(root) for root in args.wave_root])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
