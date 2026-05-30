from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from aurora.research.btc_5m_trainonly_search import BTC5mSearchConfig, METHODS, run_stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one fair BTC 5m train-only method-stage job.")
    parser.add_argument("--method", required=True, choices=METHODS)
    parser.add_argument("--wave", type=int, default=0)
    parser.add_argument("--total-waves", type=int, default=1)
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--total-stages", type=int, default=36)
    parser.add_argument("--time-budget-minutes", type=float, default=50.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="btc_5m_all_features_5methods_trainonly_1h_180jobs")
    parser.add_argument("--top-rows-per-stage", type=int, default=500)
    parser.add_argument("--random-seed", type=int, default=7301501)
    args = parser.parse_args()

    config = BTC5mSearchConfig(
        top_rows_per_stage=int(args.top_rows_per_stage),
        random_seed=int(args.random_seed),
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, meta, audit = run_stage(
        config,
        method=args.method,
        wave=int(args.wave),
        total_waves=int(args.total_waves),
        stage=int(args.stage),
        total_stages=int(args.total_stages),
        time_budget_minutes=float(args.time_budget_minutes),
    )
    artifact_stem = f"{args.file_prefix}_wave_{int(args.wave)}_stage_{args.method}_{args.stage}"
    rows_path = output_dir / f"{artifact_stem}.csv"
    meta_path = output_dir / f"{artifact_stem}_meta.json"
    audit_path = output_dir / f"{artifact_stem}_feature_audit.json"
    pd.DataFrame(rows).to_csv(rows_path, index=False)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
