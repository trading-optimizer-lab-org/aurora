from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import Counter
from pathlib import Path


def _float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--min-validation-profit-factor", type=float, default=1.05)
    args = parser.parse_args()

    best_all: dict[str, tuple[float, dict[str, str]]] = {}
    files = sorted(glob.glob(args.input_glob, recursive=True))
    raw_rows = 0
    for path in files:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                raw_rows += 1
                cid = str(row.get("candidate_id", ""))
                if not cid:
                    continue
                score = _float(row.get("train_score"), -1e300)
                if cid not in best_all or score > best_all[cid][0]:
                    best_all[cid] = (score, row)

    rows = [
        item[1]
        for item in best_all.values()
        if str(item[1].get("verified", "")).lower() == "true"
        and _float(item[1].get("validation_profit_factor"), 0.0) >= args.min_validation_profit_factor
    ]
    rows.sort(key=lambda item: _float(item.get("validation_sharpe"), -1e300), reverse=True)

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = ["candidate_id", "method", "rule"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    by_method = Counter(str(row.get("method") or row.get("source_method")) for row in rows)
    ml_groups = {
        f"{row.get('wave')}:{row.get('stage')}"
        for row in rows
        if str(row.get("method") or row.get("source_method")) == "github_ml"
    }
    summary = {
        "stage_files": len(files),
        "raw_rows": raw_rows,
        "candidates": len(rows),
        "min_validation_profit_factor": float(args.min_validation_profit_factor),
        "by_method": dict(sorted(by_method.items())),
        "github_ml_wave_stage_groups": len(ml_groups),
        "locked_opened": False,
    }
    Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
