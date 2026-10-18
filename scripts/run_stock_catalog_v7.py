#!/usr/bin/env python3
"""Stock catalog v7 (235,200 trials): run one shard, or merge shards into a report.

    python scripts/run_stock_catalog_v7.py shard --shard 0 --out outputs/v7/shard_0.parquet
    python scripts/run_stock_catalog_v7.py report --parts outputs/v7 --output-dir outputs/stock_catalog_v7

See docs/research/STOCK_CATALOG_V7_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7

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
    print(f"shard {args.shard}/{v7.SHARDS}: {v7.shard_setup(args.shard)} "
          f"{v7.EXIT_GROUPS[args.shard % len(v7.EXIT_GROUPS)]}", flush=True)
    rows = v7.run_shard(panel, bench["gspc"], bench["spy"], cash_index, industry, args.shard,
                        workers=args.workers, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(args.out, index=False)
    print(f"wrote {len(rows) - 1} trials", flush=True)
    return 0


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


HEAD = ("| trial | train trades | train PF | 2011-15 PF | 2016-20 PF | val trades | val PF | val avg | val total | "
        "port. Sortino | port. CAGR | port. max DD | DSR | passed |")
SEP = "|" + "---|" * 14


def _row(n: str, r: pd.Series) -> str:
    return (f"| {n} | {_fmt(r['train_tl_trades'], '{:,.0f}')} | {_fmt(r['train_tl_profit_factor'], '{:.2f}')} | "
            f"{_fmt(r['val1_tl_profit_factor'], '{:.2f}')} | {_fmt(r['val2_tl_profit_factor'], '{:.2f}')} | "
            f"{_fmt(r['validation_tl_trades'], '{:,.0f}')} | {_fmt(r['validation_tl_profit_factor'], '{:.2f}')} | "
            f"{_fmt(r['validation_tl_avg_return'], '{:+.2%}')} | {_fmt(r['validation_tl_total_return'], '{:+,.0%}')} | "
            f"{_fmt(r['validation_sortino_monthly'], '{:.2f}')} | {_fmt(r['validation_cagr'], '{:.1%}')} | "
            f"{_fmt(r['validation_max_drawdown'], '{:.1%}')} | {_fmt(r['deflated_sharpe'], '{:.2f}')} | "
            f"{'YES' if r['passed'] else 'no'} |")


def _table(df: pd.DataFrame, names: list[str]) -> list[str]:
    return [HEAD, SEP] + [_row(n, df.loc[n]) for n in names]


def render(agg: dict) -> str:
    df, spy = agg["df"], agg["spy"]
    lines = ["# US stock strategy catalog v7 (80 entries x 30 exits x 14 filter sets x 7 stops, pre-registered)", "",
             f"{len(df):,} of {agg['expected']:,} trials computed; deflated Sharpe over {agg['n_trials']:,} trials "
             "(v7 + v1-v6). Selection uses train (1995-2010) only. Survivorship bias NOT adjusted. "
             "Locked period from 2021-01-01 never read. PF = trade-level profit factor (every signal traded "
             "on its own); portfolio columns are the 0.5%-risk portfolio over 2011-2020.", "",
             f"SPY 2011-2020: Sortino {spy['validation_sortino_monthly']:.2f}, CAGR {spy['validation_cagr']:.1%}, "
             f"max DD {spy['validation_max_drawdown']:.1%}.", ""]
    lines += [f"## 1. Train-selected: top {v7.TOP_N} by train PF (>= {v7.MIN_TRAIN_TRADES} train trades)", ""]
    lines += _table(df, agg["selected"])
    passed = agg["passed"]
    lines += ["", "## 2. Pre-registered portfolio criteria on 2011-2020", "",
              f"{len(passed):,} trials pass (any). Among the train-selected: "
              f"{', '.join(n for n in agg['selected'] if n in passed) or 'none'}.", ""]
    best_passed = df.loc[passed].sort_values("validation_sortino_monthly", ascending=False).index[:60]
    lines += _table(df, list(best_passed))
    lines += ["", f"## 3. Robust (descriptive): PF >= {v7.ROBUST_PF} with >= {v7.ROBUST_TRADES} trades in train, "
              "2011-2015 and 2016-2020", "", f"{len(agg['robust']):,} trials; top 60 by the worst of the three PFs.",
              ""]
    lines += _table(df, agg["robust"][:60])
    lines += ["", f"## 4. Marginals: median PF over trials with >= {v7.MARGINAL_MIN_TRADES} trades in the period "
              "(number of trials in brackets)", ""]
    for dim, tab in agg["marginals"].items():
        lines += [f"### By {dim}", "", f"| {dim} | train | 2011-2015 | 2016-2020 | 2011-2020 |", "|---|---|---|---|---|"]
        for key, r in tab.iterrows():
            cells = [f"{_fmt(r[p], '{:.2f}')} ({_fmt(r[p + '_n'], '{:.0f}')})"
                     for p in ("train", "val1", "val2", "validation")]
            label = f"{key} {'+'.join(v7.FILTER_SETS[key]) or 'none'}" if dim == "filters" else key
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["## 5. Best trial per entry (by train PF, >= 50 train trades)", ""]
    best = []
    for s in v7.SETUPS:
        sub = df[(df["setup"] == s) & (df["train_tl_trades"] >= 50)]
        if len(sub):
            best.append(sub["train_tl_profit_factor"].idxmax())
    lines += _table(df, best)
    return "\n".join(lines) + "\n"


def cmd_report(args) -> int:
    rows = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.glob("*.parquet"))], ignore_index=True)
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    agg = v7.aggregate(rows, [x for k in ("v1", "v2", "v3", "v4", "v5", "v6") for x in prior[k].values()])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(args.output_dir / "results.parquet")
    summary = {k: agg[k] for k in ("spy", "selected", "passed", "n_trials", "expected")}
    summary["robust"] = agg["robust"][:1000]
    summary["marginals"] = {d: t.to_dict(orient="index") for d, t in agg["marginals"].items()}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    text = render(agg)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    missing = agg["expected"] - len(agg["df"])
    if missing:
        print(f"ERROR: {missing} trials missing from the shards")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("shard")
    a.add_argument("--shard", type=int, required=True, help=f"0..{v7.SHARDS - 1}")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--workers", type=int, default=4)
    a.add_argument("--limit", type=int, default=None, help="first N trials of the shard (smoke tests)")
    b = sub.add_parser("report")
    b.add_argument("--parts", type=Path, required=True)
    b.add_argument("--output-dir", type=Path, default=Path("outputs/stock_catalog_v7"))
    args = ap.parse_args()
    return cmd_shard(args) if args.cmd == "shard" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
