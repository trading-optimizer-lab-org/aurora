from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aurora.research.literature_campaign import load_campaign_config  # noqa: E402


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one literature campaign backtest chunk.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--specs", required=True)
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunks", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()

    campaign = load_campaign_config(args.config)
    expected = _count_csv_rows(Path(args.specs))
    config = _ENGINE.LiteratureBacktestConfig(
        signatures_path=args.specs,
        train_start=campaign.train_start,
        train_end=campaign.train_end,
        validation_start=campaign.validation_start,
        validation_end=campaign.validation_end,
        locked_start=campaign.locked_start,
        expected_signatures=expected,
    )
    signatures = _ENGINE.load_signatures(args.specs, expected=expected)
    dataset = _ENGINE.synthetic_dataset() if args.synthetic_smoke else _ENGINE.load_dataset(config)
    rows, manifest_rows, summary = _ENGINE.run_chunk(
        signatures,
        dataset,
        config,
        chunk_index=int(args.chunk_index),
        chunks=int(args.chunks),
    )
    summary["campaign_id"] = campaign.campaign_id
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


def _count_csv_rows(path: Path) -> int:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


if __name__ == "__main__":
    raise SystemExit(main())
