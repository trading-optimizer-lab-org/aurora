"""v16 shards and report. Pre-registered in docs/research/V16_PREREGISTRATION.md.

  shard   the v16 configurations (real returns at half-spreads x0.5, x1, x2; 25 placebos a block)
  report  the v14 report procedure over the v14, v15 and v16 parts; COMBO16 excludes the v14 B8 and v15's B8R2
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
from aurora.research import v14_swing as vs
from aurora.research import v15_ah as v15
from aurora.research import v16_small as v16


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R15 = _script("run_v15")
R14 = R15.R14
SHARDS = 300
V14_REGISTRY = R14.registry


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v16.INTRA_DIMS.items()}
    out.update({k: ("daily", core.grid(d)) for k, d in v16.DAILY_DIMS.items()})
    out.update({k: ("weekly", core.grid(d)) for k, d in v16.WEEKLY_DIMS.items()})
    return out


def combined() -> dict[str, tuple[str, list[dict]]]:
    return {**V14_REGISTRY(), **R15.registry(), **registry()}


def units() -> list[tuple[str, int, int]]:
    return [(k, i, b) for k, (_, cfgs) in registry().items() for i in range(len(cfgs)) for b in range(R14.N_BLOCKS)]


_W: dict = {}


def load(v14_inputs: Path, v15_inputs: Path, v16_inputs: Path) -> None:
    R14.load_inputs(v14_inputs)
    flags = pd.read_parquet(v16_inputs / "flags.parquet")
    store = R14._G["store"]
    for col in ("news", "shelf", "repeat"):
        store.cands[col] = flags[col].reindex(store.cands.index).fillna(False).astype(bool)
    _W.update(E=R14.PREP.load(v16_inputs / "extras.pkl"), table=R14.PREP.load(v15_inputs / "avail.pkl")["table"],
              pools={})


def real_and_placebo(key: str, ci: int, block: int) -> tuple[dict, dict, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store = R14._G["D"], R14._G["store"]
    dates, E, table = D["dates"], _W["E"], _W["table"]
    reps = range(block * R14.BLOCK + 1, (block + 1) * R14.BLOCK + 1)
    real, plac, stats = {}, {}, {}
    if kind == "intra":
        trades = v16.intraday_trades(store, key, g)
        tv = v15._v15_cols(trades)
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v15.book(tv, dates, table, mult, fixed=False)
        if key not in _W["pools"]:
            _W["pools"][key] = v16.pool_by_day(store, key)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            pt = v16.intraday_placebo(store, key, trades, rng, _W["pools"][key])
            plac[rep] = v15.book(v15._v15_cols(pt), dates, table, 1.0, fixed=False)
        if len(trades):
            net = trades["side"] * (trades["exit"] / trades["entry"] - 1)
            stats = {"trades": int(len(trades)), "avg_gross": float(net.mean())}
    elif kind == "daily":
        sp, weight, max_open = v16.daily_specs(D, E, key, g)
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v16.daily_book(D, sp, table, mult, weight, max_open)
            stats = {"trades": len(sp)}
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v16.daily_book(D, vs.placebo_specs(D, key, sp, rng), table, 1.0, weight, max_open)
    else:
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v16.weekly(D, E, key, g, table, mult)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v16.weekly(D, E, key, g, table, 1.0, rng=rng)
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
    load(args.v14_inputs, args.v15_inputs, args.v16_inputs)
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
    args.title = "v14 + v15 + v16: small caps long and short, IBKR-calibrated costs (pre-registered)"
    return R14.cmd_report(args)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    for a in ("v14", "v15", "v16"):
        s.add_argument(f"--{a}-inputs", type=Path, default=Path(f"outputs/{a}/inputs"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v16/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
