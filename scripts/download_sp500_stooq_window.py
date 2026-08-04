from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from aurora.infra.sp500_long_short_daily.data import download_stooq_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Download one bounded raw Stooq SPY window.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--split", choices=("train", "validation"), required=True)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frame, receipt = download_stooq_history(
        "spy.us",
        args.start,
        args.end,
        split=args.split,
        raw_dir=output_dir,
    )
    metadata = {
        "schema_version": "1",
        "window_id": str(args.window_id),
        "requested_start": args.start,
        "requested_end": args.end,
        "split": args.split,
        "rows": len(frame),
        "receipt": asdict(receipt),
    }
    (output_dir / "stooq_window_receipt.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
