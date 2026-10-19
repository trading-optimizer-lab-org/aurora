#!/usr/bin/env python3
"""v11: a Sortino-first combination of independent strategies. Pre-registered in docs/research/V11_PREREGISTRATION.md.

    python scripts/run_v11.py prepare ... (same arguments as run_v10.py prepare)
    python scripts/run_v11.py shard --shard 0 --inputs outputs/v10/inputs --out outputs/v11_part --workers 4
    python scripts/run_v11.py report --inputs outputs/v10/inputs --parts outputs/v11_parts --out outputs/v11_report
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import v9_etf as vf
from aurora.research import v10
from aurora.research import v11


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R10 = _script("run_v10")


def etf_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    import yfinance as yf

    opens, closes = {}, {}
    for s in vf.ALL_ETFS:
        df = yf.download(s, start="1993-01-01", end=str((v11.LAST + pd.Timedelta(days=1)).date()), auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            print(f"warning: no Yahoo data for {s}", flush=True)
            continue
        for name, store in (("Open", opens), ("Close", closes)):
            col = df[name]
            col = col.iloc[:, 0] if isinstance(col, pd.DataFrame) else col
            col.index = pd.to_datetime(col.index).tz_localize(None).normalize()
            store[s] = col.loc[:v11.LAST]
    return pd.DataFrame(opens), pd.DataFrame(closes)


def cmd_prepare(args) -> int:
    rc = R10.cmd_prepare(args)
    if rc:
        return rc
    o, cl = etf_prices()
    R10._dump({"open": o, "close": cl}, args.out / "inputs" / "etf_broad.pkl")
    print(f"ETFs: {list(cl.columns)}", flush=True)
    return 0


_G: dict = {}


def _globals(inputs: Path, kind: str) -> dict:
    if kind == "QB":
        return R10.qb_globals(R10._load(inputs / "qb.pkl"))
    G = R10.other_globals(inputs)
    b = R10._load(inputs / "etf_broad.pkl")
    x, e = v11.etf_context(b["open"], b["close"], R10._load(inputs / "mr.pkl")["cash"])
    G.update(x=x, e=e)
    return G


def stream(t: dict, G: dict) -> tuple[pd.Series, pd.Series]:
    """(daily returns, the cash series for its metrics) of one non-QB trial."""
    f = t["family"]
    if f == "LT":
        return v10.lt_sim(t, G["etf"], G["cash"]), G["cash"]
    if f == "CT":
        return v10.ct_sim(t, G["crypto"], G["cash_cal"]), G["cash_cal"]
    if f == "MR":
        return v10.mr_sim(t, G["mr"]), G["mr"]["cash_s"]
    return v11.etf_sim(t, G["x"], G["e"]), G["x"]["cash_s"]


def _qb_work(i: int) -> dict:
    g = v11.qb_cfg(i)
    return {**v11.score_row(v10.qb_name(g), "QB", v10.qb_sim(g, _G), _G["cash"]), "id": i}


def _other_work(t: dict) -> dict:
    r, cash = stream(t, _G)
    return {**v11.score_row(t["name"], t["family"], r, cash), "id": -1}


def cmd_shard(args) -> int:
    t0 = time.time()
    kind, items = v11.shard_items(args.shard)
    _G.update(_globals(args.inputs, kind))
    work = _qb_work if kind == "QB" else _other_work
    print(f"shard {args.shard}: {kind}, {len(items)} trials, inputs in {time.time() - t0:.0f}s", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            rows = list(pool.imap_unordered(work, items, chunksize=8))  # type: ignore[arg-type]
    else:
        rows = [work(x) for x in items]  # type: ignore[arg-type]
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(args.out / "rows.parquet", index=False)
    print(f"shard done in {time.time() - t0:.0f}s", flush=True)
    return 0


# ---------------------------------------------------------------- report

def _f(v, fmt: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not np.isfinite(v) else fmt.format(v)


def _metrics(r: pd.Series, cash: pd.Series) -> dict:
    out = {}
    for p, (a, b) in (("design", v11.COMBO), ("judge", v11.JUDGE)):
        x = r.loc[a:b].dropna()
        m = sc.metrics(x, cash)
        total = float((1 + x).prod() - 1)
        years = (x.index[-1] - x.index[0]).days / 365.25
        mo = (1 + x).groupby(x.index.to_period("M")).prod() - 1
        out.update({f"{p}_sortino": m.get("sortino_monthly"), f"{p}_cagr": (1 + total) ** (1 / years) - 1,
                    f"{p}_dd": m.get("max_drawdown"), f"{p}_total": total, f"{p}_worst_month": float(mo.min()),
                    f"{p}_sharpe": m.get("sharpe"), f"{p}_days": len(x), f"{p}_skew": m.get("skew"),
                    f"{p}_kurtosis": m.get("kurtosis")})
    x = r.loc[v11.COMBO[0]:v11.LAST].dropna()
    out["yearly"] = {int(y): float(v) for y, v in ((1 + x).groupby(x.index.year).prod() - 1).items()}
    return out


HEAD = ("| {} | Sortino 2016-20 | Sortino 2021-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | worst month | "
        + " | ".join(str(y) for y in range(2016, 2027)) + " |")
SEP = "|" + "---|" * 18


def _line(name: str, m: dict) -> str:
    years = " | ".join(_f(m["yearly"].get(y), "{:+.0%}") for y in range(2016, 2027))
    return (f"| {name} | {_f(m['design_sortino'], '{:.2f}')} | {_f(m['judge_sortino'], '{:.2f}')} | "
            f"{_f(m['judge_cagr'], '{:.1%}')} | {_f(m['judge_dd'], '{:.1%}')} | {_f(m['judge_total'], '{:+.0%}')} | "
            f"{_f(m['judge_worst_month'], '{:+.1%}')} | {years} |")


def cmd_report(args) -> int:
    parts = sorted(args.parts.rglob("rows.parquet"))
    rows = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    expected = v11.QB_N + len(v11.other_trials())
    sl = v11.shortlist(rows)
    GQ = _globals(args.inputs, "QB")
    GO = _globals(args.inputs, "OTHER")
    master, cash = GQ["dates"], GQ["cash"]
    lookup = {t["name"]: t for t in v11.other_trials()}
    series = {}
    for _, r in sl.iterrows():
        if r["family"] == "QB":
            s = v10.qb_sim(v11.qb_cfg(int(r["id"])), GQ)
        else:
            s = stream(lookup[r["name"]], GO)[0]
            s = v11.to_trading(s, master) if r["family"] == "CT" else s
        series[r["name"]] = s.reindex(master)
    R = pd.DataFrame(series)
    chosen, path = v11.greedy(R, cash)
    D = R.loc[v11.COMBO[0]:v11.COMBO[1]]
    combos = {"COMBO_GREEDY": v11.combine(R, v11.ivol_weights(D[chosen]))}
    fam_best = sl.sort_values("robust", ascending=False).groupby("family").head(1)["name"].tolist()
    combos["COMBO_FAMILY"] = v11.combine(R, v11.ivol_weights(D[fam_best]))
    combos["COMBO_FAMILY_EQ"] = v11.combine(R, pd.Series(1 / len(fam_best), index=fam_best))
    spy = GO["etf"]["SPY"].dropna().pct_change(fill_method=None).reindex(master)
    stats = {n: _metrics(s, cash) for n, s in combos.items()}
    member = {n: _metrics(R[n], cash) for n in R.columns}
    spy_m = _metrics(spy, cash)
    pool = np.concatenate([rows["judge_sharpe"].astype(float).to_numpy(), R10._prior_pool()])
    for n, m in stats.items():
        m["dsr"] = float(v7.deflated_sharpe([m["judge_sharpe"]], pool, [m["judge_days"]], [m["judge_skew"]],
                                            [m["judge_kurtosis"]])[0])
    def js(n: str) -> float:
        v = member[n]["judge_sortino"]
        return float(v) if v is not None and np.isfinite(v) else -9.0

    hind = max(member, key=js)
    lines = ["# v11: a Sortino-first combination of independent strategies (pre-registered)", "",
             f"{len(rows):,} of {expected:,} configurations; shortlist {len(sl)} streams. Chosen on 2016-2020 only; "
             f"judged on 2021-01-01 to {v11.LAST.date()}. Owner's target: monthly Sortino of 4.", "",
             "## 1. Combinations", "", HEAD.format("combination"), SEP]
    for n, m in stats.items():
        lines.append(_line(f"{n} (DSR {m['dsr']:.2f}{', Sortino >= 4' if (m['judge_sortino'] or 0) >= 4 else ''})", m))
    lines.append(_line("SPY", spy_m))
    lines += ["", "Greedy path (2016-2020 Sortino as streams are added): "
              + " -> ".join(f"{p:.2f}" for p in path), "",
              "## 2. Members of COMBO_GREEDY (weights fixed from 2016-2020 volatility)", "", HEAD.format("stream"), SEP]
    w = v11.ivol_weights(D[chosen])
    lines += [_line(f"{n} ({w[n]:.0%})", member[n]) for n in chosen]
    lines += ["", "## 3. COMBO_FAMILY members (best robust score per family)", "", HEAD.format("stream"), SEP]
    lines += [_line(n, member[n]) for n in fam_best]
    C = R[chosen]
    lines += ["", "## 4. Daily correlations of the COMBO_GREEDY members, 2021-2026", "",
              "| | " + " | ".join(str(i + 1) for i in range(len(chosen))) + " |", "|" + "---|" * (len(chosen) + 1)]
    cm = C.loc[v11.JUDGE[0]:v11.JUDGE[1]].corr()
    lines += [f"| {i + 1} | " + " | ".join(_f(v, "{:+.2f}") for v in cm.iloc[i]) + " |" for i in range(len(chosen))]
    lines += ["", f"Hindsight bound (not tradable): the best 2021-2026 Sortino among the {len(sl)} shortlisted streams is "
              f"{_f(member[hind]['judge_sortino'], '{:.2f}')} ({hind}).", ""]
    text = "\n".join(lines) + "\n"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text(text, encoding="utf-8")
    pd.DataFrame(combos).to_csv(args.out / "combo_streams.csv")
    R[chosen].to_csv(args.out / "member_streams.csv")
    sl.to_csv(args.out / "shortlist.csv", index=False)
    (args.out / "chosen.json").write_text(json.dumps({"chosen": chosen, "path": path, "family_best": fam_best}),
                                          encoding="utf-8")
    print(text, flush=True)
    return 0 if len(rows) == expected else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--out", type=Path, default=Path("outputs/v10"))
    a.add_argument("--old-cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca_locked"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec_locked"))
    a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    a = sub.add_parser("shard")
    a.add_argument("--shard", type=int, required=True)
    a.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--workers", type=int, default=4)
    a = sub.add_parser("report")
    a.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
    a.add_argument("--parts", type=Path, default=Path("outputs/v11_parts"))
    a.add_argument("--out", type=Path, default=Path("outputs/v11_report"))
    args = ap.parse_args()
    return {"prepare": cmd_prepare, "shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
