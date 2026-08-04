from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


EXPECTED_COLUMNS = ("date", "open", "high", "low", "close", "volume")
LOCKED_START = pd.Timestamp("2021-01-01")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def merge_windows(
    input_root: Path,
    output_dir: Path,
    *,
    expected_windows: int,
    requested_start: str,
    requested_end: str,
) -> dict[str, object]:
    csv_paths = sorted(input_root.resolve().rglob("stooq_spy_us_history.csv"))
    receipt_paths = sorted(input_root.resolve().rglob("stooq_window_receipt.json"))
    if len(csv_paths) != expected_windows or len(receipt_paths) != expected_windows:
        raise RuntimeError(
            "STOOQ_SHARD_COUNT_MISMATCH:"
            f"csv={len(csv_paths)}:receipts={len(receipt_paths)}:expected={expected_windows}"
        )

    frames: list[pd.DataFrame] = []
    windows: list[dict[str, object]] = []
    source_counts: dict[str, int] = {}
    for csv_path, receipt_path in zip(csv_paths, receipt_paths, strict=True):
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt = receipt_payload.get("receipt") or {}
        if receipt.get("dataset_id") != "DS002":
            raise RuntimeError(f"STOOQ_SHARD_RECEIPT_INVALID:{receipt_path}")
        effective_source = str(
            receipt_payload.get("effective_source")
            or "stooq_public_html_raw_unadjusted"
        )
        if effective_source not in {
            "stooq_public_html_raw_unadjusted",
            "yahoo_chart_raw_unadjusted_fallback",
        }:
            raise RuntimeError(f"STOOQ_SHARD_SOURCE_INVALID:{receipt_path}")
        source_counts[effective_source] = source_counts.get(effective_source, 0) + 1
        frame = pd.read_csv(csv_path)
        frame.columns = [str(column).strip().lower() for column in frame.columns]
        if tuple(frame.columns) != EXPECTED_COLUMNS or frame.empty:
            raise RuntimeError(f"STOOQ_SHARD_SCHEMA_INVALID:{csv_path}")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
        if frame["date"].duplicated().any():
            raise RuntimeError(f"STOOQ_SHARD_DUPLICATE_DATE:{csv_path}")
        frames.append(frame)
        windows.append(
            {
                "window_id": receipt_payload["window_id"],
                "requested_start": receipt_payload["requested_start"],
                "requested_end": receipt_payload["requested_end"],
                "rows": len(frame),
                "effective_source": effective_source,
                "receipt_status": receipt.get("status"),
                "csv_sha256": _sha256(csv_path.read_bytes()),
                "receipt_sha256": _sha256(receipt_path.read_bytes()),
            }
        )

    combined = pd.concat(frames, ignore_index=True).sort_values("date", kind="mergesort")
    duplicated = combined[combined["date"].duplicated(keep=False)]
    if not duplicated.empty:
        value_counts = duplicated.groupby("date", sort=True)[list(EXPECTED_COLUMNS[1:])].nunique()
        if (value_counts > 1).any(axis=None):
            raise RuntimeError("STOOQ_SHARD_OVERLAP_VALUE_MISMATCH")
    combined = combined.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    start = pd.Timestamp(requested_start).normalize()
    end = pd.Timestamp(requested_end).normalize()
    if end >= LOCKED_START or combined["date"].max() >= LOCKED_START:
        raise RuntimeError("TECHNICAL_FAILURE_LOCKED_BREACH:stooq_merge")
    if combined["date"].min() < start or combined["date"].max() > end:
        raise RuntimeError("STOOQ_SHARDED_DATE_BOUNDARY_MISMATCH")
    if combined["date"].min() > start + pd.Timedelta(days=7):
        raise RuntimeError("STOOQ_SHARDED_START_COVERAGE_GAP")
    if combined["date"].max() < end - pd.Timedelta(days=7):
        raise RuntimeError("STOOQ_SHARDED_END_COVERAGE_GAP")
    gaps = combined["date"].diff().dropna().dt.days
    if len(gaps) and int(gaps.max()) > 10:
        raise RuntimeError(f"STOOQ_SHARDED_INTERNAL_GAP:{int(gaps.max())}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_payload = combined.to_csv(index=False, lineterminator="\n").encode("utf-8")
    csv_target = output_dir / "stooq_spy_us_history.csv"
    csv_target.write_bytes(csv_payload)
    manifest = {
        "schema_version": "2",
        "source": (
            next(iter(source_counts))
            if len(source_counts) == 1
            else "mixed_stooq_and_documented_yahoo_fallback_raw_unadjusted"
        ),
        "source_counts": dict(sorted(source_counts.items())),
        "requested_start": start.date().isoformat(),
        "requested_end": end.date().isoformat(),
        "minimum_date": combined["date"].min().date().isoformat(),
        "maximum_date": combined["date"].max().date().isoformat(),
        "rows": len(combined),
        "window_count": expected_windows,
        "windows": sorted(windows, key=lambda item: str(item["window_id"])),
        "merged_sha256": _sha256(csv_payload),
        "locked_opened": False,
    }
    (output_dir / "stooq_sharded_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge bounded Stooq SPY window artifacts.")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-windows", type=int, required=True)
    parser.add_argument("--requested-start", required=True)
    parser.add_argument("--requested-end", required=True)
    args = parser.parse_args()
    merge_windows(
        args.input_root,
        args.output_dir,
        expected_windows=args.expected_windows,
        requested_start=args.requested_start,
        requested_end=args.requested_end,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
