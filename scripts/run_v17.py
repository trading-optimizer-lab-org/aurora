"""v17 shards and report. Pre-registered in docs/research/V17_PREREGISTRATION.md.

  shard   the v17 configurations (real returns at half-spreads x0.5, x1, x2; 25 placebos a block)
  report  the v14 report procedure over the v14-v17 parts; COMBO17 excludes the v14 B8 and v15's B8R2
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

from aurora.research import v14_core as core
from aurora.research import v15_ah as v15
from aurora.research import v16_small as v16
from aurora.research import v17_ideas as v17


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R16 = _script("run_v16")
R15, R14 = R16.R15, R16.R14
SHARDS = 300
V16_COMBINED = R16.combined


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v17.INTRA_DIMS.items()}
    out.update({k: ("index", core.grid(d)) for k, d in v17.INDEX_DIMS.items()})
    out.update({k: ("macro", core.grid(d)) for k, d in v17.MACRO_DIMS.items()})
    out.update({k: ("weekly", core.grid(d)) for k, d in v17.WEEKLY_DIMS.items()})
    return out


def combined() -> dict[str, tuple[str, list[dict]]]:
    return {**V16_COMBINED(), **registry()}


def units() -> list[tuple[str, int, int]]:
    return [(k, i, b) for k, (_, cfgs) in registry().items() for i in range(len(cfgs)) for b in range(R14.N_BLOCKS)]


_P: dict = {}


def load(v14_inputs: Path, v15_inputs: Path, v16_inputs: Path, v17_inputs: Path) -> None:
    R16.load(v14_inputs, v15_inputs, v16_inputs)
    flags = pd.read_parquet(v17_inputs / "flags.parquet")
    store = R14._G["store"]
    for col in ("earn", "offer"):
        store.cands[col] = flags[col].reindex(store.cands.index).fillna(False).astype(bool)


def real_and_placebo(key: str, ci: int, block: int) -> tuple[dict, dict, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    G, W = R14._G, R16._W
    D, store = G["D"], G["store"]
    dates, table = D["dates"], W["table"]
    reps = range(block * R14.BLOCK + 1, (block + 1) * R14.BLOCK + 1)
    real, plac, stats = {}, {}, {}
    if kind == "intra":
        trades = v17.intraday_trades(store, key, g)
        tv = v15._v15_cols(trades)
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v15.book(tv, dates, table, mult, fixed=False)
            if len(trades):
                stats = {"trades": int(len(trades)),
                         "avg_gross": float((trades["side"] * (trades["exit"] / trades["entry"] - 1)).mean())}
        if key not in _P:
            _P[key] = v17.pool_by_day(store, key)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            pt = v16.intraday_placebo(store, key, trades, rng, _P[key])
            plac[rep] = v15.book(v15._v15_cols(pt), dates, table, 1.0, fixed=False)
    elif kind == "index":
        d, r = v17.idx_gap(G["index"], g)
        net = (r - 2 * 0.0002 * d.abs()).reindex(dates).fillna(0.0)
        if block == 0:
            real = {sc: net for sc in core.SCENARIOS}
        gross_close = pd.Series({day: float(b[4][-1]) / float(b[1][0]) - 1
                                 for day, (pc, b) in G["index"][g["inst"]].items() if len(b[0])}).reindex(d.index)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            ds = pd.Series(np.roll(d.to_numpy(), int(rng.integers(60, 501))), index=d.index)
            plac[rep] = (ds * gross_close - 2 * 0.0002 * ds.abs()).reindex(dates).fillna(0.0)
    elif kind == "macro":
        net = v17.macro(key, g, G["X"])
        if block == 0:
            real = {sc: net for sc in core.SCENARIOS}
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v17.macro(key, g, G["X"], shift=int(rng.integers(60, 501)))
    else:
        E = W["E"]
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v17.week_rev(D, E, g, table, mult)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v17.week_rev(D, E, g, table, 1.0, rng=rng)
    real = {k: v.loc[core.DESIGN_START:core.last_day()] for k, v in real.items()}
    out = {}
    for k, v in plac.items():
        m = core.monthly(v.loc[core.DESIGN_START:core.last_day()].to_frame("r"))["r"]
        m.index = m.index.to_timestamp()
        out[k] = m
    return real, out, stats


def _work(u):
    t0 = time.time()
    try:
        real, plac, stats = real_and_placebo(*u)
        return u, real, plac, stats, time.time() - t0, None
    except Exception as exc:  # recorded and reported
        return u, {}, {}, {}, time.time() - t0, f"{type(exc).__name__}: {exc}"


def cmd_shard(args) -> int:
    load(args.v14_inputs, args.v15_inputs, args.v16_inputs, args.v17_inputs)
    mine = units()[args.shard::args.shards]
    print(f"shard {args.shard}: {len(mine)} units", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            res = list(pool.imap_unordered(_work, mine))
    else:
        res = [_work(u) for u in mine]
    real_cols, plac_cols, meta = {}, {}, []
    for (key, ci, b), real, plac, stats, sec, err in res:
        for sc, s in real.items():
            real_cols[f"{key}|{ci}|{sc}"] = s.astype(np.float32)
        for rep, m in plac.items():
            plac_cols[f"{key}|{ci}|{rep}"] = m.astype(np.float32)
        meta.append({"key": key, "ci": ci, "block": b, "sec": round(sec, 1), "error": err, **stats})
    args.out.mkdir(parents=True, exist_ok=True)
    if real_cols:
        pd.DataFrame(real_cols).to_parquet(args.out / "real.parquet")
    if plac_cols:
        pd.DataFrame(plac_cols).astype(np.float32).to_parquet(args.out / "placebo.parquet")
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"shard done: {len(res)} units, {len(errs)} errors", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    return 0


def cmd_report(args) -> int:
    R14.registry = combined
    R14.units = lambda: [(k, i, b) for k, (_, c) in combined().items() for i in range(len(c))
                         for b in range(R14.N_BLOCKS)]
    args.exclude = ["B8", "B8R2"]
    args.title = "v14-v17: every family so far, IBKR-calibrated costs (pre-registered)"
    rc = R14.cmd_report(args)
    st = pd.read_parquet(args.out / "streams.parquet")
    if "S1" in st:
        corr = st.loc["2018-01-01":].corr()["S1"].drop("S1").sort_values()
        with open(args.out / "REPORT.md", "a", encoding="utf-8") as f:
            f.write("\n## Daily correlation of every family stream with S1 (2018-2023H1)\n\n")
            f.write(", ".join(f"{k} {v:+.2f}" for k, v in corr.items()) + "\n")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    for a in ("v14", "v15", "v16", "v17"):
        s.add_argument(f"--{a}-inputs", type=Path, default=Path(f"outputs/{a}/inputs"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v17/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
