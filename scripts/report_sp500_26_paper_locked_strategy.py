from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission  # noqa: E402
from aurora.core.runtime_paths import base_data_dir  # noqa: E402
from aurora.data_contracts.timeseries_store import TimeSeriesStore  # noqa: E402
from aurora.research.literature_strategy_backtest import (  # noqa: E402
    _load_context_panel,
    _load_price_panel,
    _symbols_by_bucket,
)
from aurora.research.sp500_26_paper_replication_backtest import (  # noqa: E402
    base_fields,
    build_strategy_returns,
    evaluate_view,
    load_paper26_config,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission("sp500 26 paper locked strategy report")
    parser = argparse.ArgumentParser(description="Report locked-period results for one SP500 26-paper strategy.")
    parser.add_argument("--specs", default="config/sp500_26_paper_replication_specs.yaml")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config, specs, _raw = load_paper26_config(args.specs)
    selected = [spec for spec in specs if str(spec.get("slug")) == str(args.slug)]
    if not selected:
        raise SystemExit(f"unknown strategy slug: {args.slug}")
    spec = selected[0]
    dataset = load_dataset_through(config.train_start, str(args.end_date))
    strategy = build_strategy_returns(spec, dataset, config)
    locked = evaluate_view(
        base_fields(spec),
        strategy,
        config,
        view="locked",
        start=config.locked_start,
        end=str(args.end_date),
    )
    locked["summary"]["locked_opened"] = True
    locked["summary"]["locked_requested_by_user"] = True

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([locked["summary"]]).to_csv(output_dir / "sp500_26_locked_summary.csv", index=False)
    pd.DataFrame(locked["annual"]).to_csv(output_dir / "sp500_26_locked_annual_returns.csv", index=False)
    pd.DataFrame(locked["monthly"]).to_csv(output_dir / "sp500_26_locked_monthly_returns.csv", index=False)
    summary = {
        "slug": str(args.slug),
        "locked_opened": True,
        "locked_requested_by_user": True,
        "locked_start": config.locked_start,
        "locked_end": str(args.end_date),
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "rows_annual": int(len(locked["annual"])),
        "rows_monthly": int(len(locked["monthly"])),
    }
    (output_dir / "sp500_26_locked_audit.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def load_dataset_through(start: str, end: str) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((repo_root / "config" / "diversified_seed_dataset.yaml").read_text(encoding="utf-8"))
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    symbols_by_bucket = _symbols_by_bucket(manifest)
    prices = _load_price_panel(store, symbols_by_bucket, start=start, end=end)
    context = _load_context_panel(store, start=start, end=end)
    if prices.empty:
        raise ValueError("no price data available for locked report")
    return {
        "prices": prices,
        "returns": prices.pct_change(),
        "context": context.reindex(prices.index).ffill() if not context.empty else context,
        "symbols_by_bucket": symbols_by_bucket,
        "locked_opened": True,
        "train_start": start,
        "validation_end": end,
    }


if __name__ == "__main__":
    raise SystemExit(main())
