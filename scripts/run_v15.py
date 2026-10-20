"""v15 shards and report. Pre-registered in docs/research/V15_PREREGISTRATION.md.

  shard   the v15 configurations (real returns in three spread scenarios, 25 placebos a block)
  report  the v14 report procedure over the v14 and v15 parts together; COMBO15 excludes the v14 B8 (replaced
          by B8R1)
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
from aurora.research import v14_intraday as vi
from aurora.research import v15_ah as v15


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R14 = _script("run_v14")
SHARDS = 300
V14_REGISTRY = R14.registry
KIND = {"B8R1_GAPFADE": "b8r", "B8R2_GAPFADE": "b8r", "AH2_B8LATE": "ah2", "AH1_AHFADE": "ahfix",
        "AH3_EARNAH": "ahfix", "AH4_NIGHTPM": "ahfix"}


def registry() -> dict[str, tuple[str, list[dict]]]:
    return {k: (KIND[k], core.grid(d)) for k, d in v15.V15_DIMS.items()}


def combined() -> dict[str, tuple[str, list[dict]]]:
    return {**V14_REGISTRY(), **registry()}


def units() -> list[tuple[str, int, int]]:
    return [(k, i, b) for k, (_, cfgs) in registry().items() for i in range(len(cfgs)) for b in range(R14.N_BLOCKS)]


_V: dict = {}


def load(v14_inputs: Path, v15_inputs: Path) -> None:
    R14.load_inputs(v14_inputs)
    cands = pd.read_parquet(v15_inputs / "ah_cands.parquet")
    arr = np.load(v15_inputs / "ah_store.npz")
    ah = v15.AHStore(cands, {k: arr[k] for k in vi.FIELDS})
    _V.update(ah=ah, index={(d, s): k for k, d, s in zip(cands.index, cands["date"], cands["symbol"])},
              table=R14.PREP.load(v15_inputs / "avail.pkl")["table"])
    c = cands
    _V["runner_pool"] = _by_day(c.index[(c["day_ret"] >= 0.20) & (c["c16"] >= 1) & (c["c16"] <= 20)], c)
    _V["liquid_pool"] = _by_day(c.index[(c["c16"] >= 3) & (c["dv20"] >= 5e6) & np.isfinite(c["nxt_open"]) &
                                        np.isfinite(c["nxt_close"])], c)


def _by_day(ix: pd.Index, c: pd.DataFrame) -> dict:
    out: dict = {}
    for k, d in zip(ix, c.loc[ix, "date"]):
        out.setdefault(pd.Timestamp(d), []).append(k)
    return out


def _fixed_trades(key: str, g: dict) -> pd.DataFrame:
    ah = _V["ah"]
    return {"AH1_AHFADE": v15.ah1, "AH3_EARNAH": v15.ah3, "AH4_NIGHTPM": v15.ah4}[key](ah, g)


def _fixed_placebo(key: str, g: dict, real: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    ah = _V["ah"]
    pool = _V["liquid_pool"] if key == "AH3_EARNAH" else _V["runner_pool"]
    rows = []
    for _, r in real.iterrows():
        ch = pool.get(pd.Timestamp(r["date"]), [])
        if not ch:
            continue
        k = int(rng.choice(ch))
        if key == "AH1_AHFADE":
            t = v15.ah1_trade(ah, k, g["drop"], int(r["minute"]), dist=r["stop"] / r["entry"] - 1)
        elif key == "AH4_NIGHTPM":
            t = v15.ah4_trade(ah, k, g["cover"])
        else:
            t = v15.ah3_trade(ah, k, g["mode"], int(r["side"]))
        if t is not None:
            rows.append(t)
    return pd.DataFrame(rows, columns=v15.COLS)


def real_and_placebo(key: str, ci: int, block: int) -> tuple[dict, dict, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    G = R14._G
    store, dates = G["store"], G["D"]["dates"]
    table = _V["table"]
    reps = range(block * R14.BLOCK + 1, (block + 1) * R14.BLOCK + 1)
    spread = 1.5 if key.startswith("B8R2") else 1.0
    fixed = kind == "ahfix"
    if kind == "b8r":
        base = vi.family_trades(store, "B8_GAPFADE", g)
        trades = v15._v15_cols(base)
    elif kind == "ah2":
        base = vi.family_trades(store, "B8_GAPFADE", {"gap": g["gap"], "entry": "orl5", "exit": "close",
                                                      "pmv": g["pmv"]})
        trades = v15.extend(store, _V["ah"], _V["index"], base, g["cover"])
    else:
        base = trades = _fixed_trades(key, g)
    real, stats = {}, {}
    if block == 0:
        for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
            real[sc] = v15.book(trades, dates, table, spread * mult, fixed)
        if len(trades):
            net = trades["side"] * (trades["exit"] / trades["entry"] - 1)
            stats = {"trades": int(len(trades)), "avg_gross": float(net.mean()),
                     "pf_gross": float(net[net > 0].sum() / -net[net < 0].sum()) if (net < 0).any() else None}
    plac = {}
    for rep in reps:
        rng = np.random.default_rng(R14._seed(key, ci, rep))
        if kind in ("b8r", "ah2"):
            if "B8_GAPFADE" not in G["pools"]:
                G["pools"]["B8_GAPFADE"] = vi.pool_by_day(store, "B8_GAPFADE")
            pb = vi.placebo(store, "B8_GAPFADE", {"exit": "close"} if kind == "ah2" else g, base, rng,
                            G["pools"]["B8_GAPFADE"])
            pt = v15._v15_cols(pb) if kind == "b8r" else v15.extend(store, _V["ah"], _V["index"], pb, g["cover"])
        else:
            pt = _fixed_placebo(key, g, trades, rng)
        plac[rep] = v15.book(pt, dates, table, spread, fixed)
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
    load(args.v14_inputs, args.v15_inputs)
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
    R14.registry = combined  # the v14 report over both runs' parts
    R14.units = lambda: [(k, i, b) for k, (_, c) in combined().items() for i in range(len(c))
                         for b in range(R14.N_BLOCKS)]
    args.exclude = ["B8", "B8R2"]  # B8R2 is the same rule under wider spreads
    args.title = "v14 + v15: IBKR-calibrated shorts and the after-hours session (pre-registered)"
    rc = R14.cmd_report(args)
    avail = R14.PREP.load(args.v15_inputs / "avail.pkl")["stats"]
    with open(args.out / "REPORT.md", "a", encoding="utf-8") as f:
        f.write("\n## IBKR availability calibration (2025-10-21 to 2026-10-16)\n\n")
        f.write(f"Events {avail['events']}, without borrow data {avail['no_borrow_data']}, borrowable "
                f"{avail['share_borrowable']}.\n\n| price | shares out | p | median fee %/yr | events |\n"
                "|---|---|---|---|---|\n")
        for cell, v in avail["cells"].items():
            a, b = cell.split("|")
            f.write(f"| {a} | {b} | {v['p']} | {v['fee']} | {v['n']} |\n")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--v14-inputs", type=Path, default=Path("outputs/v14/inputs"))
    s.add_argument("--v15-inputs", type=Path, default=Path("outputs/v15/inputs"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    r.add_argument("--v15-inputs", type=Path, default=Path("outputs/v15/inputs"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v15/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
