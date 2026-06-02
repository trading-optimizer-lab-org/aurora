from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aurora.research.literature_campaign import write_campaign_inputs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build literature campaign specs from paper evidence.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    summary = write_campaign_inputs(args.config, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
