"""Split one verified train-only runtime pack for selective worker downloads."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    split_runtime_input_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--runtime-source-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    split_runtime_input_pack(
        args.runtime_input_pack,
        args.output_dir,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            campaign
        ),
        runtime_source_run_id=args.runtime_source_run_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
