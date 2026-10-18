#!/usr/bin/env python3
"""Qullamaggie phase 1 (intraday execution, 2016-2020): fetch the minute bars the
candidates need from Alpaca, run the 48 trials and write the report.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_qullamaggie_intraday.py run \
        --panel-dir outputs/stock_panel --cache outputs/alpaca --output-dir outputs/qullamaggie_intraday

Minute data stays in ``--cache`` (never published). See
docs/research/QULLAMAGGIE_INTRADAY_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc

API = "https://data.alpaca.markets/v2/stocks/bars"
NY = ZoneInfo("America/New_York")
LAST = pd.Timestamp("2020-12-31")
PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")
MINUTE_COLS = ["symbol", "minute", "o", "h", "l", "c", "v"]


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Alpaca:
    """Historical bars (SIP feed, unadjusted). The free plan allows 200 calls a minute."""

    def __init__(self) -> None:
        key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.calls = 0

    def bars(self, symbols: list[str], timeframe: str, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, list]:
        if end.tz_convert(NY).normalize().tz_localize(None) > LAST:
            raise ValueError("refusing to request data after 2020-12-31 (locked period)")
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start.isoformat(),
                  "end": end.isoformat(), "feed": "sip", "adjustment": "raw", "limit": 10000}
        out: dict[str, list] = {}
        while True:
            for attempt in range(8):
                time.sleep(0.32)
                self.calls += 1
                r = requests.get(API, params=params, headers=self.headers, timeout=60)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                break
            else:
                raise RuntimeError(f"Alpaca kept failing: {r.status_code}")
            body = r.json()
            for sym, rows in (body.get("bars") or {}).items():
                out.setdefault(sym, []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                return out
            params["page_token"] = token


def alpaca_symbol(sym: str) -> str:
    return sym.replace("-", ".")


def _ny(day: pd.Timestamp, hh: int, mm: int) -> pd.Timestamp:
    return pd.Timestamp(day.year, day.month, day.day, hh, mm, tz=NY).tz_convert("UTC")


def fetch_daily(api: Alpaca, cache: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    path = cache / "daily.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["symbol", "date", "o", "h", "l", "c", "v"])
    todo = sorted(set(symbols) - set(have["symbol"]))
    new = []
    for b in range(0, len(todo), 7):
        batch = todo[b:b + 7]
        got = api.bars([alpaca_symbol(s) for s in batch], "1Day", _ny(pd.Timestamp("2015-09-01"), 0, 0),
                       _ny(LAST, 20, 0))
        back = {alpaca_symbol(s): s for s in batch}
        for asym, rows in got.items():
            for x in rows:
                day = pd.Timestamp(x["t"]).tz_convert(NY).normalize().tz_localize(None)
                new.append({"symbol": back.get(asym, asym), "date": day, "o": x["o"], "h": x["h"], "l": x["l"],
                            "c": x["c"], "v": x["v"]})
        # symbols Alpaca does not know are remembered so they are not asked again
        new += [{"symbol": s, "date": pd.NaT, "o": np.nan, "h": np.nan, "l": np.nan, "c": np.nan, "v": np.nan}
                for s in batch if alpaca_symbol(s) not in got]
        if b and b % 350 == 0:
            print(f"daily bars: {b}/{len(todo)} symbols", flush=True)
    if new:
        have = pd.concat([have, pd.DataFrame(new)], ignore_index=True)
        cache.mkdir(parents=True, exist_ok=True)
        have.to_parquet(path, index=False)
    have = have.dropna(subset=["date"])
    return {s: g.set_index("date").sort_index()[["o", "h", "l", "c", "v"]] for s, g in have.groupby("symbol")}


def fetch_minutes(api: Alpaca, cache: Path, need: dict[pd.Timestamp, list[str]]) -> None:
    folder = cache / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    for n, (day, symbols) in enumerate(sorted(need.items())):
        path = folder / f"{day.date()}.parquet"
        marker = folder / f"{day.date()}.asked.json"
        asked = set(json.loads(marker.read_text(encoding="utf-8"))) if marker.exists() else set()
        todo = sorted(set(symbols) - asked)
        if not todo:
            continue
        got = api.bars([alpaca_symbol(s) for s in todo], "1Min", _ny(day, 9, 30), _ny(day, 15, 59))
        back = {alpaca_symbol(s): s for s in todo}
        open_utc = _ny(day, 9, 30)
        rows = [{"symbol": back.get(asym, asym), "minute": int((pd.Timestamp(x["t"]) - open_utc).total_seconds() // 60),
                 "o": x["o"], "h": x["h"], "l": x["l"], "c": x["c"], "v": x["v"]}
                for asym, bars in got.items() for x in bars]
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=MINUTE_COLS)
        merged = pd.concat([old, pd.DataFrame(rows, columns=MINUTE_COLS)], ignore_index=True)
        merged = merged[(merged["minute"] >= 0) & (merged["minute"] < 390)].sort_values(["symbol", "minute"])
        merged.to_parquet(path, index=False)
        marker.write_text(json.dumps(sorted(asked | set(todo))), encoding="utf-8")
        if n % 100 == 0:
            print(f"minute bars: day {n}/{len(need)} ({day.date()}), {api.calls} calls", flush=True)


def minute_loader(cache: Path):
    def load(day: pd.Timestamp) -> pd.DataFrame:
        path = cache / "minutes" / f"{day.date()}.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=MINUTE_COLS)
    return load


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


HEAD = ("| trial | 2016-18 trades | PF | 2019-20 trades | PF | 2016-20 trades | win | PF | avg | total | Sortino | "
        "CAGR | max DD | same-day stops | median stop | entry minute | DSR | passed |")
SEP = "|" + "---|" * 18


def _row(n: str, r: pd.Series) -> str:
    return (f"| {n} | {_fmt(r['p1_tl_trades'], '{:,.0f}')} | {_fmt(r['p1_tl_profit_factor'], '{:.2f}')} | "
            f"{_fmt(r['p2_tl_trades'], '{:,.0f}')} | {_fmt(r['p2_tl_profit_factor'], '{:.2f}')} | "
            f"{_fmt(r['all_tl_trades'], '{:,.0f}')} | {_fmt(r['all_tl_win_rate'], '{:.0%}')} | "
            f"{_fmt(r['all_tl_profit_factor'], '{:.2f}')} | {_fmt(r['all_tl_avg_return'], '{:+.2%}')} | "
            f"{_fmt(r['all_tl_total_return'], '{:+,.0%}')} | {_fmt(r['all_sortino_monthly'], '{:.2f}')} | "
            f"{_fmt(r['all_cagr'], '{:.1%}')} | {_fmt(r['all_max_drawdown'], '{:.1%}')} | "
            f"{_fmt(r.get('stopped_entry_day'), '{:.0%}')} | {_fmt(r.get('median_risk'), '{:.1%}')} | "
            f"{_fmt(r.get('median_entry_minute'), '{:.0f}')} | {_fmt(r.get('deflated_sharpe'), '{:.2f}')} | "
            f"{'YES' if r.get('passed') is True else ('no' if r.get('passed') is False else '-')} |")


def render(agg: dict, info: dict) -> str:
    df, ref, spy = agg["df"], agg["ref"], agg["spy"]
    lines = ["# Qullamaggie phase 1: intraday execution on one-minute bars, 2016-2020 (pre-registered, 48 trials)",
             "", f"{len(df)} of {agg['expected']} trials; deflated Sharpe over {agg['n_trials']:,} trials. Candidate "
             f"days {info['candidate_days']:,}; intraday entries found {info['entries']:,}; dropped: "
             + ", ".join(f"{k} {v:,}" for k, v in info["dropped"].items()) + ". Survivorship bias NOT adjusted. "
             "Nothing after 2020-12-31 was requested.", "",
             f"SPY 2016-2020: Sortino {spy['all_sortino_monthly']:.2f}, CAGR {spy['all_cagr']:.1%}, max DD "
             f"{spy['all_max_drawdown']:.1%}. His record: ~37% same-day stops, median stop 2.5% (breakout) / 3.8% "
             "(EP), median entry minute 10, 25-31% winners.", "",
             "## 1. Reference: the daily-bar versions on 2016-2020 (not trials)", "", HEAD, SEP]
    lines += [_row(n, ref.loc[n]) for n in ref.index]
    lines += ["", "## 2. All trials", "", HEAD, SEP] + [_row(n, df.loc[n]) for n in df.index]
    lines += ["", "## 3. Pre-registered criteria on 2016-2020", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", "",
              "## 4. Median trade-level PF 2016-2020 by rule", ""]
    parts = df.index.str.split("_")
    for setup in ("IBO", "IEP"):
        sub = df[parts.str[0] == setup]
        sp = sub.index.str.split("_")
        dims = {"selection" if setup == "IBO" else "neglect": sp.str[1],
                "market" if setup == "IBO" else "volume": sp.str[2], "opening range": sp.str[3], "exit": sub["exit_rule"]}
        for dim, values in dims.items():
            key = np.asarray(values)
            lines += [f"### {setup}: by {dim}", "", f"| {dim} | 2016-2018 | 2019-2020 | 2016-2020 |", "|---|---|---|---|"]
            for val in sorted(set(key)):
                m = sub[key == val]
                cells = [f"{m[f'{p}_tl_profit_factor'].median():.2f}" for p in ("p1", "p2", "all")]
                lines.append(f"| {val} | " + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines) + "\n"


def report(rows: pd.DataFrame, info: dict, output_dir: Path) -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k in ("v1", "v2", "v3", "v4", "v5", "v6") for x in prior[k].values()]
    pool += [x for x in prior["v7"] if x is not None]
    pool += list(prior["qullamaggie"].values())
    agg = qi.aggregate(rows, pool)
    output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(output_dir / "results.parquet")
    agg["ref"].to_parquet(output_dir / "reference.parquet")
    (output_dir / "summary.json").write_text(json.dumps({"passed": agg["passed"], "info": info, "spy": agg["spy"]},
                                                        indent=1, default=str), encoding="utf-8")
    text = render(agg, info)
    (output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if len(agg["df"]) == agg["expected"] else 1


def cmd_run(args) -> int:
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = _script("run_qullamaggie").nasdaq_close(args.cache / "ixic.csv")
    api = Alpaca()
    ind = sc.indicators(panel, bench["gspc"], industry)
    from aurora.research import qullamaggie as q
    need = qi.needed(qi.candidates(panel, ind, q.context(panel, ind, nasdaq)))
    del ind
    print(f"{sum(len(v) for v in need.values()):,} candidate days on {len(need):,} sessions", flush=True)
    alp_daily = fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    fetch_minutes(api, args.cache, need)
    print(f"Alpaca calls: {api.calls}", flush=True)
    rows, info = qi.run(panel, bench["gspc"], bench["spy"], nasdaq, cash_index, industry, minute_loader(args.cache),
                        alp_daily, workers=args.workers)
    df = pd.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output_dir / "rows.parquet", index=False)
    (args.output_dir / "info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return report(df, info, args.output_dir)


def cmd_report(args) -> int:
    rows = pd.read_parquet(args.output_dir / "rows.parquet")
    info = json.loads((args.output_dir / "info.json").read_text(encoding="utf-8"))
    return report(rows, info, args.output_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie_intraday"))
    a.add_argument("--workers", type=int, default=4)
    b = sub.add_parser("report")
    b.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie_intraday"))
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
