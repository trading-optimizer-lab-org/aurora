from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


BASE_COLUMNS = ("date", "open", "high", "low", "close", "volume")
ADJUSTED_COLUMNS = ("date", "open", "high", "low", "close", "adj_close", "volume")
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
    distribution_paths = sorted(input_root.resolve().rglob("spy_distributions.csv"))
    split_paths = sorted(input_root.resolve().rglob("spy_splits.csv"))
    if len(csv_paths) != expected_windows or len(receipt_paths) != expected_windows:
        raise RuntimeError(
            "STOOQ_SHARD_COUNT_MISMATCH:"
            f"csv={len(csv_paths)}:receipts={len(receipt_paths)}:expected={expected_windows}"
        )

    frames: list[pd.DataFrame] = []
    distribution_frames: list[pd.DataFrame] = []
    split_frames: list[pd.DataFrame] = []
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
            "yahoo_chart_adjusted_close_with_events",
        }:
            raise RuntimeError(f"STOOQ_SHARD_SOURCE_INVALID:{receipt_path}")
        source_counts[effective_source] = source_counts.get(effective_source, 0) + 1
        frame = pd.read_csv(csv_path)
        frame.columns = [str(column).strip().lower() for column in frame.columns]
        if tuple(frame.columns) not in {BASE_COLUMNS, ADJUSTED_COLUMNS} or frame.empty:
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

    if distribution_paths and len(distribution_paths) != expected_windows:
        raise RuntimeError("SPY_DISTRIBUTION_SHARD_COUNT_MISMATCH")
    if split_paths and len(split_paths) != expected_windows:
        raise RuntimeError("SPY_SPLIT_SHARD_COUNT_MISMATCH")
    for paths, value_column, collected_frames in (
        (distribution_paths, "distribution", distribution_frames),
        (split_paths, "split_ratio", split_frames),
    ):
        for path in paths:
            event_frame = pd.read_csv(path)
            if tuple(event_frame.columns) != ("date", value_column):
                raise RuntimeError(f"SPY_EVENT_SHARD_SCHEMA_INVALID:{value_column}:{path}")
            if len(event_frame):
                event_frame["date"] = pd.to_datetime(
                    event_frame["date"], errors="raise"
                ).dt.normalize()
                event_frame[value_column] = pd.to_numeric(
                    event_frame[value_column], errors="raise"
                )
            collected_frames.append(event_frame)

    combined = pd.concat(frames, ignore_index=True).sort_values("date", kind="mergesort")
    duplicated = combined[combined["date"].duplicated(keep=False)]
    if not duplicated.empty:
        compared_columns = [column for column in combined.columns if column != "date"]
        value_counts = duplicated.groupby("date", sort=True)[compared_columns].nunique()
        if (value_counts > 1).any(axis=None):
            raise RuntimeError("STOOQ_SHARD_OVERLAP_VALUE_MISMATCH")
    combined = combined.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    def merge_events(
        event_frames: list[pd.DataFrame],
        *,
        value_column: str,
    ) -> pd.DataFrame:
        if not event_frames:
            return pd.DataFrame(columns=["date", value_column])
        merged_events = pd.concat(event_frames, ignore_index=True)
        if merged_events.empty:
            return pd.DataFrame(columns=["date", value_column])
        duplicates = merged_events[merged_events["date"].duplicated(keep=False)]
        if not duplicates.empty and (
            duplicates.groupby("date")[value_column].nunique() > 1
        ).any():
            raise RuntimeError(f"SPY_EVENT_SHARD_OVERLAP_MISMATCH:{value_column}")
        merged_events = merged_events.drop_duplicates("date", keep="last").sort_values(
            "date", kind="mergesort"
        )
        if merged_events["date"].max() >= LOCKED_START:
            raise RuntimeError("TECHNICAL_FAILURE_LOCKED_BREACH:spy_events")
        if not merged_events["date"].isin(combined["date"]).all():
            raise RuntimeError(f"SPY_EVENT_ON_NON_SESSION:{value_column}")
        return merged_events.reset_index(drop=True)

    distributions = merge_events(distribution_frames, value_column="distribution")
    splits = merge_events(split_frames, value_column="split_ratio")

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
    distribution_target = output_dir / "spy_distributions.csv"
    split_target = output_dir / "spy_splits.csv"
    for events, target in (
        (distributions, distribution_target),
        (splits, split_target),
    ):
        serializable = events.copy()
        if len(serializable):
            serializable["date"] = pd.to_datetime(
                serializable["date"], errors="raise"
            ).dt.strftime("%Y-%m-%d")
        serializable.to_csv(target, index=False, lineterminator="\n")
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
        "adjusted_close_complete": bool(
            "adj_close" in combined and combined["adj_close"].notna().all()
        ),
        "distribution_event_count": len(distributions),
        "split_event_count": len(splits),
        "corporate_action_files_sha256": {
            "distributions": _sha256(distribution_target.read_bytes()),
            "splits": _sha256(split_target.read_bytes()),
        },
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
