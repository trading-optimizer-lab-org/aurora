"""v18 shards and report. Pre-registered in docs/research/V18_PREREGISTRATION.md.

  shard   the v18 configurations: real returns at half-spreads x0.5, x1, x2 and gross; 25 placebos a block
  report  the v14 report procedure over the v18 parts (COMBO18 = v18 families), plus the gross record and the
          2023-07-01 to 2026-10-16 segment
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
from aurora.research import v16_small as v16
from aurora.research import v18_rules as v18


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R16 = _script("run_v16")
R14 = R16.R14
SHARDS = 300
SEGMENT = ("2023-07-01", "2026-10-16")


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v18.INTRA_DIMS.items()}
    out.update({k: ("daily", core.grid(d)) for k, d in v18.DAILY_DIMS.items()})
    out.update({k: ("weekly", core.grid(d)) for k, d in v18.WEEKLY_DIMS.items()})
    out.update({k: ("macro", core.grid(d)) for k, d in v18.MACRO_DIMS.items()})
    return out


def units() -> list[tuple[str, int, int]]:
    return [(k, i, b) for k, (_, cfgs) in registry().items() for i in range(len(cfgs)) for b in range(R14.N_BLOCKS)]


_P: dict = {}


def load(v14_inputs: Path, v15_inputs: Path, v16_inputs: Path, v17_inputs: Path, v18_inputs: Path) -> None:
    R16.load(v14_inputs, v15_inputs, v16_inputs)
    store = R14._G["store"]
    for path, cols in ((v17_inputs / "flags.parquet", ("earn", "offer")),
                       (v18_inputs / "flags.parquet", ("catalyst", "runs60", "sr_prev", "off_prev", "shelf30"))):
        flags = pd.read_parquet(path)
        for col in cols:
            store.cands[col] = flags[col].reindex(store.cands.index)
    for col in ("earn", "offer", "shelf30"):
        store.cands[col] = store.cands[col].fillna(False).astype(bool)
    store.cands["catalyst"] = store.cands["catalyst"].fillna("none")
    R16._W["E"].update(R14.PREP.load(v18_inputs / "extras.pkl"))


def _fee3(table: dict) -> dict:
    return {k: (v[0], v[1] * 3 if np.isfinite(v[1]) else v[1], v[2]) for k, v in table.items()}


def real_and_placebo(key: str, ci: int, block: int) -> tuple[dict, dict, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    G, W = R14._G, R16._W
    D, store = G["D"], G["store"]
    dates, table, E = D["dates"], W["table"], W["E"]
    reps = range(block * R14.BLOCK + 1, (block + 1) * R14.BLOCK + 1)
    real, plac, stats = {}, {}, {}
    if kind == "intra":
        trades = v18.intraday_trades(store, key, g)
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0), ("high", 2.0)):
                real[sc] = v18.book(trades, dates, table, mult)
            real["gross"] = v18.book(trades, dates, table, 0.0, gross=True)
            if len(trades):
                stats = {"trades": int(len(trades)),
                         "avg_gross": float((trades["side"] * (trades["exit"] / trades["entry"] - 1)).mean())}
        pk = (key, g.get("band"))
        if pk not in _P:
            _P[pk] = v18.pool_by_day(store, key, g.get("band"))
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v18.book(v18.intraday_placebo(store, trades, rng, _P[pk]), dates, table, 1.0)
    elif kind == "daily":
        sp, weight, max_open = v18.daily_specs(D, E, key, g)
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0)):
                real[sc] = v16.daily_book(D, sp, table, mult, weight, max_open)
            real["high"] = v16.daily_book(D, sp, _fee3(table), 2.0, weight, max_open)  # v18b: fees x3 too
            keep = core.COMMISSION
            try:
                core.COMMISSION = 0.0
                free = {k: (v[0], 0.0, v[2]) for k, v in table.items()}  # availability kept, no borrow fee
                real["gross"] = v16.daily_book(D, sp, free, 0.0, weight, max_open)
            finally:
                core.COMMISSION = keep
            stats = {"trades": len(sp)}
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v16.daily_book(D, vs.placebo_specs(D, key, sp, rng), table, 1.0, weight, max_open)
    elif kind == "weekly":
        if block == 0:
            for sc, mult in (("low", 0.5), ("mid", 1.0)):
                real[sc] = v18.weekly(D, E, key, g, table, mult)
            real["high"] = v18.weekly(D, E, key, g, _fee3(table), 2.0)
            real["gross"] = v18.weekly(D, E, key, g, {k: (v[0], 0.0, v[2]) for k, v in table.items()}, 0.0)
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v18.weekly(D, E, key, g, table, 1.0, rng=rng)
    else:
        net = v18.iwm_tom(G["X"], g)
        if block == 0:
            real = {sc: net for sc in ("low", "mid", "high", "gross")}
        for rep in reps:
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            plac[rep] = v18.iwm_tom(G["X"], g, shift=int(rng.integers(60, 501)))
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
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v18 runs on the whole sample: the unlock must be set")
    load(args.v14_inputs, args.v15_inputs, args.v16_inputs, args.v17_inputs, args.v18_inputs)
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
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v18 runs on the whole sample: the unlock must be set")
    R14.registry = registry
    R14.units = units
    args.exclude = []
    args.title = "v18: small caps, wide (302 configurations, walk-forward 2018-2026, pre-registered)"
    rc = R14.cmd_report(args)
    summary = json.loads((args.out / "summary.json").read_text(encoding="utf-8"))
    streams = pd.read_parquet(args.out / "streams.parquet")
    real = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("real.parquet"))], axis=1)
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cash = D["cash"]
    lines = ["", "## The gross record and the 2023-07+ segment", "",
             "| family | WF Sortino gross (no costs) | WF Sortino middle | 2023-07 to 2026-10 middle | CAGR there | max DD there |",
             "|---|---|---|---|---|---|"]
    seg = {}
    for fam, info in summary["families"].items():
        picks = {int(y): n for y, n in info["picks"].items()}
        parts = [real[f"{n}|gross"].reindex(D["dates"]).fillna(0.0).loc[f"{y}-01-01":f"{y}-12-31"]
                 for y, n in picks.items() if f"{n}|gross" in real]
        g = pd.concat(parts) if parts else pd.Series(dtype=float)
        sg = R14._stats(g, cash, "2018-01-01", SEGMENT[1]) if len(g) else {}
        st = R14._stats(streams[fam], cash, *SEGMENT) if fam in streams else {}
        seg[fam] = st
        lines.append(f"| {fam} | {sg.get('sortino', np.nan):.2f} | {info['wf'].get('sortino', np.nan):.2f} | "
                     f"{st.get('sortino', np.nan):.2f} | {st.get('cagr', np.nan):.1%} | {st.get('dd', np.nan):.1%} |")
    combo_seg = R14._stats(streams["COMBO"], cash, *SEGMENT)
    ok = bool(summary["criterion"] and combo_seg.get("sortino", 0) >= 3)
    lines += ["", f"COMBO18 over 2023-07-01 to 2026-10-16: Sortino {combo_seg.get('sortino', np.nan):.2f}, "
                  f"CAGR {combo_seg.get('cagr', np.nan):.1%}, max DD {combo_seg.get('dd', np.nan):.1%}.",
              f"Pre-registered criterion (walk-forward >= 4, halves >= 3, PBO < 20%, 2023-07+ >= 3): "
              f"{'met' if ok else 'not met'}."]
    with open(args.out / "REPORT.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    summary.update({"segment": seg, "combo_segment": combo_seg, "criterion_v18": ok})
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("\n".join(lines), flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    for a in ("v14", "v15", "v16", "v17", "v18"):
        s.add_argument(f"--{a}-inputs", type=Path, default=Path(f"outputs/v18/{a}"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v18/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
