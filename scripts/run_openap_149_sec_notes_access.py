from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.sec_fsd_access import (
    download_official_sec_notes_archives,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 SEC Notes access"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    output = args.output_dir or base_data_dir() / "openap_149_sec_notes_access"
    output.mkdir(parents=True, exist_ok=True)
    summary = download_official_sec_notes_archives(
        (args.period,),
        output / "zips",
        output / "sec_notes_source_manifest.csv",
        user_agent=args.user_agent,
    )
    summary = {**summary, "period": args.period}
    (output / "sec_notes_access_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
