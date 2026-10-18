#!/usr/bin/env python3
"""Qullamaggie's literal rules (85 trials): run one shard, or merge shards into a report.

    python scripts/run_qullamaggie.py shard --shard 0 --out outputs/qulla/shard_0.parquet
    python scripts/run_qullamaggie.py report --parts outputs/qulla --output-dir outputs/qullamaggie

See docs/research/QULLAMAGGIE_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import stock_catalog as sc

PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")
SETUP_LABEL = {"QBO": "Breakout", "QEP": "Episodic Pivot", "QPS": "Parabolic short"}


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def nasdaq_close(cache: Path | None) -> pd.Series:
    """Nasdaq Composite close (^IXIC, Yahoo) up to 2020-12-31."""
    if cache is not None and cache.exists():
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
    else:
        import yfinance as yf
        raw = yf.download("^IXIC", start="1990-01-01", end=str(sc.LOCKED_START.date()), auto_adjust=False,
                          progress=False)
        s = raw["Close"]
        s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            s.rename("ixic").to_csv(cache)
    s = s[s.index < sc.LOCKED_START].dropna()
    if len(s) < 5000:
        raise RuntimeError("Nasdaq Composite download failed")
    return s


def cmd_shard(args) -> int:
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    print(f"shard {args.shard}/{len(q.groups())}: {q.groups()[args.shard]}", flush=True)
    rows = q.run_shard(panel, bench["gspc"], bench["spy"], nasdaq_close(args.nasdaq_cache), cash_index, industry,
                       args.shard, workers=args.workers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(args.out, index=False)
    print(f"wrote {len(rows) - 1} trials", flush=True)
    return 0


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


HEAD = ("| trial | train trades | train win | train PF | train avg | 2011-20 trades | win | PF | avg | total | "
        "Sortino 95-10 | Sortino 11-20 | CAGR 11-20 | max DD 11-20 | DSR | passed |")
SEP = "|" + "---|" * 16


def _row(n: str, r: pd.Series) -> str:
    return (f"| {n} | {_fmt(r['train_tl_trades'], '{:,.0f}')} | {_fmt(r['train_tl_win_rate'], '{:.0%}')} | "
            f"{_fmt(r['train_tl_profit_factor'], '{:.2f}')} | {_fmt(r['train_tl_avg_return'], '{:+.2%}')} | "
            f"{_fmt(r['validation_tl_trades'], '{:,.0f}')} | {_fmt(r['validation_tl_win_rate'], '{:.0%}')} | "
            f"{_fmt(r['validation_tl_profit_factor'], '{:.2f}')} | {_fmt(r['validation_tl_avg_return'], '{:+.2%}')} | "
            f"{_fmt(r['validation_tl_total_return'], '{:+,.0%}')} | {_fmt(r['train_sortino_monthly'], '{:.2f}')} | "
            f"{_fmt(r['validation_sortino_monthly'], '{:.2f}')} | {_fmt(r['validation_cagr'], '{:.1%}')} | "
            f"{_fmt(r['validation_max_drawdown'], '{:.1%}')} | {_fmt(r['deflated_sharpe'], '{:.2f}')} | "
            f"{'YES' if r['passed'] else 'no'} |")


def _table(df: pd.DataFrame, names: list[str]) -> list[str]:
    return [HEAD, SEP] + [_row(n, df.loc[n]) for n in names]


def render(agg: dict) -> str:
    df, spy = agg["df"], agg["spy"]
    lines = ["# Qullamaggie's literal rules on US stocks (pre-registered, 85 trials)", "",
             f"{len(df)} of {agg['expected']} trials computed; deflated Sharpe over {agg['n_trials']:,} trials "
             "(this study + catalog v1-v7). Survivorship bias NOT adjusted (helps longs, hurts shorts). Locked "
             "period from 2021-01-01 never read. Trade-level columns: every signal traded on its own; portfolio "
             "columns: 0.5% risk per trade, 20% cap.", "",
             f"SPY: Sortino {spy['train_sortino_monthly']:.2f} (1995-2010) / {spy['validation_sortino_monthly']:.2f} "
             f"(2011-2020), CAGR 2011-2020 {spy['validation_cagr']:.1%}, max DD {spy['validation_max_drawdown']:.1%}.",
             "", "## 1. Canonical (his literal beginner rules)", ""]
    lines += _table(df, [n for n in q.CANONICAL if n in df.index])
    lines += ["", f"## 2. Train-selected: best by train Sortino per setup (>= {q.MIN_SELECT_TRADES} train trades)", ""]
    lines += _table(df, list(agg["selected"].values()))
    passed = agg["passed"]
    lines += ["", "## 3. Pre-registered portfolio criteria on 2011-2020", "",
              f"Passed: {', '.join(passed) if passed else 'none'}.", "",
              "## 4. Realism against his real record", "",
              "His record: ~37% of breakouts/EPs stopped out on the entry day (10-day SMA model on his real "
              "entries), median stop 2.5% (breakout) / 3.8% (EP), 25-31% winners.", "",
              "| trial | stopped on entry day | median initial stop | win rate (all) | median winner hold |",
              "|---|---|---|---|---|"]
    for n in q.CANONICAL:
        if n in df.index:
            r = df.loc[n]
            win = (r["train_tl_win_rate"] * r["train_tl_trades"] + r["validation_tl_win_rate"]
                   * r["validation_tl_trades"]) / (r["train_tl_trades"] + r["validation_tl_trades"])
            lines.append(f"| {n} | {_fmt(r['stopped_entry_day'], '{:.0%}')} | {_fmt(r['median_risk'], '{:.1%}')} | "
                         f"{_fmt(win, '{:.0%}')} | {_fmt(r['median_win_days'], '{:.0f}')} days |")
    lines += ["", "## 5. Median trade-level PF by rule (trials with >= 50 trades in the period)", ""]
    for setup, label in SETUP_LABEL.items():
        sub = df[df.index.str.startswith(setup)]
        parts = sub.index.str.split("_")
        dims = {"exit": sub["exit"]}
        if setup == "QBO":
            dims.update(fill=parts.str[1], selection=parts.str[2], market=parts.str[3])
        elif setup == "QEP":
            dims.update(neglect=parts.str[1], adr=parts.str[2], market=parts.str[3])
        else:
            dims.update(run=parts.str[1])
        for dim, key in dims.items():
            lines += [f"### {label}: by {dim}", "", f"| {dim} | train | 2011-2015 | 2016-2020 | 2011-2020 |",
                      "|---|---|---|---|---|"]
            for val in sorted(set(key)):
                m = sub[(key == val).to_numpy()]
                cells = []
                for p in ("train", "val1", "val2", "validation"):
                    pf = m[f"{p}_tl_profit_factor"].where(m[f"{p}_tl_trades"] >= 50).dropna()
                    cells.append(f"{pf.median():.2f} ({len(pf)})" if len(pf) else "-")
                lines.append(f"| {val} | " + " | ".join(cells) + " |")
            lines.append("")
    lines += ["## 6. All trials", ""] + _table(df, list(df.index))
    return "\n".join(lines) + "\n"


def cmd_report(args) -> int:
    rows = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.glob("*.parquet"))], ignore_index=True)
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k in ("v1", "v2", "v3", "v4", "v5", "v6") for x in prior[k].values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = q.aggregate(rows, pool)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(args.output_dir / "results.parquet")
    summary = {k: agg[k] for k in ("spy", "selected", "passed", "n_trials", "expected")}
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
    a.add_argument("--shard", type=int, required=True, help=f"0..{len(q.groups()) - 1}")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--nasdaq-cache", type=Path, default=None)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--workers", type=int, default=4)
    b = sub.add_parser("report")
    b.add_argument("--parts", type=Path, required=True)
    b.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie"))
    args = ap.parse_args()
    return cmd_shard(args) if args.cmd == "shard" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
