"""v19s: position sizing of COMBO19 in one account (pre-registered in docs/research/V19S_SIZING_PREREGISTRATION.md).

The walk-forward picks of the COMBO19 member families (v19r's selection, docs/research/data/v19r_summary.json; each
year only that year's members and picks, chosen on earlier data) are traded together in ONE account under R4 costs,
on a grid of sizing rules: risk to the stop per intraday trade, the cap on one position, the cap on the account's gross
exposure and the account size (the liquidity caps of v14, 2% of the dollar volume traded before an intraday entry and
1% of the 20-day dollar volume for a daily one, bind harder on bigger accounts). For each book: walk-forward
2018-2026 statistics, a stationary block bootstrap of ten-year paths (the chance of 50%, 75% and 90% drawdowns) and the
loss of a squeeze (the largest position doubling against the book). A book whose equity reaches zero stays there.

  part    one (account, risk, cap) cell: the picks' trades (4 processes), its books at both costs and four gross caps
  report  the parts merged: REPORT.md, books.csv, summary.json, the daily returns of the $100k middle-cost books
``--study ru`` (v20s, docs/research/V20S_SIZING_PREREGISTRATION.md) does the same for v20's RU walk-forward stream (a
daily short without a stop): its position size is 10x ``risk`` (v20's 5% at 0.5%). No market data is written.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19

R4 = np.array([[0.006633, 0.004728, 0.005763], [0.008026, 0.003602, 0.004782], [0.008188, 0.003977, 0.004642],
               [0.009853, 0.005096, 0.004473]])  # v21's calibration, as run_v22.R4
RISKS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.06)
CAPS = (0.20, 0.40, 0.60, 1.00)
GROSS = (1.0, 1.5, 2.0, 3.0)
ACCOUNTS = (25_000.0, 100_000.0, 250_000.0)
COSTS = (("mid", 1.0, 1.0), ("high", 2.0, 3.0))
YEARS, BLOCK, PATHS = 10, 20, 2000
_G: dict = {}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def joint_book(paths: list[tuple], dates: pd.DatetimeIndex, gross_cap: float, max_open: int = 20) -> pd.Series:
    """v19's book_paths with the account's gross exposure capped at ``gross_cap``."""
    out, gross = np.zeros(len(dates)), np.zeros(len(dates))
    open_until: list[int] = []
    for i0, r, _, w in sorted(paths, key=lambda p: (p[0], -p[2])):
        open_until = [x for x in open_until if x >= i0]
        n = min(len(r), len(dates) - i0)
        if n <= 0 or w <= 0 or len(open_until) >= max_open or gross[i0:i0 + n].max() + w > gross_cap + 1e-9:
            continue
        out[i0:i0 + n] += w * r[:n]
        gross[i0:i0 + n] += w
        open_until.append(i0 + n - 1)
    return pd.Series(out, index=dates)


def intra_paths(t: pd.DataFrame, table: dict, risk: float, cap: float, account: float, spread: float,
                fee: float) -> list[tuple]:
    """v19.intra_book's sizing with ``risk`` to the stop and ``cap`` on a position (the first five trades a day)."""
    if t.empty:
        return []
    t = t.sort_values(["date", "minute", "prio"], ascending=[True, True, False]).groupby("date", sort=False).head(5)
    e, s = t["entry"].to_numpy(float), t["stop"].to_numpy(float)
    dist = np.abs(e - s) / e
    w = np.minimum(np.minimum(cap, risk / np.maximum(dist, 1e-4)), 0.02 * np.nan_to_num(t["liq"].to_numpy(float))
                   / account)
    cost, avail = v19._costs(t["price"].to_numpy(), t["so"].to_numpy(), t["side"].to_numpy(), t["nights"].to_numpy(),
                             t["opens"].to_numpy(), table, spread, fee, False,
                             (t["leg_in"].to_numpy(), t["leg_out"].to_numpy()))
    out = []
    for i, (i0, r, pr) in enumerate(zip(t["t"].to_numpy(), t["rets"], t["prio"].to_numpy(float))):
        rr = np.array(r, float)
        rr[0] -= cost[i]
        out.append((int(i0), rr, float(pr), float(w[i] * avail[i])))
    return out


def daily_paths(D: dict, specs: list, table: dict, risk: float, cap: float, account: float, spread: float,
                fee: float) -> list[tuple]:
    """v19.path19 with its 5% position cap scaled like the intraday risk (risk / 0.5%), at most ``cap``."""
    keep = core.ACCOUNT
    core.ACCOUNT = account
    try:
        return [p for s in specs if (p := v19.path19(D, s, table, spread, fee, False,
                                                     min(cap, 0.05 * risk / 0.005))) is not None]
    finally:
        core.ACCOUNT = keep


def draws(n: int, seed: int = 19) -> np.ndarray:
    """Indices of a stationary block bootstrap (mean block 20 sessions): PATHS ten-year paths over n sessions; the
    same draws for every book."""
    rng = np.random.default_rng(seed)
    L = 252 * YEARS
    new = rng.random((PATHS, L)) < 1 / BLOCK
    new[:, 0] = True
    starts = rng.integers(n, size=(PATHS, L))
    pos = np.maximum.accumulate(np.where(new, np.arange(L), 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (np.arange(L) - pos)) % n


def bootstrap(r: np.ndarray, idx: np.ndarray) -> dict:
    eq = np.cumprod(1 + np.maximum(r[idx], -1.0), axis=1)
    dd = (eq / np.maximum(np.maximum.accumulate(eq, axis=1), 1e-300) - 1).min(axis=1)
    last = eq[:, -1]
    cagr = np.where(last > 0, np.maximum(last, 1e-300) ** (1 / YEARS) - 1, -1.0)
    return {"p_dd50": float((dd <= -0.5).mean()), "p_dd75": float((dd <= -0.75).mean()),
            "p_dd90": float((dd <= -0.9).mean()), "dd_p95": float(np.quantile(dd, 0.05)),
            "cagr_med": float(np.median(cagr)), "cagr_p05": float(np.quantile(cagr, 0.05))}


def stats(s: pd.Series, cash: pd.Series) -> dict:
    """Walk-forward statistics of daily returns; a day losing more than the account ends it (equity stays at zero)."""
    x = s.clip(lower=-1.0)
    eq = (1 + x).cumprod()
    years = max((x.index[-1] - x.index[0]).days / 365.25, 1e-9)
    last = float(eq.iloc[-1])
    m = x.groupby(x.index.to_period("M")).apply(lambda q: (1 + q).prod() - 1)
    return {"sortino": core.sortino(x, cash), "cagr": last ** (1 / years) - 1 if last > 0 else -1.0,
            "dd": float((eq / eq.cummax().clip(lower=1e-300) - 1).min()), "total": last - 1,
            "worst_day": float(x.min()), "worst_month": float(m.min()), "ruined": bool(last <= 0)}


def _trades(name: str):
    key, ci = name.split("|")[0], int(name.split("|")[1])
    kind, cfgs = _G["reg"][key]
    g = cfgs[ci]
    D, E, store = _G["D"], _G["E"], _G["store"]
    return name, kind, (v19.intraday_trades(store, D, key, g) if kind == "intra" else _G["specs"](D, E, key, g))


def cmd_part(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v19s runs on the whole sample: the unlock must be set")
    if args.study == "ru":
        from aurora.research import v20_grid as v20
        R20 = _script("run_v20")
        R19, reg, specs = R20.R19, R20.registry(), v20.daily_specs
    else:
        R19 = _script("run_v19")
        reg, specs = R19.registry(), v19.daily_specs
    R14, R16 = R19.R14, R19.R16
    R19.load(args.inputs)
    v19.set_costs("r4", 0.25, R4)
    D, table = R14._G["D"], R16._W["table"]
    _G.update({"reg": reg, "specs": specs, "D": D, "E": R16._W["E"], "store": R14._G["store"]})
    dates, cash = D["dates"], D["cash"]
    a, b = "2018-01-01", str(core.last_day().date())
    summ = json.loads(args.summary.read_text(encoding="utf-8"))
    if args.study == "ru":  # the RU stream: each year's walk-forward pick
        summ = {"families": {"RU": summ["families"]["RU"]}, "members": {y: ["RU"] for y in summ["families"]["RU"]["picks"]}}
    names = sorted({summ["families"][f]["picks"][y] for y, fams in summ["members"].items() for f in fams})
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            got = pool.map(_trades, names, chunksize=1)
    else:
        got = [_trades(n) for n in names]
    cache = {n: (k, x) for n, k, x in got}
    intra, daily = [], []
    for y, fams in summ["members"].items():
        for fam in fams:
            kind, x = cache[summ["families"][fam]["picks"][y]]
            if kind == "intra":
                intra.append(x[pd.to_datetime(x["date"]).dt.year == int(y)])
            else:
                daily.append([s for s in x if dates[s.t].year == int(y)])
    print(f"{len(names)} picks: {len(intra)} intraday and {len(daily)} daily family-years", flush=True)
    idx = draws(len(dates[(dates >= a) & (dates <= b)]))
    acct, risk, cap = args.account, args.risk, args.cap
    rows, streams = [], {}
    for cname, spread, fee in COSTS:
        paths = [p for tr in intra for p in intra_paths(tr, table, risk, cap, acct, spread, fee)]
        paths += [p for sp in daily for p in daily_paths(D, sp, table, risk, cap, acct, spread, fee)]
        for gcap in GROSS:
            s = joint_book(paths, dates, gcap).loc[a:b]
            name = f"A{int(acct / 1000)}k_R{risk * 100:g}_C{int(cap * 100)}_G{gcap:g}_{cname}"
            rows.append({"name": name, "account": acct, "risk": risk, "cap": cap, "gross": gcap, "costs": cname,
                         "position": min(cap, 0.05 * risk / 0.005), **stats(s, cash), "squeeze": cap,
                         **bootstrap(s.to_numpy(), idx)})
            if acct == 100_000.0 and cname == "mid":
                streams[name] = s.astype(np.float32)
        print(f"{cname}: {len(paths)} paths", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    tag = f"{int(acct)}_{risk}_{cap}"
    (args.out / f"rows_{tag}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if streams:
        pd.DataFrame(streams).to_parquet(args.out / f"streams_{tag}.parquet")
    return 0


def pick(df: pd.DataFrame, acct: float) -> pd.Series | None:
    """The pre-registered choice (amended before any result): the highest median bootstrap CAGR at the middle costs
    among the books with a chance of a 75% drawdown in ten years of at most 1% (middle costs) and gross exposure of
    at most 2x."""
    ok = df[(df["account"] == acct) & (df["costs"] == "mid") & (df["gross"] <= 2.0) & (df["p_dd75"] <= 0.01)]
    return ok.sort_values("cagr_med", ascending=False).iloc[0] if len(ok) else None


def report(df: pd.DataFrame, study: str = "combo19") -> str:
    def f(x) -> str:
        return f"{x:.1%}" if np.isfinite(x) else "-"

    title = "# v20s: sizing v20's RU stream (position = 10x risk)" if study == "ru" else         "# v19s: sizing COMBO19 in one account"
    lines = [title, "",
             "Walk-forward 2018-2026, R4 costs. p50 / p75 / p90: the chance of a 50% / 75% / 90% drawdown within ten "
             "years (block bootstrap of the book's daily returns); squeeze: the loss if the largest position doubles "
             "against the book (its cap); ruined: the equity reached zero in 2018-2026.", ""]
    for acct in ACCOUNTS:
        lines += [f"## Account ${acct:,.0f}", "",
                  ("| position | gross " if study == "ru" else "| risk | cap | gross ") +
                  "| Sortino | CAGR | max DD | worst month | p50 | p75 | p90 | median CAGR (bootstrap) "
                  "| CAGR high costs | DD high costs | p75 high |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|" + ("" if study == "ru" else "---|")]
        sub = df[df["account"] == acct]
        hi = sub[sub["costs"] == "high"].set_index(["risk", "cap", "gross"])
        for _, r in sub[sub["costs"] == "mid"].sort_values(["risk", "cap", "gross"]).iterrows():
            h = hi.loc[(r["risk"], r["cap"], r["gross"])]
            ruin = " (ruined)" if r["ruined"] else ""
            lead = f"| {r['position']:.1%} " if study == "ru" else f"| {r['risk']:.1%} | {r['cap']:.0%} "
            lines.append(lead + f"| {r['gross']:g} | {r['sortino']:.2f} | "
                         f"{f(r['cagr'])}{ruin} | {f(r['dd'])} | {f(r['worst_month'])} | {r['p_dd50']:.1%} | "
                         f"{r['p_dd75']:.1%} | {r['p_dd90']:.1%} | {f(r['cagr_med'])} | {f(h['cagr'])} | "
                         f"{f(h['dd'])} | {h['p_dd75']:.1%} |")
        p = pick(df, acct)
        lines += ["", "Pre-registered choice: " + (p["name"] if p is not None else "none"), ""]
    return "\n".join(lines)


def cmd_report(args) -> int:
    rows = [r for p in sorted(args.parts.rglob("rows_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    df = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out / "books.csv", index=False)
    (args.out / "summary.json").write_text(json.dumps({"books": rows, "choice": {
        str(int(a)): (None if (p := pick(df, a)) is None else p["name"]) for a in ACCOUNTS}}, indent=1, default=float),
        encoding="utf-8")
    parts = [pd.read_parquet(p) for p in sorted(args.parts.rglob("streams_*.parquet"))]
    if parts:
        pd.concat(parts, axis=1).to_parquet(args.out / "streams.parquet")
    text = report(df, args.study)
    (args.out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text, flush=True)
    print(f"books {len(df)}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("part")
    p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    p.add_argument("--summary", type=Path, default=None)
    p.add_argument("--study", choices=("combo19", "ru"), default="combo19")
    p.add_argument("--account", type=float, required=True)
    p.add_argument("--risk", type=float, required=True)
    p.add_argument("--cap", type=float, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--study", choices=("combo19", "ru"), default="combo19")
    args = ap.parse_args()
    if args.cmd == "part" and args.summary is None:
        args.summary = Path("docs/research/data/" + ("v20_summary.json" if args.study == "ru" else "v19r_summary.json"))
    return {"part": cmd_part, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
