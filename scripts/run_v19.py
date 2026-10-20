"""v19 shards, selection and report. Pre-registered in docs/research/V19_PREREGISTRATION.md.

  real     every v19 configuration: daily returns at half-spreads x0.5, x1 and x2 (borrow fees x3 at x2) and gross,
           plus the statistics of the trades the middle-cost book took
  select   the walk-forward pick of each family for each year and its best design configuration: the only
           configurations whose placebos the report uses (the picks depend on the real returns only)
  placebo  200 placebos of each selected configuration, 25 a unit
  report   the v14 report procedure over the v19 families (COMBO19), the gross record, the 2023-07+ segment, the
           trades of each family's walk-forward stream and how each entry and exit choice did
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
from aurora.research import v19_grid as v19


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R18 = _script("run_v18")
R16, R14 = R18.R16, R18.R14
SHARDS = 300
SEGMENT = R18.SEGMENT
SCENARIOS = (("low", 0.5, 1.0), ("mid", 1.0, 1.0), ("high", 2.0, 3.0))  # (name, spread multiple, fee multiple)


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v19.INTRA_DIMS.items()}
    out.update({k: ("daily", core.grid(d)) for k, d in v19.DAILY_DIMS.items()})
    return out


def configs() -> list[tuple[str, int]]:
    return [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]


def _names(text: str) -> list[tuple[str, int]]:
    return [(n.split("|")[0], int(n.split("|")[1])) for n in text.split(",") if n]


def load(base: Path) -> None:
    R18.load(base / "v14", base / "v15", base / "v16", base / "v17", base / "v18")


def _books(key: str, g: dict):
    """The configuration's trades and a function (spread, fee multiple, gross) -> (daily returns, paths, taken)."""
    kind = registry()[key][0]
    D, store = R14._G["D"], R14._G["store"]
    table, E = R16._W["table"], R16._W["E"]
    if kind == "intra":
        trades = v19.intraday_trades(store, D, key, g)
        return trades, lambda sp, fm, gr: v19.intra_book(trades, D["dates"], table, sp, fm, gr)
    specs = v19.daily_specs(D, E, key, g)
    return specs, lambda sp, fm, gr: v19.daily_book(D, specs, table, sp, fm, gr)


def _design(s: pd.Series) -> pd.Series:
    return s.loc[core.DESIGN_START:core.last_day()]


def real_returns(key: str, ci: int) -> tuple[dict, dict]:
    g = registry()[key][1][ci]
    dates = R14._G["D"]["dates"]
    trades, book = _books(key, g)
    real, stats = {}, {"signals": len(trades)}
    for sc, spread, fee in SCENARIOS:
        s, paths, taken = book(spread, fee, False)
        real[sc] = s
        if sc == "mid":
            stats.update(v19.trade_stats(paths, taken, dates))
    real["gross"] = book(0.0, 1.0, True)[0]
    return {k: _design(v) for k, v in real.items()}, stats


_P: dict = {}


def placebo_returns(key: str, ci: int, block: int) -> dict:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store, table = R14._G["D"], R14._G["store"], R16._W["table"]
    trades, _ = _books(key, g)
    out = {}
    for rep in range(block * R14.BLOCK + 1, (block + 1) * R14.BLOCK + 1):
        rng = np.random.default_rng(R14._seed(key, ci, rep))
        if kind == "intra":
            pk = (key, g["band"])
            if pk not in _P:
                _P[pk] = v19.pool_by_day(store, key, g["band"])
            s = v19.intra_book(v19.intraday_placebo(store, D, trades, rng, _P[pk]), D["dates"], table, 1.0)[0]
        else:
            s = v19.daily_book(D, v19.daily_placebo(D, trades, rng, g.get("band")), table, 1.0)[0]
        m = core.monthly(_design(s).to_frame("r"))["r"]
        m.index = m.index.to_timestamp()
        out[rep] = m
    return out


def _work(u):
    t0 = time.time()
    try:
        if len(u) == 2:
            real, stats = real_returns(*u)
            return u, real, {}, stats, time.time() - t0, None
        return u, {}, placebo_returns(*u), {}, time.time() - t0, None
    except Exception as exc:  # recorded and reported
        return u, {}, {}, {}, time.time() - t0, f"{type(exc).__name__}: {exc}"


def _run(units: list, args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v19 runs on the whole sample: the unlock must be set")
    load(args.inputs)
    mine = units[args.shard::args.shards]
    print(f"shard {args.shard}: {len(mine)} units", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            res = list(pool.imap_unordered(_work, mine))
    else:
        res = [_work(u) for u in mine]
    real_cols, plac_cols, meta = {}, {}, []
    for u, real, plac, stats, sec, err in res:
        key, ci = u[0], u[1]
        for sc, s in real.items():
            real_cols[f"{key}|{ci}|{sc}"] = s.astype(np.float32)
        for rep, m in plac.items():
            plac_cols[f"{key}|{ci}|{rep}"] = m.astype(np.float32)
        meta.append({"key": key, "ci": ci, "block": u[2] if len(u) > 2 else -1, "sec": round(sec, 1),
                     "error": err, **stats})
    args.out.mkdir(parents=True, exist_ok=True)
    if real_cols:
        pd.DataFrame(real_cols).to_parquet(args.out / "real.parquet")
    if plac_cols:
        pd.DataFrame(plac_cols).to_parquet(args.out / "placebo.parquet")
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"shard done: {len(res)} units, {len(errs)} errors", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    return 0


def cmd_real(args) -> int:
    return _run(configs(), args)


def cmd_placebo(args) -> int:
    units = [(k, i, b) for k, i in _names(args.selected) for b in range(R14.N_BLOCKS)]
    return _run(units, args)


def choices(real: pd.DataFrame, D: dict) -> dict[str, dict]:
    """Each family's walk-forward picks and best design configuration, exactly as the v14 report computes them."""
    reg = registry()
    end = core.last_day()
    cash = D["cash"]
    R_all = real.reindex(D["dates"]).fillna(0.0).loc[core.DESIGN_START:end]
    fams: dict[str, list[str]] = {}
    for key, (_, cfgs) in reg.items():
        fams.setdefault(R14.family_of(key), []).extend([f"{key}|{i}" for i in range(len(cfgs))])
    out = {}
    for fam, names in fams.items():
        names = [n for n in names if n + "|mid" in R_all]
        if not names:
            continue
        R = R_all[[n + "|mid" for n in names]].copy()
        R.columns = names
        nb = core.neighbours([{"rule": n.split("|")[0], **reg[n.split("|")[0]][1][int(n.split("|")[1])]}
                              for n in names])
        _, picks = core.walk_forward(R, cash, nb, end=end)
        design = {c: core.sortino(R[c], cash) for c in R.columns}
        out[fam] = {"picks": {int(y): v[0] for y, v in picks.items()}, "best": max(design, key=lambda c: design[c])}
    return out


def cmd_select(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v19 runs on the whole sample: the unlock must be set")
    parts = sorted(args.parts.rglob("real.parquet"))
    real = pd.concat([pd.read_parquet(p) for p in parts], axis=1)
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    D = R14.PREP.load(args.inputs / "v14" / "daily.pkl")
    ch = choices(real, D)
    names = sorted({n for c in ch.values() for n in [*c["picks"].values(), c["best"]]})
    (args.out / "real").mkdir(parents=True, exist_ok=True)
    real.to_parquet(args.out / "real" / "real.parquet")
    (args.out / "real" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (args.out / "selected.json").write_text(json.dumps({"choices": ch, "names": names}, indent=1), encoding="utf-8")
    (args.out / "selected.txt").write_text(",".join(names), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"configurations {len(meta)} of {len(configs())}, errors {len(errs)}; selected {len(names)}", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    return 0


# ---------------------------------------------------------------- report

def _trades_line(fam: str, picks: dict, stats: dict, months: int) -> str:
    n = s = w = 0
    worst = 0.0
    for y, name in picks.items():
        a = stats.get(name, {}).get("years", {}).get(str(y))
        if a:
            n, s, w, worst = n + a[0], s + a[1], w + a[2], min(worst, a[3])
    if not n:
        return f"| {fam} | 0 | - | - | - |"
    return f"| {fam} | {n / months:.1f} | {s / n:+.1%} | {w / n:.0%} | {worst:+.0%} |"


def _choices_lines(fam: str, keys: list[str], sortino: pd.Series, picks: dict) -> list[str]:
    reg = registry()
    rows = []
    for key in keys:
        cfgs = reg[key][1]
        for dim in cfgs[0]:
            parts = []
            for val in dict.fromkeys(c[dim] for c in cfgs):
                ids = [f"{key}|{i}" for i, c in enumerate(cfgs) if c[dim] == val]
                med = float(np.nanmedian(sortino.reindex(ids))) if len(ids) else np.nan
                n_pick = sum(1 for p in picks.values() if p in ids)
                parts.append(f"{val} {med:.2f} ({n_pick})")
            rows.append(f"| {fam} | {dim} | {' / '.join(parts)} |")
    return rows


def cmd_report(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v19 runs on the whole sample: the unlock must be set")
    sel = json.loads(args.selected.read_text(encoding="utf-8"))
    R14.registry = registry
    R14.units = lambda: [(k, i, 0) for k, i in configs()] + [(k, i, b) for k, i in _names(",".join(sel["names"]))
                                                            for b in range(R14.N_BLOCKS)]
    args.exclude = []
    args.title = (f"v19: small caps, entry x exit grids ({len(configs())} configurations, walk-forward 2018-2026, "
                  "pre-registered)")
    rc = R14.cmd_report(args)
    summary = json.loads((args.out / "summary.json").read_text(encoding="utf-8"))
    streams = pd.read_parquet(args.out / "streams.parquet")
    real = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("real.parquet"))], axis=1)
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    stats = {f"{m['key']}|{m['ci']}": m for m in meta if m.get("block") == -1}
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cash, end = D["cash"], core.last_day()
    lines = ["", "## The gross record and the 2023-07+ segment", "",
             "| family | WF Sortino gross (no costs) | WF Sortino middle | 2023-07 to 2026-10 middle | CAGR there | "
             "max DD there |", "|---|---|---|---|---|---|"]
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
    months = len(pd.period_range("2018-01", end.strftime("%Y-%m"), freq="M"))
    lines += ["", "## Trades of each family's walk-forward stream (middle costs, trades the book took)", "",
              "| family | trades a month | mean net return a trade | win rate | worst trade |", "|---|---|---|---|---|"]
    lines += [_trades_line(fam, {int(y): n for y, n in info["picks"].items()}, stats, months)
              for fam, info in summary["families"].items()]
    mid = real[[c for c in real.columns if c.endswith("|mid")]].reindex(D["dates"]).fillna(0.0).loc["2018-01-01":end]
    M = core.monthly(mid)
    cm = core.monthly(cash.reindex(mid.index).fillna(0.0).to_frame("c"))["c"].to_numpy()
    sortino = pd.Series(core.sortino_cols(M.to_numpy(), cm), index=[c[:-4] for c in mid.columns])
    lines += ["", "## Entry and exit choices", "",
              "Median 2018-2026 Sortino (middle costs, whole period, so in sample) of all configurations with each "
              "value, and in brackets the number of walk-forward years that picked it.", "",
              "| family | dimension | value median (years picked) |", "|---|---|---|"]
    reg = registry()
    for fam, info in summary["families"].items():
        keys = [k for k in reg if R14.family_of(k) == fam]
        lines += _choices_lines(fam, keys, sortino, info["picks"])
    lines += ["", "## Latest pick of each family", ""]
    for fam, info in summary["families"].items():
        if info["picks"]:
            y, name = max(info["picks"].items())
            key, ci = name.split("|")
            lines.append(f"- {fam} {y}: {name} = {reg[key][1][int(ci)]}")
    chosen = sel["choices"]
    mismatch = [f for f, info in summary["families"].items()
                if {int(y): n for y, n in info["picks"].items()} != {int(y): n for y, n in chosen[f]["picks"].items()}]
    combo_seg = R14._stats(streams["COMBO"], cash, *SEGMENT)
    ok = bool(summary["criterion"] and combo_seg.get("sortino", 0) >= 3)
    lines += ["", f"Selection check: picks that differ from the selection job: {mismatch or 'none'}.",
              "", f"COMBO19 over 2023-07-01 to 2026-10-16: Sortino {combo_seg.get('sortino', np.nan):.2f}, "
                  f"CAGR {combo_seg.get('cagr', np.nan):.1%}, max DD {combo_seg.get('dd', np.nan):.1%}.",
              f"Pre-registered criterion (walk-forward >= 4, halves >= 3, PBO < 20%, 2023-07+ >= 3): "
              f"{'met' if ok else 'not met'}."]
    with open(args.out / "REPORT.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    summary.update({"segment": seg, "combo_segment": combo_seg, "criterion_v19": ok, "pick_mismatch": mismatch,
                    "config_sortino_2018": sortino.round(4).to_dict()})
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("\n".join(lines), flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("real", "placebo"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, required=True)
        s.add_argument("--shards", type=int, default=SHARDS)
        s.add_argument("--workers", type=int, default=4)
        s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        s.add_argument("--out", type=Path, required=True)
        if name == "placebo":
            s.add_argument("--selected", required=True, help="comma-separated key|ci names")
    s = sub.add_parser("select")
    s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    s.add_argument("--parts", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--selected", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v19/report"))
    args = ap.parse_args()
    return {"real": cmd_real, "placebo": cmd_placebo, "select": cmd_select, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
