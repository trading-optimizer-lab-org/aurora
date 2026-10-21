"""v19s: position sizing of COMBO19 in one account (pre-registered in docs/research/V19S_SIZING_PREREGISTRATION.md).

The walk-forward picks of the COMBO19 member families (v19r's selection, docs/research/data/v19r_summary.json; each
year only that year's members and picks, chosen on earlier data) are traded together in ONE account under R4 costs,
on a grid of sizing rules: risk to the stop per intraday trade, the cap on one position, the cap on the account's gross
exposure and the account size (the liquidity caps of v14, 2% of the dollar volume traded before an intraday entry and
1% of the 20-day dollar volume for a daily one, bind harder on bigger accounts). For each book: walk-forward
2018-2026 statistics, a stationary block bootstrap of ten-year paths (the chance of a 50% and a 90% drawdown) and the
loss of a squeeze (the largest position doubling against the book). Writes REPORT.md, summary.json and the daily
returns; no market data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19

R4 = np.array([[0.006633, 0.004728, 0.005763], [0.008026, 0.003602, 0.004782], [0.008188, 0.003977, 0.004642],
               [0.009853, 0.005096, 0.004473]])  # v21's calibration, as run_v22.R4
RISKS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.06)
CAPS = (0.20, 0.40)
GROSS = (1.0, 1.5, 2.0, 3.0)
ACCOUNTS = (25_000.0, 100_000.0, 250_000.0)
COSTS = (("mid", 1.0, 1.0), ("high", 2.0, 3.0))
YEARS, BLOCK, PATHS = 10, 20, 2000


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
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    last = eq[:, -1]
    cagr = np.where(last > 0, np.maximum(last, 1e-12) ** (1 / YEARS) - 1, -1.0)
    return {"p_dd50": float((dd <= -0.5).mean()), "p_dd90": float((dd <= -0.9).mean()),
            "dd_p95": float(np.quantile(dd, 0.05)), "cagr_med": float(np.median(cagr)),
            "cagr_p05": float(np.quantile(cagr, 0.05))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--summary", type=Path, default=Path("docs/research/data/v19r_summary.json"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v19s"))
    args = ap.parse_args()
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v19s runs on the whole sample: the unlock must be set")
    R19 = _script("run_v19")
    R14, R16 = R19.R14, R19.R16
    R19.load(args.inputs)
    v19.set_costs("r4", 0.25, R4)
    D, table, E, store = R14._G["D"], R16._W["table"], R16._W["E"], R14._G["store"]
    dates, cash = D["dates"], D["cash"]
    a, b = "2018-01-01", str(core.last_day().date())
    summ = json.loads(args.summary.read_text(encoding="utf-8"))
    reg = R19.registry()
    intra, daily, cache = [], [], {}  # (family, year, trades or specs) of each year's members and picks
    for y, fams in summ["members"].items():
        for fam in fams:
            name = summ["families"][fam]["picks"][y]
            key, ci = name.split("|")[0], int(name.split("|")[1])
            kind, cfgs = reg[key]
            g = cfgs[ci]
            if name not in cache:
                cache[name] = v19.intraday_trades(store, D, key, g) if kind == "intra" else                     v19.daily_specs(D, E, key, g)
            if kind == "intra":
                tr = cache[name]
                intra.append((fam, y, tr[pd.to_datetime(tr["date"]).dt.year == int(y)]))
            else:
                daily.append((fam, y, [s for s in cache[name] if dates[s.t].year == int(y)]))
        print(f"{y}: {', '.join(fams)}", flush=True)
    rows, streams = [], {}
    idx = draws(len(dates[(dates >= a) & (dates <= b)]))
    for acct in ACCOUNTS:
        for risk in RISKS:
            for cap in CAPS:
                for cname, spread, fee in COSTS:
                    paths = [p for _, _, tr in intra for p in intra_paths(tr, table, risk, cap, acct, spread, fee)]
                    paths += [p for _, _, sp in daily for p in daily_paths(D, sp, table, risk, cap, acct, spread, fee)]
                    for gcap in GROSS:
                        s = joint_book(paths, dates, gcap)
                        st = R14._stats(s, cash, a, b)
                        x = s.loc[a:b].to_numpy()
                        bs = bootstrap(x, idx)
                        m = s.loc[a:b].groupby(s.loc[a:b].index.to_period("M")).apply(lambda q: (1 + q).prod() - 1)
                        name = f"A{int(acct / 1000)}k_R{risk * 100:g}_C{int(cap * 100)}_G{gcap:g}_{cname}"
                        rows.append({"name": name, "account": acct, "risk": risk, "cap": cap, "gross": gcap,
                                     "costs": cname, **st, "worst_day": float(x.min()), "worst_month": float(m.min()),
                                     "squeeze": cap, **bs})
                        if acct == 100_000.0 and cname == "mid":
                            streams[name] = s.loc[a:b].astype(np.float32)
                    print(f"account {acct:.0f} risk {risk} cap {cap} {cname}: {len(paths)} paths", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(args.out / "books.csv", index=False)
    pd.DataFrame(streams).to_parquet(args.out / "streams.parquet")
    (args.out / "summary.json").write_text(df.to_json(orient="records", indent=1), encoding="utf-8")
    (args.out / "REPORT.md").write_text(report(df), encoding="utf-8")
    print(report(df), flush=True)
    return 0


def pick(df: pd.DataFrame, acct: float) -> pd.Series | None:
    """The pre-registered choice: the highest median bootstrap CAGR at the middle costs among the books whose
    high-cost twin keeps the chance of a 50% drawdown in ten years at 1% or less, with a squeeze loss of at most 40%
    and gross exposure of at most 2."""
    mid = df[(df["account"] == acct) & (df["costs"] == "mid") & (df["gross"] <= 2.0) & (df["squeeze"] <= 0.40)]
    hi = df[(df["account"] == acct) & (df["costs"] == "high")].set_index(["risk", "cap", "gross"])
    ok = [i for i, r in mid.iterrows() if hi.loc[(r["risk"], r["cap"], r["gross"]), "p_dd50"] <= 0.01]
    if not ok:
        return None
    return mid.loc[ok].sort_values("cagr_med", ascending=False).iloc[0]


def report(df: pd.DataFrame) -> str:
    f = lambda x: f"{x:.1%}"  # noqa: E731
    lines = ["# v19s: sizing COMBO19 in one account", "",
             "Walk-forward 2018-2026, R4 costs. p50 / p90: the chance of a 50% / 90% drawdown within ten years "
             "(block bootstrap); squeeze: the loss if the largest position doubles against the book.", ""]
    for acct in ACCOUNTS:
        lines += [f"## Account ${acct:,.0f}", "", "| risk | cap | gross | Sortino | CAGR | max DD | worst month | "
                  "CAGR high costs | DD high costs | p50 high | p90 high | median CAGR (bootstrap) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        sub = df[df["account"] == acct]
        hi = sub[sub["costs"] == "high"].set_index(["risk", "cap", "gross"])
        for _, r in sub[sub["costs"] == "mid"].iterrows():
            h = hi.loc[(r["risk"], r["cap"], r["gross"])]
            lines.append(f"| {r['risk']:.1%} | {r['cap']:.0%} | {r['gross']:g} | {r.get('sortino', np.nan):.2f} | "
                         f"{f(r.get('cagr', np.nan))} | {f(r.get('dd', np.nan))} | {f(r['worst_month'])} | "
                         f"{f(h.get('cagr', np.nan))} | {f(h.get('dd', np.nan))} | {h['p_dd50']:.1%} | "
                         f"{h['p_dd90']:.1%} | {f(r['cagr_med'])} |")
        p = pick(df, acct)
        lines += ["", "Pre-registered choice: " + (p["name"] if p is not None else "none") + "", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
