"""Run the data-free official DEHB infrastructure smoke in GitHub Actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_official_smoke import run_official_dehb_smoke


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-contract", required=True, type=Path)
    parser.add_argument("--feature-contract", required=True, type=Path)
    parser.add_argument("--dependency-lock", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_official_dehb_smoke(
        data_contract_path=args.data_contract,
        feature_contract_path=args.feature_contract,
        dependency_lock_path=args.dependency_lock,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
