from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.openap_181.sec_fsd_access import (
    download_official_sec_fsd_archives,
)
from aurora.research.openap_181.sec_fsd_inputs import bounded_quarters


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 SEC FSD access"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--start-quarter", required=True)
    parser.add_argument("--end-quarter", required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    quarters = bounded_quarters(args.start_quarter, args.end_quarter)
    summary = download_official_sec_fsd_archives(
        quarters,
        args.zip_dir,
        args.source_manifest,
        user_agent=args.user_agent,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
