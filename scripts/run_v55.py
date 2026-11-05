"""v55 (V55_PREREGISTRATION.md): v49's book with its close entries decided on Alpaca's free IEX price at 15:50.

  fetch  Alpaca IEX one-minute bars, 09:30-15:49 ET, of every symbol-day of v43's minute store (Actions cache only)
  run    v49's book under TZC with the 15:50 decision taken from one source: sip (v47's O1), iex, iex10
  final  V55_REPORT.md and v55_summary.json
Aggregates only: no prices leave the runner.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v29_iex as I  # noqa: E402
import run_v50 as P  # noqa: E402

W, V, R43 = P.W, P.V, P.R43
D14 = I.D14
BOOK = (0.20, 0.40, 0.20, 5)
SETS = {"TZC": P.TZC}
MAIN = "TZC"
SOURCES = {"sip": None, "iex": None, "iex10": 10}  # the oldest the last IEX bar before 15:50 may be, in minutes
OPEN_M, DECIDE_M = 330, 710  # minutes from 04:00: 09:30 and 15:50
CHECK = P.CHECK
GAIN_MIN, MAX_RUIN = 0.90, P.MAX_RUIN
_G: dict = {"iex": {}, "maxage": None}


# ---------------------------------------------------------------- fetch

def _frame(rows: list[tuple], day: pd.Timestamp) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    if df.empty:
        return pd.DataFrame({"symbol": pd.Series(dtype=str), "minute": pd.Series(dtype=np.int16),
                             **{k: pd.Series(dtype=np.float32) for k in ("h", "l", "c")}})
    start = D14._ny(day, 4, 0)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[(df["minute"] >= OPEN_M) & (df["minute"] < DECIDE_M)][["symbol", "minute", "h", "l", "c"]]
    for k in ("h", "l", "c"):
        df[k] = df[k].astype(np.float32)
    return df.sort_values(["symbol", "minute"]).reset_index(drop=True)


def cmd_fetch(args) -> int:
    src = sorted((args.data / "minutes").glob("*.parquet"))
    args.iex.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()

    def one(p: Path) -> int:
        dst = args.iex / p.name
        if dst.exists():
            return len(pd.read_parquet(dst, columns=["minute"]))
        day = pd.Timestamp(p.stem)
        syms = sorted(pd.read_parquet(p, columns=["symbol"])["symbol"].astype(str).unique())
        rows = []
        for k in range(0, len(syms), 200):
            rows += I._bars_iex(syms[k:k + 200], D14._ny(day, 9, 30), D14._ny(day, 15, 49), headers, limiter)
        df = _frame(rows, day)
        df.to_parquet(dst, index=False)
        return len(df)

    with ThreadPoolExecutor(4) as ex:
        n = list(ex.map(one, src))
    out = {"days": len(src), "bars": int(sum(n)), "days_with_bars": int(sum(x > 0 for x in n)),
           "calls": limiter.calls, "sec": round(time.time() - t0)}
    print(json.dumps(out), flush=True)
    if not out["bars"]:
        raise SystemExit("no IEX bar fetched: the feed or the keys failed")
    return 0


# ---------------------------------------------------------------- the IEX decision

def load_iex(folder: Path) -> None:
    D = R43._G["D"]
    row = {str(d.date()): u for u, d in enumerate(D["dates"])}
    col = {str(c): j for j, c in enumerate(D["cols"])}
    out = {}
    for p in sorted(folder.glob("*.parquet")):
        u = row.get(p.stem)
        if u is None:
            continue
        df = pd.read_parquet(p)
        for sym, g in df.groupby("symbol", sort=False):
            j = col.get(str(sym))
            if j is not None:
                out[(u, j)] = (g["minute"].to_numpy(np.int64),) + tuple(g[k].to_numpy(np.float64) for k in "hlc")
    _G["iex"] = out


def last_minute(t: int, j: int) -> int | None:
    b = _G["iex"].get((t, j))
    if b is None:
        return None
    keep = (b[0] >= OPEN_M) & (b[0] < DECIDE_M) & np.isfinite(b[3])
    return int(b[0][keep][-1]) if keep.any() else None


def iex_decision(t: int, j: int) -> tuple[float, float, float] | None:
    """(price, high, low) at 15:50 from the IEX bars, split-adjusted; None when the bot would have no decision."""
    m = last_minute(t, j)
    if m is None or (_G["maxage"] is not None and m < DECIDE_M - _G["maxage"]):
        return None
    f = float(R43._G["D"]["F"][t, j])
    if not np.isfinite(f) or f <= 0:
        return None
    mm, h, lo, c = _G["iex"][(t, j)]
    keep = (mm >= OPEN_M) & (mm < DECIDE_M) & np.isfinite(c)
    return float(c[keep][-1] * f), float(np.nanmax(h[keep]) * f), float(np.nanmin(lo[keep]) * f)


def patch_iex(D: dict, days: set) -> dict:
    """v47's patch with the IEX decision in place of the consolidated one."""
    for k in ("C", "H", "L"):
        if not D[k].flags.writeable:
            D[k] = D[k].copy()
    keep = {}
    for t, j in days:
        got = iex_decision(t, j)
        if got is None:
            continue
        keep[(t, j)] = tuple(float(D[k][t, j]) for k in ("C", "H", "L"))
        for k, x in zip(("C", "H", "L"), got):
            D[k][t, j] = x
    return keep


def diag(days: list[tuple[int, int]]) -> dict:
    err, ages = [], []
    for t, j in days:
        s = V.at_decision(R43.timeline(t, j))
        x = iex_decision(t, j)
        if s is None or x is None:
            continue
        err.append([abs(a / b - 1) if b > 0 else np.nan for a, b in zip(x, s)])
        ages.append(DECIDE_M - 1 - last_minute(t, j))
    E = np.array(err, float).reshape(-1, 3)
    out = {"sip_days": len(days), "iex_days": len(err), "coverage": len(err) / max(len(days), 1)}
    if len(err):
        a = np.array(ages)
        out["age_min"] = {"median": float(np.median(a)), "p90": float(np.quantile(a, 0.9)),
                          "over10": float((a >= 10).mean())}
        for i, k in enumerate(("price", "high", "low")):
            e = E[np.isfinite(E[:, i]), i]
            out[k] = {"median": float(np.median(e)), "p90": float(np.quantile(e, 0.9)),
                      "p99": float(np.quantile(e, 0.99)), "over1pct": float((e > 0.01).mean())}
    return out


# ---------------------------------------------------------------- run

def cmd_run(args) -> int:
    ds, ns, ru, mn = BOOK
    W._G["mn"] = int(mn)
    P.R40.SIZES = W.sizes_of(ds, ns, ru)
    P.SETS = SETS
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[P.E2K, P.LEVELS]]
    R43.setup(args, tuple(lv2))
    out = {"source": args.source, "book": W.book_id(ds, ns, ru, int(mn))}
    days = V.candidates()
    if args.source != "sip":
        load_iex(args.iex)
        _G["maxage"] = SOURCES[args.source]
        out["diag"] = diag(days)
        V.patch = patch_iex
        days = [k for k in days if iex_decision(*k) is not None]
    V._G.update(rows=P.R35._rows(args), days=days)
    jobs = [(lv, t) for t in P.ENS_TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, st) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
            if lv == W.LEVEL and t == "base":
                out["o1"] = st
    with mp.get_context("fork").Pool(args.procs) as pool:
        R = {job: res for job, res, _ in pool.map(P._job, jobs, chunksize=1)}
        B = dict(pool.map(W._boot_job, [((n, t, s), [R[(lv, t)][n][s] for lv in lv2], ("all", "early", "late"))
                                        for n in SETS for t in P.ENS_TASKS for s in P.SEEDS], chunksize=1))
    out["res"] = {n: {t: {str(s): B[(n, t, s)] for s in P.SEEDS} for t in P.ENS_TASKS} for n in SETS}
    out["sec"] = round(time.time() - t0)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.source}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    e = W.ensemble(out["res"][MAIN]["base"], "all")
    print(args.source, f"ens median {e['med']:,.0f} ruin {e['ruin']:.1%}", json.dumps(out.get("diag")), flush=True)
    return 0


# ---------------------------------------------------------------- final

def verdict(e: dict) -> tuple[bool, bool]:
    ref = e[("sip", "base", "all")]
    check = abs(ref["med"] - CHECK[0]) <= CHECK[2] and abs(ref["ruin"] - CHECK[1]) <= CHECK[3]
    ok = (e[("iex", "base", "all")]["med"] >= GAIN_MIN * ref["med"]
          and all(e[("iex", t, "all")]["ruin"] <= MAX_RUIN for t in P.ENS_TASKS))
    return check, ok


def cmd_final(args) -> int:
    Z = {s: json.loads((args.runs / f"{s}.json").read_text(encoding="utf-8")) for s in SOURCES
         if (args.runs / f"{s}.json").exists()}
    e = {(s, t, smp): W.ensemble(Z[s]["res"][MAIN][t], smp) for s in Z for t in P.ENS_TASKS
         for smp in ("all", "early", "late")}
    check, ok = verdict(e) if {"sip", "iex"} <= set(Z) else (False, False)
    _d = P._d
    L = ["# v55 report: v49's book decided on the free IEX price at 15:50", "",
         f"Pre-registered in V55_PREREGISTRATION.md. Check (sip vs v50 {_d(CHECK[0])}, {CHECK[1]:.1%}): "
         f"{'passed' if check else 'FAILED'}.", "",
         f"## Answer: **{'PASS' if ok else 'NOT MET'}**", "",
         "| source | median | ruin | HOT5 median | HOT5 ruin | 2023+ median | 2023+ ruin | close entries kept / "
         "dropped / added vs the real close |", "|---|---|---|---|---|---|---|---|"]
    for s, z in Z.items():
        a, h, late = e[(s, "base", "all")], e[(s, "hot5", "all")], e[(s, "base", "late")]
        o = z.get("o1", {})
        L.append(f"| {s} | {_d(a['med'])} | {a['ruin']:.1%} | {_d(h['med'])} | {h['ruin']:.1%} | {_d(late['med'])} | "
                 f"{late['ruin']:.1%} | {o.get('kept')} / {o.get('dropped')} / {o.get('added')} |")
    for s, z in Z.items():
        g = z.get("diag")
        if not g:
            continue
        L += ["", f"## {s}: the IEX decision against the consolidated one", "",
              f"Sessions with a decision: {g['iex_days']} of {g['sip_days']} ({g['coverage']:.1%})."]
        if "age_min" in g:
            L.append(f"Age of the last IEX bar before 15:50: median {g['age_min']['median']:.0f} min, 90th "
                     f"percentile {g['age_min']['p90']:.0f} min, {g['age_min']['over10']:.1%} 10 min or older.")
            L += ["", "| | median error | 90th pct | 99th pct | over 1% |", "|---|---|---|---|---|"]
            L += [f"| {k} | {g[k]['median']:.2%} | {g[k]['p90']:.2%} | {g[k]['p99']:.2%} | {g[k]['over1pct']:.1%} |"
                  for k in ("price", "high", "low")]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V55_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v55_summary.json").write_text(json.dumps(
        {"pass": ok, "check": check, "ensemble": {"|".join(k): v for k, v in e.items()},
         "diag": {s: z.get("diag") for s, z in Z.items()}, "o1": {s: z.get("o1") for s, z in Z.items()}},
        indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--data", type=Path, default=Path("outputs/v43"))
    f.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r = sub.add_parser("run")
    r.add_argument("--source", choices=tuple(SOURCES), required=True)
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v55w/runs"))
    g = sub.add_parser("final")
    g.add_argument("--runs", type=Path, required=True)
    g.add_argument("--out", type=Path, default=Path("outputs/v55w/report"))
    args = ap.parse_args()
    return {"fetch": cmd_fetch, "run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v55"
    raise SystemExit(main())
