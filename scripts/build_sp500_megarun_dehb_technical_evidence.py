from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_technical_evidence import (
    build_technical_evidence,
    validate_technical_evidence,
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_TECHNICAL_EVIDENCE")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--official-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    evidence = build_technical_evidence(
        campaign,
        official_report_path=args.official_report,
        work_dir=args.output.parent / "fault_injection",
        github_sha=os.environ.get("GITHUB_SHA", ""),
    )
    validate_technical_evidence(evidence, campaign_sha256=campaign.sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
