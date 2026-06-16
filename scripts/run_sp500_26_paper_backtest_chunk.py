from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission  # noqa: E402
from aurora.research.sp500_26_paper_replication_backtest import (  # noqa: E402
    dataset_for_mode,
    load_paper26_config,
    run_specs_chunk,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission("sp500 26 paper backtest chunk")
    parser = argparse.ArgumentParser(description="Run one SP500 26-paper replication chunk.")
    parser.add_argument("--specs", default="config/sp500_26_paper_replication_specs.yaml")
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunks", type=int, default=26)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()

    config, specs, _raw = load_paper26_config(args.specs)
    dataset = dataset_for_mode(config, synthetic_smoke=bool(args.synthetic_smoke))
    results, annual, monthly, summary = run_specs_chunk(
        specs,
        dataset,
        config,
        chunk_index=int(args.chunk_index),
        chunks=int(args.chunks),
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"sp500_26_paper_chunk_{int(args.chunk_index):03d}"
    results.to_csv(out / f"{stem}_results.csv", index=False)
    annual.to_csv(out / f"{stem}_annual.csv", index=False)
    monthly.to_csv(out / f"{stem}_monthly.csv", index=False)
    (out / f"{stem}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
