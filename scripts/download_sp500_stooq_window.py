from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from aurora.infra.sp500_long_short_daily.data import (
    DataGateError,
    download_kibot_unadjusted_history,
    download_stooq_history,
)


def download_window(
    *,
    start: str,
    end: str,
    split: str,
    window_id: str,
    output_dir: Path,
) -> dict[str, object]:
    """Download one bounded window with an explicit free provider fallback."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_source = "stooq_public_html_raw_unadjusted"
    try:
        frame, receipt = download_stooq_history(
            "spy.us",
            start,
            end,
            split=split,
            raw_dir=output_dir,
        )
    except DataGateError as exc:
        if str(exc) != "STOOQ_DAILY_HITS_LIMIT":
            raise
        frame, fallback_receipt = download_kibot_unadjusted_history(
            "SPY",
            start,
            end,
            split=split,
            raw_dir=output_dir,
        )
        payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        (output_dir / "stooq_spy_us_history.csv").write_bytes(payload)
        receipt = replace(
            fallback_receipt,
            dataset_id="DS002",
            status="downloaded_documented_free_fallback_kibot_raw_unadjusted",
            reason=(
                "fallback_for=STOOQ_DAILY_HITS_LIMIT;"
                f"fallback_dataset_id={fallback_receipt.dataset_id};"
                f"fallback_sha256={fallback_receipt.sha256}"
            ),
        )
        effective_source = "kibot_guest_raw_unadjusted_fallback"
        print(
            "[sp500-data] Stooq daily quota exhausted; "
            f"using documented bounded Kibot fallback window={window_id}",
            flush=True,
        )
    metadata: dict[str, object] = {
        "schema_version": "2",
        "window_id": str(window_id),
        "requested_start": start,
        "requested_end": end,
        "split": split,
        "rows": len(frame),
        "effective_source": effective_source,
        "receipt": asdict(receipt),
    }
    (output_dir / "stooq_window_receipt.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Download one bounded raw Stooq SPY window.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--split", choices=("train", "validation"), required=True)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    download_window(
        start=args.start,
        end=args.end,
        split=args.split,
        window_id=args.window_id,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
