from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.openap_181.sec_companyfacts_access import (
    download_official_sec_companyfacts,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 SEC CompanyFacts access"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ciks", required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    summary = download_official_sec_companyfacts(
        (value.strip() for value in args.ciks.split(",") if value.strip()),
        output / "raw_companyfacts",
        output / "sec_companyfacts_source_manifest.csv",
        user_agent=args.user_agent,
    )
    summary_path = output / "sec_companyfacts_access_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
