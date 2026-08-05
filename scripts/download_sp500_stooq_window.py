from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from aurora.infra.sp500_long_short_daily.data import (
    DataGateError,
    download_stooq_history,
    download_yahoo_history,
)


def download_window(
    *,
    start: str,
    end: str,
    split: str,
    window_id: str,
    output_dir: Path,
    source_mode: str = "stooq-with-fallback",
) -> dict[str, object]:
    """Download one bounded window with an explicit free provider fallback."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_source = "stooq_public_html_raw_unadjusted"
    fallback_reason = (
        "STOOQ_PROVIDER_OUTAGE_CONFIRMED"
        if source_mode == "yahoo-fallback"
        else None
    )
    provider_error: DataGateError | None = None
    if source_mode not in {"stooq-with-fallback", "yahoo-fallback"}:
        raise ValueError(f"UNSUPPORTED_SP500_PRICE_SOURCE_MODE:{source_mode}")
    if fallback_reason is None:
        try:
            frame, receipt = download_stooq_history(
                "spy.us",
                start,
                end,
                split=split,
                raw_dir=output_dir,
            )
        except DataGateError as exc:
            provider_error = exc
            fallback_reason = str(exc)
    if fallback_reason is not None:
        if fallback_reason not in {
            "STOOQ_PROVIDER_OUTAGE_CONFIRMED",
            "STOOQ_DAILY_HITS_LIMIT",
            "STOOQ_HTML_HISTORY_ROWS_NOT_FOUND",
        }:
            if provider_error is not None:
                raise provider_error
            raise DataGateError(fallback_reason)
        frame, _, _, fallback_receipts = download_yahoo_history(
            "SPY",
            start,
            end,
            split=split,
            raw_dir=output_dir,
        )
        frame = frame.loc[:, ["date", "open", "high", "low", "close", "volume"]]
        payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        (output_dir / "stooq_spy_us_history.csv").write_bytes(payload)
        fallback_receipt = fallback_receipts[0]
        receipt = replace(
            fallback_receipt,
            dataset_id="DS002",
            status="downloaded_documented_free_fallback_yahoo_raw_unadjusted",
            reason=(
                f"fallback_for={fallback_reason};"
                f"fallback_dataset_id={fallback_receipt.dataset_id};"
                f"fallback_sha256={fallback_receipt.sha256}"
            ),
        )
        effective_source = "yahoo_chart_raw_unadjusted_fallback"
        print(
            f"[sp500-data] Stooq unavailable ({fallback_reason}); "
            f"using documented bounded Yahoo fallback window={window_id}",
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
    parser.add_argument(
        "--source-mode",
        choices=("stooq-with-fallback", "yahoo-fallback"),
        default="stooq-with-fallback",
    )
    args = parser.parse_args()

    download_window(
        start=args.start,
        end=args.end,
        split=args.split,
        window_id=args.window_id,
        output_dir=args.output_dir,
        source_mode=args.source_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
