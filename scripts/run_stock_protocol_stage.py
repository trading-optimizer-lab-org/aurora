"""Run one deterministic shard of a stock protocol layer."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

import pandas as pd

from aurora.research.stock_protocol.dataset import read_pack
from aurora.research.stock_protocol.execution import execute_next_open
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.metrics import compute_metrics
from aurora.research.stock_protocol.portfolio import build_portfolio
from aurora.research.stock_protocol.signals import compute_signal


PHASE_TEST_IDS = {
    "signal": (1, 2, 3, 8, 9, 13),
    "weights": (13,),
    "entries": (15, 16, 17, 18, 19, 20),
    "exits": (21, 22, 23, 24, 25, 26),
    "portfolio": (27, 28, 29),
    "costs": (32,),
    "walk_forward": (34,),
    "robustness": (35,),
    "final": (36,),
}


def _blocks(manifest, block_count: int = 20) -> list[tuple[str, str]]:
    starts = pd.date_range(manifest.research_start, manifest.research_end, periods=block_count + 1)
    return [
        (starts[i].date().isoformat(), (starts[i + 1] - pd.Timedelta(days=1)).date().isoformat())
        for i in range(block_count)
    ]


def enumerate_tasks(manifest, phase: str, block_count: int = 20) -> list[dict[str, object]]:
    tests = {item.test_id: item for item in manifest.tests}
    tasks: list[dict[str, object]] = []
    for test_id in PHASE_TEST_IDS[phase]:
        record = tests[test_id]
        for variant_index, variant in enumerate(record.variants):
            for block_index, (block_start, block_end) in enumerate(_blocks(manifest, block_count)):
                tasks.append({
                    "phase": phase,
                    "test_id": test_id,
                    "variant_index": variant_index,
                    "variant": dict(variant),
                    "block_index": block_index,
                    "block_start": block_start,
                    "block_end": block_end,
                })
    return tasks


def _exit_rule(phase: str, variant: dict[str, object]) -> dict[str, object]:
    if phase == "exits":
        if "holding_sessions" in variant:
            return {"kind": "none", "holding_sessions": int(variant["holding_sessions"])}
        if "target_pct" in variant:
            return {"kind": "take_profit", "target_pct": float(variant["target_pct"]), "holding_sessions": 63}
        if "stop_atr" in variant and variant["stop_atr"] != "none":
            return {"kind": "catastrophe_atr", "k": float(variant["stop_atr"]), "holding_sessions": 63}
        return {"kind": "none", "holding_sessions": 63}
    if phase == "portfolio":
        return {"kind": "none", "holding_sessions": 63}
    return {"kind": "none", "holding_sessions": 63}


def run_stage(
    manifest_path: Path,
    pack_root: Path,
    phase: str,
    shard_id: int,
    shard_count: int,
    output_root: Path,
) -> Path:
    manifest = load_protocol_manifest(manifest_path)
    if phase not in PHASE_TEST_IDS:
        raise ValueError(f"unknown phase: {phase}")
    if shard_id < 0 or shard_id >= shard_count:
        raise ValueError("shard_id must be within shard_count")
    tasks = enumerate_tasks(manifest, phase)
    selected = tasks[shard_id::shard_count]
    panel = read_pack(pack_root, manifest.data_end)
    rows: list[dict[str, object]] = []
    for task in selected:
        signal = compute_signal(panel, int(task["test_id"]), dict(task["variant"]))
        block_start = pd.Timestamp(task["block_start"])
        block_end = pd.Timestamp(task["block_end"])
        signal = signal.loc[signal["signal_date"].between(block_start, block_end)].copy()
        trades = execute_next_open(signal, panel, _exit_rule(phase, dict(task["variant"])))
        if phase == "portfolio":
            trades = build_portfolio(trades, dict(task["variant"]))
        cost_bps = int(task["variant"].get("cost_bps", 0))
        returns = trades["gross_return"] if not trades.empty else pd.Series(dtype=float)
        metrics = compute_metrics(returns, trades, cost_bps=cost_bps)
        rows.append({
            **task,
            "variant": json.dumps(task["variant"], sort_keys=True),
            "shard_id": shard_id,
            "shard_count": shard_count,
            "dataset_hash": panel.audit.dataset_hash,
            "locked_opened": False,
            "data_end": manifest.data_end,
            "rows": int(len(trades)),
            "metrics": metrics,
            "status": "evaluated" if not trades.empty else "no_observations",
        })
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"phase={phase}" / f"shard={shard_id:03d}" / "stage_results.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--shard-id", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=360)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(run_stage(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
