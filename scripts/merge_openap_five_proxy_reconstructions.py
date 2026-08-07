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
    audits = sorted(source.rglob("proxy_validation_audit.json"))
    returns = sorted(source.rglob("proxy_realized_monthly.csv"))
    if len(panels) != len(FIVE_PROXY_SIGNALS):
        raise RuntimeError(
            f"Expected {len(FIVE_PROXY_SIGNALS)} reconstruction panels, found {len(panels)}"
        )
    if len(audits) != len(FIVE_PROXY_SIGNALS):
        raise RuntimeError(
            f"Expected {len(FIVE_PROXY_SIGNALS)} reconstruction audits, found {len(audits)}"
        )
    audited_signals: list[str] = []
    for path in audits:
        payload = json.loads(path.read_text(encoding="utf-8"))
        shard_signals = payload.get("signals", [])
        if len(shard_signals) != 1:
            raise RuntimeError(f"Reconstruction audit must identify one signal: {path}")
        if payload.get("locked_opened") is not False:
            raise RuntimeError(f"Reconstruction audit opened locked data: {path}")
        if payload.get("validation_used_for_selection") is not False:
            raise RuntimeError(f"Reconstruction audit used validation for selection: {path}")
        audited_signals.append(str(shard_signals[0]))
    expected = set(FIVE_PROXY_SIGNALS)
    if set(audited_signals) != expected or len(audited_signals) != len(expected):
        raise RuntimeError(
            "Audited reconstruction signals do not match contract: "
            f"{sorted(audited_signals)} != {sorted(expected)}"
        )
    frames = [pd.read_parquet(path) for path in panels]
    found = {
        str(signal)
        for frame in frames
        for signal in frame.get("signal", pd.Series(dtype="string")).dropna().unique()
    }
    if not found.issubset(expected):
        raise RuntimeError(
            f"Reconstructed panels contain signals outside contract: {sorted(found - expected)}"
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
        "signals_with_rows": sorted(found),
        "signals_without_rows": sorted(expected - found),
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
