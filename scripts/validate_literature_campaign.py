from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aurora.research.literature_campaign import load_campaign_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a literature campaign YAML.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_campaign_config(args.config)
    payload = {
        "campaign_id": config.campaign_id,
        "train_start": config.train_start,
        "train_end": config.train_end,
        "validation_start": config.validation_start,
        "validation_end": config.validation_end,
        "locked_start": config.locked_start,
        "chunks": config.chunks,
        "max_parallel": config.max_parallel,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
