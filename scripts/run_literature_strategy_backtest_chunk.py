from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_engine():
    module_path = ROOT / "research" / "literature_strategy_backtest.py"
    spec = importlib.util.spec_from_file_location("literature_strategy_backtest_runtime", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load literature strategy backtest module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


_ENGINE = _load_engine()
LiteratureBacktestConfig = _ENGINE.LiteratureBacktestConfig
load_dataset = _ENGINE.load_dataset
load_signatures = _ENGINE.load_signatures
run_chunk = _ENGINE.run_chunk
synthetic_dataset = _ENGINE.synthetic_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one literature strategy backtest chunk.")
    parser.add_argument("--signatures", default="config/literature_strategy_signatures_9419.csv")
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunks", type=int, default=180)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-signatures", type=int, default=9419)
    parser.add_argument("--train-start", default="1995-01-01")
    parser.add_argument("--train-end", default="2010-12-31")
    parser.add_argument("--validation-start", default="2011-01-01")
    parser.add_argument("--validation-end", default="2020-12-31")
    parser.add_argument("--locked-start", default="2021-01-01")
    parser.add_argument("--require-data-start-lte", default="")
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()

    config = LiteratureBacktestConfig(
        signatures_path=args.signatures,
        train_start=args.train_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        locked_start=args.locked_start,
        expected_signatures=int(args.expected_signatures),
        require_data_start_lte=str(args.require_data_start_lte or ""),
    )
    signatures = load_signatures(args.signatures, expected=int(args.expected_signatures))
    dataset = synthetic_dataset() if args.synthetic_smoke else load_dataset(config)
    rows, manifest_rows, summary = run_chunk(
        signatures,
        dataset,
        config,
        chunk_index=int(args.chunk_index),
        chunks=int(args.chunks),
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"literature_strategy_backtest_chunk_{int(args.chunk_index):03d}"
    rows.to_csv(out / f"{stem}.csv", index=False)
    manifest_rows.to_csv(out / f"{stem}_manifest.csv", index=False)
    (out / f"{stem}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
