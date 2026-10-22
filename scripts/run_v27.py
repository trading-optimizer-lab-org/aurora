"""v27: v26 checked on names it never chose from, and two extensions of its picks.
Pre-registered in docs/research/V27_PREREGISTRATION.md. Reads v26's report (``V26_REPORT``, default
outputs/v26w/report).

  V27_STUDY=holdout   run_v22's real and select stages on v26's whole grid, each family split in two halves of the
                      symbols (a hash of the ticker); then ``holdout``: each half's walk-forward picks measured on the
                      other half, and v26's own picks on each half
  V27_STUDY=extend    run_v22's stages (real, select, placebo, report) on v26's picks crossed with a rotation filter
                      and adds to the short on the entry day
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R26 = _script("run_v26")
R22, R19, R16, R14 = R26.R22, R26.R19, R26.R16, R26.R14
STUDY = os.environ.get("V27_STUDY", "holdout")
V26_REPORT = Path(os.environ.get("V26_REPORT", "outputs/v26w/report"))
ROT = ("any", "r05", "r1", "r2")
ROT_MAX = {"any": np.inf, "r05": 0.5, "r1": 1.0, "r2": 2.0}
ADD = ("none", "a10", "a20", "a30")
ADD_STEP = {"none": 0.0, "a10": 0.10, "a20": 0.20, "a30": 0.30}
_S: dict = {}
_HALF: dict = {}


def half_of(sym) -> int:
    """The symbol's half: the parity of the first 32 bits of the SHA-256 of its ticker."""
    s = str(sym)
    if s not in _HALF:
        _HALF[s] = int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) % 2
    return _HALF[s]


def v26_summary() -> dict:
    if "summ" not in _S:
        _S["summ"] = json.loads((V26_REPORT / "summary.json").read_text(encoding="utf-8"))
    return _S["summ"]


def _params(cfg: dict) -> dict:
    return {k: cfg[k] for k in ("hold", "stop", "ext", "rally", "scale")}


# ---------------------------------------------------------------- B: the halves

def registry_h() -> dict:
    if "h" not in _S:
        _S["h"] = {f"H{h}/{k}": v for h in (0, 1) for k, v in R26.registry().items()}
    return _S["h"]


def half_book(k26: str, ci: int, h: int) -> tuple:
    """(daily returns at the middle costs, paths, taken) of a v26 configuration on half h of the symbols."""
    cfg = R26.registry()[k26][1][ci]
    D, table = R14._G["D"], R16._W["table"]
    sh.set_params(_params(cfg))
    v19.set_costs("r4", R22.SLIP, R22.R4)
    try:
        kind, _, x = R26.shield_trades(k26, cfg)
        if kind == "intra":
            if len(x):
                x = x[np.array([half_of(s) for s in x["symbol"]]) == h]
            return v19.intra_book(x, D["dates"], table, 1.0)
        cols = D["cols"]
        return v19.daily_book(D, [s for s in x if half_of(cols[s.j]) == h], table, 1.0)
    finally:
        sh.set_params(None)
        v19.set_costs("r4", R22.SLIP, R22.R4)


def evaluate_h(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    h, k26 = int(key[1]), key.split("/", 1)[1]
    s, paths, taken = half_book(k26, ci, h)
    return {"mid": s}, paths, taken


def _half_unit(u: tuple) -> tuple:
    name, h = u
    k26, ci = R26._split(name)
    return u, half_book(k26, ci, h)[0]


def cmd_holdout(args) -> int:
    """Each half's walk-forward picks on the other half, and v26's own picks on each half."""
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v27 runs on the whole sample: the unlock must be set")
    R19.load(args.inputs)
    sel = json.loads((args.selected / "selected.json").read_text(encoding="utf-8"))["choices"]
    D = R14._G["D"]
    end = core.last_day()
    cal = D["dates"][(D["dates"] >= pd.Timestamp("2018-01-01")) & (D["dates"] <= end)]
    fams: dict = {}
    for fam, ch in sel.items():  # fam: "H0/v19:XS1"
        h, f26 = int(fam[1]), fam.split("/", 1)[1]
        picks = {int(y): n.split("/", 1)[1] for y, n in ch["picks"].items()}
        fams.setdefault(f26, {})[h] = picks
    own = {f: {int(y): n for y, n in i["picks"].items()} for f, i in v26_summary()["families"].items() if i["picks"]}
    units = sorted({(n, h) for f in set(fams) | set(own) for pk in [*fams.get(f, {}).values(), own.get(f, {})]
                    for n in pk.values() for h in (0, 1)})
    print(f"{len(units)} pick-half books", flush=True)
    if args.workers > 1 and os.name != "nt":
        import multiprocessing as mp
        with mp.get_context("fork").Pool(args.workers) as pool:
            got = dict(pool.map(_half_unit, units, chunksize=1))
    else:
        got = dict(_half_unit(u) for u in units)

    def wf(picks: dict, h: int) -> dict:
        s = R26.stitch({n: got[(n, h)] for n in set(picks.values())}, picks, cal, end)
        return R26._stats(s) | {"stream": s}

    rows, streams = [], {}
    for f in sorted(set(fams) | set(own)):
        r: dict = {"family": f}
        for h in (0, 1):
            if h in fams.get(f, {}):
                a, b = wf(fams[f][h], h), wf(fams[f][h], 1 - h)
                r[f"sel{h}_on{h}"], r[f"sel{h}_on{1 - h}"] = a.get("sortino"), b.get("sortino")
                streams[f"{f}|sel{h}|on{1 - h}"] = b["stream"]
                streams[f"{f}|sel{h}|on{h}"] = a["stream"]
        if f in own:
            for h in (0, 1):
                r[f"v26_on{h}"] = wf(own[f], h).get("sortino")
        rows.append(r)
    S = pd.DataFrame(streams)
    agg = {}
    for tag in ("in", "out"):
        cols = [c for c in S.columns if (c.split("|")[1][-1] == c.split("|")[2][-1]) == (tag == "in")]
        if cols:
            agg[tag] = R26._stats(S[cols].mean(axis=1))
    L = ["# v27 B: v26 on the half of the symbols it did not choose from", "",
         "Each family's walk-forward picks chosen on one half of the symbols (run_v22's selection on that half "
         "alone), measured on the same half and on the other; and v26's own picks (chosen on all symbols) on each "
         "half. Monthly Sortino 2018+, middle R4 costs.", "",
         "| family | picked on half 0: on 0 | on 1 (unseen) | picked on half 1: on 1 | on 0 (unseen) | v26 picks on "
         "half 0 | on half 1 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['family']} | {R26._f2(r.get('sel0_on0'))} | {R26._f2(r.get('sel0_on1'))} | "
                 f"{R26._f2(r.get('sel1_on1'))} | {R26._f2(r.get('sel1_on0'))} | {R26._f2(r.get('v26_on0'))} | "
                 f"{R26._f2(r.get('v26_on1'))} |")
    L += ["", "Equal-weight average of the family streams: on the half they were picked on Sortino "
          f"{R26._f2(agg.get('in', {}).get('sortino'))} (CAGR {R26._pc(agg.get('in', {}).get('cagr'))}); on the "
          f"unseen half {R26._f2(agg.get('out', {}).get('sortino'))} (CAGR {R26._pc(agg.get('out', {}).get('cagr'))})."]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "HOLDOUT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "holdout.json").write_text(json.dumps({"families": rows, "average": agg}, indent=1, default=float),
                                           encoding="utf-8")
    S.astype(np.float32).to_parquet(args.out / "holdout_streams.parquet")
    print("\n".join(L), flush=True)
    return 0


# ---------------------------------------------------------------- C: rotation and adds

EXT: dict = {"rot": "any", "add": "none"}
_ORIG_INTRA = sh.intra_row


def rotation_intra(D: dict, cd, b: tuple, j: int) -> float:
    """Shares traded in the session before the entry over the shares outstanding (nan when unknown)."""
    so = float(D["SO"][int(cd["t"]), int(cd["j"])])
    return float(np.sum(b[5][:j])) / so if np.isfinite(so) and so > 0 else np.nan


def rotation_daily(D: dict, E: dict, s) -> float:
    """The entry session's volume (an entry at a close) or the session before's (at an open) over the shares
    outstanding."""
    so = float(D["SO"][s.t, s.j])
    t = s.t if s.kind == "close" else s.t - 1
    v = float(E["V"][t, s.j]) if t >= 0 else np.nan
    return v / so if np.isfinite(so) and so > 0 and np.isfinite(v) else np.nan


def ext_row(D: dict, cd, b: tuple, line: np.ndarray, j: int, e: float, own: float, prio: float) -> dict:
    """The shield's row with the rotation filter and the adds: a third of the position at the entry, a third more at
    the first bar of the entry day that reaches e x (1 + step) and the last third at e x (1 + 2 step), below the
    stop; the adds keep the first part's stop and exit. A trade the filter refuses gets no weight and sorts last."""
    row = _ORIG_INTRA(D, cd, b, line, j, e, own, prio)
    rot = rotation_intra(D, cd, b, j)
    if EXT["rot"] != "any" and not (np.isfinite(rot) and rot <= ROT_MAX[EXT["rot"]]):
        row.update(liq=0.0, minute=10_000, keep=False)
        return row
    row["keep"] = True
    step = ADD_STEP[EXT["add"]]
    if not step:
        return row
    S, P0 = row["stop"], sh.PARAMS
    parts = [(1.0, np.asarray(row["rets"], float), float(row["nights"]))]
    k0 = j
    for n in (1, 2):
        level = e * (1 + n * step)
        if level >= S:
            break
        hit = vi.first_true(b[2] >= level, k0 + 1)
        if hit < 0:
            break
        fill = max(float(b[1][hit]), level)
        sh.set_params({**P0, "stop": "own"})
        try:
            r = _ORIG_INTRA(D, cd, b, line, hit, fill, S, prio)
        finally:
            sh.set_params(P0)
        parts.append((fill / e, np.asarray(r["rets"], float), float(r["nights"])))
        k0 = hit
    n = max(len(p[1]) for p in parts)
    row["rets"] = sum(f / 3 * np.pad(r, (0, n - len(r))) for f, r, _ in parts)
    row["nights"] = sum(x / 3 for _, _, x in parts)
    return row


def registry_e() -> dict:
    if "e" not in _S:
        out = {}
        for fam, info in sorted(v26_summary()["families"].items()):
            picks = sorted(set(info["picks"].values()))
            if not picks:
                continue
            k26 = picks[0].rsplit("|", 1)[0]
            kind = R26.registry()[k26][0]
            adds = ADD if kind == "intra" else ("none",)
            out[k26] = (kind, [{"base": n, "rot": r, "add": a} for n in picks for r in ROT for a in adds])
        _S["e"] = out
    return _S["e"]


def _daily_ok(D: dict, specs: list, rot: str) -> list:
    if rot == "any":
        return specs
    E = R16._W["E"]
    return [s for s in specs if np.isfinite(x := rotation_daily(D, E, s)) and x <= ROT_MAX[rot]]


def evaluate_e(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    cfg = registry_e()[key][1][ci]
    k26, bci = R26._split(cfg["base"])
    bcfg = R26.registry()[k26][1][bci]
    src, fam = k26.split(":")
    D, table = R14._G["D"], R16._W["table"]
    dates = D["dates"]
    EXT.update(rot=cfg["rot"], add=cfg["add"])
    sh.set_params(_params(bcfg))
    v19.set_costs("r4", R22.SLIP, R22.R4)
    try:
        kind, g, data = R26.entries(k26, bcfg["entry"])
        if kind == "intra":
            def rows() -> pd.DataFrame:
                tr = pd.DataFrame([ext_row(D, *a) for a in data])
                tr = tr[tr["keep"]] if len(tr) else pd.DataFrame(columns=v19.COLS)
                return R26._keep_rows(tr[v19.COLS], bcfg["filt"])
            tr = rows()
            if placebo_rng is not None:
                pt = R26._keep_rows(R26._placebo_intra(src, fam, g, tr, placebo_rng), bcfg["filt"])
                return v19.intra_book(pt, dates, table, 1.0)[0], None, None
        else:
            specs = _daily_ok(D, R26._keep_specs(data, bcfg["filt"]), cfg["rot"])
            if placebo_rng is not None:
                pl = (v19.daily_placebo if src == "v19" else R26.v20.daily_placebo)(D, specs, placebo_rng,
                                                                                    g.get("band"))
                return v19.daily_book(D, _daily_ok(D, R26._keep_specs(pl, bcfg["filt"]), cfg["rot"]), table,
                                      1.0)[0], None, None
        out, paths, taken = {}, [], np.zeros(0, bool)
        for name, half, spread, fee, gross in R22.SCEN:
            v19.set_costs("r4", R22.SLIP, half)
            s, p_, t_ = (v19.intra_book(tr, dates, table, spread, fee, gross) if kind == "intra"
                         else v19.daily_book(D, specs, table, spread, fee, gross))
            out[name] = s
            if name == "mid":
                paths, taken = p_, t_
        v19.set_costs("r4", 0.0, R22.R4)
        out["gross"] = (v19.intra_book(rows(), dates, table, 0.0, 1.0, True) if kind == "intra"
                        else v19.daily_book(D, specs, table, 0.0, 1.0, True))[0]
        return out, paths, taken
    finally:
        sh.set_params(None)
        EXT.update(rot="any", add="none")
        v19.set_costs("r4", R22.SLIP, R22.R4)


if STUDY == "holdout":
    R22.registry, R22.configs, R22.evaluate = registry_h, (lambda: [(k, i) for k, (_, c) in registry_h().items()
                                                                     for i in range(len(c))]), evaluate_h
    R22.TITLE, R22.COMBO = "v27 B: v26's grid on two halves of the symbols", "COMBO27B"
else:
    sh.intra_row = ext_row
    R22.registry, R22.configs, R22.evaluate = registry_e, (lambda: [(k, i) for k, (_, c) in registry_e().items()
                                                                     for i in range(len(c))]), evaluate_e
    R22.TITLE, R22.COMBO = "v27 C: v26's picks with a rotation filter and adds", "COMBO27C"


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "holdout":
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        ap.add_argument("--selected", type=Path, default=None)
        ap.add_argument("--workers", type=int, default=4)
        ap.add_argument("--out", type=Path, required=True)
        args = ap.parse_args()
        return cmd_holdout(args)
    return R22.main()


if __name__ == "__main__":
    sys.argv[0] = "run_v27"
    raise SystemExit(main())
