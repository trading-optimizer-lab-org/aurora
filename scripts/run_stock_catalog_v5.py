#!/usr/bin/env python3
"""Stock catalog v5 (new entries x new exits): run one shard, or merge shards into a report.

    python scripts/run_stock_catalog_v5.py shard --shard 0 --shards 20 --out outputs/v5/shard_0.json
    python scripts/run_stock_catalog_v5.py report --parts outputs/v5 --output-dir outputs/stock_catalog_v5

See docs/research/STOCK_CATALOG_V5_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from statistics import median

import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v5 as v5

PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_shard(args) -> int:
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    groups = v5.shard_groups(args.shard, args.shards) if args.groups is None else args.groups.split(",")
    print(f"shard {args.shard}/{args.shards}: {groups}", flush=True)
    out = v5.run_shard(panel, bench["gspc"], bench["spy"], cash_index, industry, groups)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"groups": groups, "results": out["results"]}, default=str), encoding="utf-8")
    pd.DataFrame(out["daily_returns"]).to_parquet(args.out.with_suffix(".daily.parquet"))
    print(f"wrote {len(out['results']) - 1} trials", flush=True)
    return 0


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


def render(agg: dict) -> str:
    res, spy = agg["results"], agg["spy"]
    tl = lambda n, p: res[n]["trade_level"][p]  # noqa: E731
    lines = ["# US stock strategy catalog v5 (new entries x new exits, pre-registered)", "",
             f"{len(agg['names'])} of {agg['expected']} trials computed; deflated Sharpe over {agg['n_trials']} "
             "trials (v5 + v1-v4). Selection uses train (1995-2010) only. Survivorship bias NOT adjusted. "
             "Locked period from 2021-01-01 never read.", "",
             f"SPY validation: Sortino {spy['validation']['sortino_monthly']:.2f}, CAGR {spy['validation']['cagr']:.1%}, "
             f"max DD {spy['validation']['max_drawdown']:.1%}.", ""]
    head = ("| trial | train trades | train PF | train avg | val trades | val PF | val avg | val total | "
            "port. Sortino | port. CAGR | port. max DD | passed |")
    sep = "|" + "---|" * 12

    def row(n: str) -> str:
        a, b, v = tl(n, "train"), tl(n, "validation"), res[n]["validation"]
        return (f"| {n} | {_fmt(a.get('trades'), '{:,}')} | {_fmt(a.get('profit_factor'), '{:.2f}')} | "
                f"{_fmt(a.get('avg_return'), '{:+.2%}')} | {_fmt(b.get('trades'), '{:,}')} | "
                f"{_fmt(b.get('profit_factor'), '{:.2f}')} | {_fmt(b.get('avg_return'), '{:+.2%}')} | "
                f"{_fmt(b.get('total_return'), '{:+,.0%}')} | {v['sortino_monthly']:.2f} | {v['cagr']:.1%} | "
                f"{v['max_drawdown']:.1%} | {'YES' if res[n]['passed'] else 'no'} |")
    lines += [f"## 1. Train-selected: top {v5.TOP_N} by train profit factor (>= {v5.MIN_TRAIN_TRADES} train trades)",
              "", head, sep] + [row(n) for n in agg["selected"]]
    lines += ["", "## 1b. Stable: PF >= 1.3 with >= 200 trades in both periods (descriptive)", "",
              f"{len(agg['stable'])} trials.", "", head, sep] + [row(n) for n in agg["stable"][:40]]
    passed = [n for n in agg["names"] if res[n]["passed"]]
    lines += ["", "## 2. Pre-registered criteria", "",
              f"Passed (any trial): {', '.join(passed) if passed else 'none'}",
              f"Passed among train-selected: {', '.join(n for n in agg['selected'] if n in passed) or 'none'}", ""]
    by_val = sorted([n for n in agg["names"] if tl(n, "validation").get("trades", 0) >= 200],
                    key=lambda n: -tl(n, "validation")["profit_factor"])[:30]
    lines += ["## 3. Descriptive: top 30 by validation profit factor (>= 200 validation trades)", "", head, sep]
    lines += [row(n) for n in by_val]

    def med(names: list[str], p: str) -> str:
        vals = [tl(n, p)["profit_factor"] for n in names if tl(n, p).get("trades", 0) >= 50]
        return f"{median(vals):.2f} ({len(vals)})" if vals else "-"

    lines += ["", "## 4. Exits: median trade-level PF across setups and filters", "",
              "| exit | train | validation |", "|---|---|---|"]
    for x in v5.EXITS:
        ns = [n for n in agg["names"] if n.split("_")[1] == x]
        lines.append(f"| {x} | {med(ns, 'train')} | {med(ns, 'validation')} |")
    lines += ["", "## 5. Filter sets: median trade-level PF (long grid)", "", "| filters | train | validation |",
              "|---|---|---|"]
    for f, fs in v5.FILTER_SETS.items():
        ns = [n for n in agg["names"] if n.endswith("_" + f)]
        lines.append(f"| {f} {'+'.join(fs) or 'none'} | {med(ns, 'train')} | {med(ns, 'validation')} |")
    lines += ["", "## 6. Best trial per setup (by train PF)", "", head, sep]
    for s in v5.SETUPS:
        ns = [n for n in agg["names"] if n.split("_")[0] == s and tl(n, "train").get("trades", 0) >= 50]
        if ns:
            lines.append(row(max(ns, key=lambda n: tl(n, "train")["profit_factor"])))
    return "\n".join(lines) + "\n"


def cmd_report(args) -> int:
    parts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.parts.glob("*.json"))]
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    agg = v5.aggregate(parts, [x for k in ("v1", "v2", "v3", "v4") for x in prior[k].values()])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(agg, indent=1, default=str), encoding="utf-8")
    text = render(agg)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    missing = agg["expected"] - len(agg["names"])
    if missing:
        print(f"ERROR: {missing} trials missing from the shards")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("shard")
    a.add_argument("--shard", type=int, required=True)
    a.add_argument("--shards", type=int, default=20)
    a.add_argument("--groups", default=None, help="comma-separated setups (overrides --shard)")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("report")
    b.add_argument("--parts", type=Path, required=True)
    b.add_argument("--output-dir", type=Path, default=Path("outputs/stock_catalog_v5"))
    args = ap.parse_args()
    return cmd_shard(args) if args.cmd == "shard" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
