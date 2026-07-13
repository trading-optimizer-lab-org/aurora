"""Freeze one layer's train selection and emit a compact handoff snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from aurora.research.stock_protocol.manifest import load_protocol_manifest


def _pareto_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    cagr = pd.to_numeric(frame.get("metrics.cagr", 0.0), errors="coerce").fillna(0.0)
    capday = pd.to_numeric(frame.get("metrics.return_per_capital_day", 0.0), errors="coerce").fillna(0.0)
    dd = pd.to_numeric(frame.get("metrics.max_drawdown", 0.0), errors="coerce").fillna(0.0)
    keep = []
    for i in range(len(frame)):
        dominated = False
        for j in range(len(frame)):
            if i == j:
                continue
            no_worse = cagr.iloc[j] >= cagr.iloc[i] and capday.iloc[j] >= capday.iloc[i] and dd.iloc[j] >= dd.iloc[i]
            strict = cagr.iloc[j] > cagr.iloc[i] or capday.iloc[j] > capday.iloc[i] or dd.iloc[j] > dd.iloc[i]
            dominated = dominated or (no_worse and strict)
        keep.append(not dominated)
    return frame.loc[keep]


def freeze_layer(results_path: Path, layer: str, manifest_path: Path, output_root: Path) -> Path:
    manifest = load_protocol_manifest(manifest_path)
    frame = pd.read_csv(results_path)
    frontier = _pareto_rows(frame)
    if frontier.empty:
        raise ValueError(f"layer {layer} has no non-dominated rows")
    sort_column = "metrics.sharpe" if "metrics.sharpe" in frontier else "metrics.cagr"
    selected = frontier.sort_values(sort_column, ascending=False).head(20)
    payload = {
        "layer": layer,
        "selected": selected.to_dict(orient="records"),
        "frontier_rows": int(len(frontier)),
        "dataset_hashes": sorted(set(frame["dataset_hash"].astype(str))),
        "policy_hash": manifest.policy_hash,
        "locked_opened": False,
        "data_end": manifest.data_end,
    }
    payload["config_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"{layer}_snapshot.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", dest="results_path", type=Path, required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(freeze_layer(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
