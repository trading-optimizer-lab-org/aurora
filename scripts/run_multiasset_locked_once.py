#!/usr/bin/env python3
"""Open the locked period (2021-01-01 onward) once for the registered candidate.

Requires the exact authorization string; the workflow additionally refuses to
run when an artifact from a previous opening exists.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

from aurora.research.multiasset_locked import evaluate_locked

AUTHORIZATION = "OPEN_MULTIASSET_LOCKED_2021_AW_VAA_ONCE"


def _build_prices():
    path = Path(__file__).resolve().parent / "run_multiasset_baselines.py"
    spec = importlib.util.spec_from_file_location("run_multiasset_baselines", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_prices(end_exclusive=None)


def render(result: dict, data_end: str) -> str:
    cand, bench = result[result["candidate"]], result[result["benchmark"]]
    rows = [("Monthly Sortino", "sortino_monthly", "{:.2f}"), ("Monthly Sharpe", "sharpe_monthly", "{:.2f}"),
            ("Daily Sortino", "sortino", "{:.2f}"), ("Daily Sharpe", "sharpe", "{:.2f}"),
            ("CAGR", "cagr", "{:.1%}"), ("Volatility", "vol", "{:.1%}"),
            ("Max drawdown", "max_drawdown", "{:.1%}"), ("Positive months", "positive_months", "{:.1%}")]
    lines = [f"# Locked period evaluation ({cand['start']} to {result['evaluated_through']}, "
             f"complete months; data to {data_end})", "", f"Commit: `{result['git_commit']}`", "",
             f"Candidate: `{result['candidate']}`; benchmark: `{result['benchmark']}`; "
             f"costs {result['cost_bps']:g} bps.", "",
             "| metric | candidate | SPY |", "|---|---|---|"]
    lines += [f"| {label} | {fmt.format(cand[k])} | {fmt.format(bench[k])} |" for label, k, fmt in rows]
    lines += ["", "| year | candidate | SPY |", "|---|---|---|"]
    lines += [f"| {y} | {cand['annual_returns'][y]:.1%} | {bench['annual_returns'][y]:.1%} |"
              for y in cand["annual_returns"]]
    lines += ["", "## Pre-registered criteria", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'}: {c}" for c, ok in result["checks"].items()]
    lines += ["", f"**Overall: {'PASSED' if result['passed'] else 'FAILED'}**"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/multiasset_locked_once"))
    args = parser.parse_args()
    if args.authorization != AUTHORIZATION:
        raise SystemExit("authorization string mismatch; locked period not opened")
    prices, data_report = _build_prices()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Keep the exact observations used, since this run must never be repeated.
    prices.to_parquet(args.output_dir / "prices.parquet")
    result = evaluate_locked(prices)
    result["git_commit"] = os.environ.get("GITHUB_SHA", "unknown")
    (args.output_dir / "locked_result.json").write_text(
        json.dumps({"data": data_report, **result}, indent=2, default=str), encoding="utf-8")
    text = render(result, data_report["data_end"])
    (args.output_dir / "LOCKED.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
