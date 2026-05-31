from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="btc_5m_pf105_statistical_robustness")
    parser.add_argument("--expected-candidates", type=int, default=36555)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    files = sorted(glob.glob(args.input_glob, recursive=True))
    for path in files:
        if Path(path).stat().st_size == 0:
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if "statistical_pass" not in (reader.fieldnames or []):
                continue
            rows.extend(reader)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / f"{args.file_prefix}_results.csv"
    pass_path = out / f"{args.file_prefix}_pass.csv"
    methods_path = out / f"{args.file_prefix}_methods.csv"
    fail_path = out / f"{args.file_prefix}_fail_reasons.csv"
    summary_path = out / f"{args.file_prefix}_summary.json"

    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = ["candidate_id", "method", "statistical_pass", "fail_reasons"]
    rows.sort(key=lambda row: float(row.get("daily_sharpe") or "-999999"), reverse=True)
    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    pass_rows = [row for row in rows if str(row.get("statistical_pass", "")).lower() == "true"]
    with pass_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pass_rows)

    method_counts = Counter(row.get("method", "") for row in rows)
    method_pass = Counter(row.get("method", "") for row in pass_rows)
    with methods_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["method", "tested", "statistical_pass", "pass_rate"])
        writer.writeheader()
        for method in sorted(method_counts):
            tested = method_counts[method]
            passed = method_pass[method]
            writer.writerow(
                {
                    "method": method,
                    "tested": tested,
                    "statistical_pass": passed,
                    "pass_rate": float(passed / tested) if tested else 0.0,
                }
            )

    failures = Counter()
    for row in rows:
        if str(row.get("statistical_pass", "")).lower() == "true":
            continue
        for reason in str(row.get("fail_reasons", "")).split(";"):
            if reason:
                failures[reason] += 1
    with fail_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["fail_reason", "count"])
        writer.writeheader()
        for reason, count in failures.most_common():
            writer.writerow({"fail_reason": reason, "count": count})

    unique = {row.get("candidate_id") for row in rows if row.get("candidate_id")}
    summary = {
        "input_files": len(files),
        "rows": len(rows),
        "unique_candidates": len(unique),
        "expected_candidates": int(args.expected_candidates),
        "partial": len(unique) != int(args.expected_candidates),
        "statistical_pass": len(pass_rows),
        "locked_opened": False,
        "period": "validation_daily_from_5m",
        "costs": "zero",
        "outputs": {
            "results": str(results_path),
            "pass": str(pass_path),
            "methods": str(methods_path),
            "fail_reasons": str(fail_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
