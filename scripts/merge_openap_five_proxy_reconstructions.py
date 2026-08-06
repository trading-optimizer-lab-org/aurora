"""Merge independently checkpointed OpenAP proxy reconstructions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.core.execution_policy import require_github_execution  # noqa: E402
from aurora.research.openap_93.historical_proxy_validation import (  # noqa: E402
    FIVE_PROXY_SIGNALS,
)


def merge_reconstructions(
    *, input_dir: str | Path, output_dir: str | Path
) -> dict[str, object]:
    require_github_execution("OpenAP five-proxy reconstruction merge")
    source = Path(input_dir)
    output = Path(output_dir)
    panels = sorted(source.rglob("proxy_reconstruction_panel.parquet"))
    returns = sorted(source.rglob("proxy_realized_monthly.csv"))
    if len(panels) != len(FIVE_PROXY_SIGNALS):
        raise RuntimeError(
            f"Expected {len(FIVE_PROXY_SIGNALS)} reconstruction panels, found {len(panels)}"
        )
    frames = [pd.read_parquet(path) for path in panels]
    found = {
        str(signal)
        for frame in frames
        for signal in frame.get("signal", pd.Series(dtype="string")).dropna().unique()
    }
    expected = set(FIVE_PROXY_SIGNALS)
    if found != expected:
        raise RuntimeError(
            f"Reconstructed signals do not match contract: {sorted(found)} != {sorted(expected)}"
        )
    panel = pd.concat(frames, ignore_index=True)
    identity = ["signal", "variant_id", "symbol", "formation_month"]
    if panel.duplicated(identity).any():
        raise RuntimeError("Duplicate proxy identities found across reconstruction shards")
    if not returns:
        raise RuntimeError("No realised monthly-return shards were found")
    monthly = pd.concat([pd.read_csv(path) for path in returns], ignore_index=True)
    monthly = monthly.drop_duplicates(["symbol", "completed_month"], keep="last")
    output.mkdir(parents=True, exist_ok=True)
    panel.sort_values(identity).to_parquet(
        output / "proxy_reconstruction_panel.parquet", index=False
    )
    monthly.sort_values(["symbol", "completed_month"]).to_csv(
        output / "proxy_realized_monthly.csv", index=False
    )
    summary = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "reconstruction_shards_expected": len(FIVE_PROXY_SIGNALS),
        "reconstruction_shards_found": len(panels),
        "proxy_rows": int(len(panel)),
        "monthly_return_rows": int(len(monthly)),
        "partial": False,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "backtest_enabled": False,
    }
    (output / "proxy_reconstruction_merge_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    merge_reconstructions(input_dir=args.input_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
