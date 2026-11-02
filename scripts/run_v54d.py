"""v54d (V54D_PREREGISTRATION.md): why CRASH-long earns from 2018 and not in 2016-2017, market or data.

  daily   the overnight of every -20% close on the daily panel alone, by year (no minute data)
  minute  CRASH-long by year on v51+v52's minute bars: entries x exits, as is and without the extreme trades
  cover   by year, what the minute bars hold around CRASH events: extended-session bars and their agreement with
          the daily panel
  final   V54D_REPORT.md and v54d_summary.json
Aggregates only: no prices or trades leave the runner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v53 as W  # noqa: E402  (sets the 2016-2026 cells)

V, E = W.V, W.E
RTH0, RTH1 = 330, 720  # minutes from 04:00: 09:30 and 16:00
ENTRIES = ("c_1555", "c_ah0")
TIMES = ("d1o", "d1pm", "d1m", "d1c", "d2c")
EXITS = ((0.0, 0.0), (0.25, 1.00))
SETUP = "CRASH"  # the tests use a setup their synthetic world has
PRICE_BANDS = {"lt1": (0.0, 1.0), "1-5": (1.0, 5.0), "ge5": (5.0, np.inf)}


def stats(r: np.ndarray) -> dict:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if not len(r):
        return {"n": 0}
    lo, hi = np.percentile(r, [1, 99])
    t = r[(r >= lo) & (r <= hi)]
    top = np.sort(r)[::-1][:max(1, len(r) // 100)]

    def pf(x):
        return round(float(V._pf(x[x > 0].sum(), -x[x < 0].sum())), 3)
    return {"n": int(len(r)), "mean": round(float(r.mean()), 5), "median": round(float(np.median(r)), 5),
            "win": round(float((r > 0).mean()), 3), "pf": pf(r), "pf_trim": pf(t),
            "mean_trim": round(float(t.mean()), 5),
            "top1_share": round(float(top.sum() / r.sum()), 3) if r.sum() > 0 else None}


def by_year(years: np.ndarray, r: np.ndarray) -> dict:
    return {str(int(y)): stats(r[years == y]) for y in np.unique(years)}


# ---------------------------------------------------------------- daily

def cmd_daily(args) -> int:
    G = V.load_inputs(args.inputs, args.extras)
    C, O, valid = G["C"].astype(float), G["O"].astype(float), G["valid"].astype(bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        chg = C[1:-1] / C[:-2] - 1
        on = O[2:] / C[1:-1] - 1
        nxt = C[2:] / C[1:-1] - 1
    ok = valid[1:-1] & valid[:-2] & valid[2:] & np.isfinite(chg) & np.isfinite(on) & (C[1:-1] > 0)
    crash = ok & (chg <= -0.20)
    t, j = np.nonzero(crash)
    years = G["year"][t + 1]
    px = C[1:-1][t, j]
    out = {"first_date": str(G["dates"][0].date()), "last_date": str(G["dates"][-1].date()),
           "symbols_valid_by_year": {str(int(y)): int(valid[G["year"] == y].any(0).sum()) for y in np.unique(G["year"])},
           "crash_overnight": by_year(years, on[t, j]), "crash_next_close": by_year(years, nxt[t, j]),
           "crash_overnight_by_price": {k: by_year(years[(px >= a) & (px < b)], on[t, j][(px >= a) & (px < b)])
                                        for k, (a, b) in PRICE_BANDS.items()}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "daily.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("first_date", "last_date")}), flush=True)
    return 0


# ---------------------------------------------------------------- minute

def _setup(args) -> tuple[dict, dict]:
    G = V.load_inputs(args.inputs, args.extras)
    census = json.loads((args.data / "census.json").read_text(encoding="utf-8"))
    EV = V.setup_events(G, args.data, SETUP)
    V._G.update(G=G, EV=EV, setup=SETUP, sgn=1, entries=list(E.ENTRIES["close"].items()), H=int(census["hold"]),
                folder=args.data / "minutes")
    return G, EV


def cmd_minute(args) -> int:
    t0 = time.time()
    G, EV = _setup(args)
    parts = V._map(V._pass1, V._chunks(EV["t"]), args.procs)
    order = np.concatenate(V._chunks(EV["t"]))
    P = {k: np.empty((len(order),) + parts[0][k].shape[1:], parts[0][k].dtype) for k in parts[0]}
    for k in P:
        P[k][order] = np.concatenate([p[k] for p in parts])
    Mb = E.filter_matrix().astype(bool)
    V._G.update(P1=P, Mb=Mb)
    names = [n for n, _ in V._G["entries"]]
    out = {"events": int(len(EV["t"])), "codes": {}}
    for en in ENTRIES:
        q = names.index(en)
        out["codes"][en] = {str(int(y)): {V.CODES[c]: int(((P["code"][:, q] == c) & (G["year"][EV["t"]] == y)).sum())
                                         for c in np.unique(P["code"][:, q])} for y in np.unique(G["year"][EV["t"]])}
        ev, cells, _ = V._cells(q, (0,))
        yrs = G["year"][EV["t"][ev] + P["de"][ev, q]]
        for ti in TIMES:
            for tg, st in EXITS:
                x = E.EXITS.index((E.TIMES.index(ti), E.TGTS.index(tg), E.STOPS.index(st)))
                R = P["R"][ev, q, x].astype(float)
                keep = Mb[V.ALL][cells] & np.isfinite(R)
                out[f"{en} {V.exit_name(x)}"] = by_year(yrs[keep], R[keep])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "minute.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"minute done {time.time() - t0:.0f}s, {len(EV['t'])} events", flush=True)
    return 0


# ---------------------------------------------------------------- cover

def _cover(ix: np.ndarray) -> list[tuple]:
    G, EV = V._G["G"], V._G["EV"]
    t = EV["t"][ix]
    frames = V._frames(range(int(t.min()), int(t.max()) + 2), EV["j"][ix])
    rows = []
    for i in ix:
        u, k = int(EV["t"][i]), int(EV["j"][i])
        A, B = frames.get((u, k)), frames.get((u + 1, k))
        if A is None:
            rows.append((int(G["year"][u]), 0, np.nan, np.nan, np.nan, np.nan, np.nan))
            continue
        c = A[3]
        rth = np.flatnonzero(np.isfinite(c[:RTH1]))
        last = c[rth[-1]] if len(rth) else np.nan
        dc = abs(last / float(G["C"][u, k]) - 1) if len(rth) else np.nan
        ah = float(np.isfinite(c[RTH1:]).sum())
        if B is None:
            pm = pmv = do = np.nan
        else:
            pm = float(np.isfinite(B[3][:RTH0]).sum())
            pmv = float(np.nansum(B[4][:RTH0] * B[5][:RTH0]))
            o = np.flatnonzero(np.isfinite(B[0][RTH0:]))
            do = abs(B[0][RTH0 + o[0]] / float(G["O"][u + 1, k]) - 1) if len(o) else np.nan
        rows.append((int(G["year"][u]), 1, dc, ah, pm, pmv, do))
    return rows


def cmd_cover(args) -> int:
    G, EV = _setup(args)
    sel = np.flatnonzero(EV["sb"] >= 0)
    rows = np.array([r for part in V._map(_cover, [sel[c] for c in V._chunks(EV["t"][sel])], args.procs)
                     for r in part], float)
    out = {}
    for y in np.unique(rows[:, 0]):
        z = rows[rows[:, 0] == y]
        has = z[z[:, 1] == 1]

        def med(col):
            v = has[:, col]
            v = v[np.isfinite(v)]
            return round(float(np.median(v)), 5) if len(v) else None

        def share(col, f):
            v = has[:, col]
            v = v[np.isfinite(v)]
            return round(float(f(v).mean()), 4) if len(v) else None
        out[str(int(y))] = {"events": int(len(z)), "with_bars": int(len(has)),
                            "close_gap_median": med(2), "close_gap_over_2pct": share(2, lambda v: v > 0.02),
                            "ah_bars_median": med(3), "ah_none": share(3, lambda v: v == 0),
                            "pm_bars_median": med(4), "pm_none": share(4, lambda v: v == 0),
                            "pm_dollars_median": med(5),
                            "open_gap_median": med(6), "open_gap_over_2pct": share(6, lambda v: v > 0.02)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cover.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"events": int(len(rows))}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _row(name: str, d: dict, years: list[str]) -> str:
    cells = []
    for y in years:
        s = d.get(y, {"n": 0})
        cells.append(f"{s['n']} / {s['pf']:.2f} / {s['pf_trim']:.2f} / {100 * s['median']:+.1f}%" if s["n"] else "-")
    return f"| {name} | " + " | ".join(cells) + " |"


def cmd_final(args) -> int:
    D = json.loads((args.res / "daily.json").read_text(encoding="utf-8"))
    M = json.loads((args.res / "minute.json").read_text(encoding="utf-8"))
    C = json.loads((args.res / "cover.json").read_text(encoding="utf-8"))
    yrs = [str(y) for y in range(2016, 2027)]
    head = "| | " + " | ".join(yrs) + " |\n|---|" + "---|" * len(yrs)
    L = ["# v54d report: CRASH-long by year, market or data", "",
         "Cells: trades / PF / PF without the top and bottom 1% / median trade.", "",
         f"## Daily panel only ({D['first_date']} to {D['last_date']}): buy a -20% close, sell the next open (gross)",
         "", "| | " + " | ".join(sorted(D["crash_overnight"])) + " |",
         "|---|" + "---|" * len(D["crash_overnight"])]
    dy = sorted(D["crash_overnight"])
    L.append(_row("all prices, next open", D["crash_overnight"], dy))
    L.append(_row("all prices, next close", D["crash_next_close"], dy))
    for k, d in D["crash_overnight_by_price"].items():
        L.append(_row(f"price {k}, next open", d, dy))
    L.append("| symbols valid | " + " | ".join(str(D["symbols_valid_by_year"].get(y, "-")) for y in dy) + " |")
    L += ["", "## Minute bars: CRASH-long net of TZC costs, filter all", "", head]
    for k, d in M.items():
        if k not in ("events", "codes"):
            L.append(_row(k, d, yrs))
    L += ["", "## Minute bars around CRASH events", "", head]
    for f in ("events", "with_bars", "close_gap_median", "close_gap_over_2pct", "ah_bars_median", "ah_none",
              "pm_bars_median", "pm_none", "pm_dollars_median", "open_gap_median", "open_gap_over_2pct"):
        L.append(f"| {f} | " + " | ".join(str(C.get(y, {}).get(f, "-")) for y in yrs) + " |")
    L += ["", "## Entry codes (c_1555, c_ah0)", ""]
    for en, d in M["codes"].items():
        L.append(f"- {en}: " + "; ".join(f"{y} {v}" for y, v in sorted(d.items())))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V54D_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v54d_summary.json").write_text(json.dumps({"daily": D, "minute": M, "cover": C}, indent=1),
                                                encoding="utf-8")
    print("\n".join(L[:20]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("daily", "minute", "cover"):
        c = sub.add_parser(n)
        c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        c.add_argument("--extras", type=Path, default=Path("outputs/v28/inputs"))
        c.add_argument("--data", type=Path, default=Path("outputs/v53"))
        c.add_argument("--procs", type=int, default=4)
    c = sub.add_parser("final")
    c.add_argument("--res", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"daily": cmd_daily, "minute": cmd_minute, "cover": cmd_cover, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v54d"
    raise SystemExit(main())
