from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.field_ritter_access import (
    download_field_ritter_ipo_workbook,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 Field-Ritter IPO access"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    requested_output = args.output_dir or Path("openap_149_field_ritter_access")
    output = (
        requested_output
        if requested_output.is_absolute()
        else base_data_dir() / requested_output
    )
    output.mkdir(parents=True, exist_ok=True)
    summary = download_field_ritter_ipo_workbook(
        output / "IPO-age.xlsx",
        output / "field_ritter_source_manifest.csv",
        user_agent=args.user_agent,
    )
    (output / "field_ritter_access_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
