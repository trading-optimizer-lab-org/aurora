"""v37: new daily small-cap members (V37_PREREGISTRATION.md). Three daily short families (first red day of a runner,
float rotation, dead-cat bounce) walked by the shield, picked each year on earlier years, added to v34's limit
book; the choice on 2018-2022 paths.

  real     one shard of the 1,400 configurations alone in A1's account (monthly returns)
  select   the walk-forward picks of each new family
  account  one (size, costs) job: the 8 books' daily returns at the five levels
  final    V37_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R36 = _script("run_v36")
R35, R33 = R36.R35, R36.R33
R29, R32, A, R14, R22, R20, R28 = R33.R29, R33.R32, R33.A, R33.R14, R33.R22, R33.R20, R33.R28
v19, v28, core = R33.v19, R33.A.v28, R33.core
LEVELS = R35.LEVELS
NEW: dict[str, tuple] = {
    "C:FRD_SHORT": tuple((x, w) for x in (0.5, 1.0, 2.0) for w in (3, 5, 10)),
    "C:ROT_SHORT": (1.0, 3.0, 5.0),
    "C:BOUNCE_SHORT": (0.2, 0.4),
}
BANDS, TRIGS = ("low", "high"), ("open", "redclose")
HOLDS, STOPS = ("d1", "d2", "d3", "d5", "d10"), ("own", "pct20", "pct35", "pct50", "atr4")
SETS = {"all": (), "no_both": ("B:v19:ON1", "C:SYMPATHY")}
SIZES: tuple[float, ...] = (0.25, 0.30)
TASKS = ("base",) + R35.STRESS
JOBS = [(s, t) for s in SIZES for t in TASKS]
BOOKS = [(m, s, n) for m in SETS for s in SIZES for n in (False, True)]


def new_grid(key: str) -> list[dict]:
    return [{"param": p, "band": b, "trig": tg, "hold": h, "stop": s, "ext": "none"}
            for p in NEW[key] for b in BANDS for tg in TRIGS for h in HOLDS for s in STOPS]


def _shift(a: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype=float)
    out[k:] = a[:-k]
    return out


def setup_mask(D: dict, key: str, p, so: np.ndarray | None = None, vol: np.ndarray | None = None
               ) -> tuple[np.ndarray, np.ndarray]:
    """The setup sessions of a family (known at their close) and the priority (the size of the move)."""
    C = np.asarray(D["C"], float)
    c1 = _shift(C)
    with np.errstate(invalid="ignore", divide="ignore"):
        r1 = C / c1 - 1
        if key == "C:FRD_SHORT":
            x, w = p
            low = pd.DataFrame(_shift(C, 2)).rolling(w, min_periods=max(2, w // 2)).min().to_numpy()
            run = c1 / low - 1
            S = (run >= x) & (c1 > _shift(C, 2)) & (C < c1)
            return S, np.nan_to_num(run)
        if key == "C:ROT_SHORT":
            assert so is not None and vol is not None
            rot = vol / so
            return (rot >= p) & (r1 >= 0.20), np.nan_to_num(rot)
        peak = pd.DataFrame(c1).rolling(20, min_periods=10).max().to_numpy()
        low40 = pd.DataFrame(c1).rolling(40, min_periods=20).min().to_numpy()
        return (peak >= 2 * low40) & (c1 <= 0.6 * peak) & (r1 >= p), np.nan_to_num(r1)


def new_specs(D: dict, key: str, g: dict) -> list:
    X = v28.X
    vol = X.get("E_V")
    so = np.asarray(D["SO"], float) if key == "C:ROT_SHORT" else None
    p = tuple(g["param"]) if isinstance(g["param"], list) else g["param"]
    S, prio = setup_mask(D, key, p, so, None if vol is None else np.asarray(vol, float))
    S &= v28._base(D) & v28.v18._band_arr(np.asarray(D["P"], float), g["band"])
    rows = v19._setup_trigger(D, S, prio, g["trig"])
    return v19._once_specs(rows, -1, {"stop": "none", "exit": "time"}, 9)


_EVENT_SPECS = v28.event_specs


def _event_specs(D: dict, key: str, g: dict) -> list:
    return new_specs(D, key, g) if key in NEW else _EVENT_SPECS(D, key, g)


def install() -> None:
    v28.event_specs = _event_specs
    reg = R28.registry()
    for key in NEW:
        reg[key] = ("event", new_grid(key))


install()


# ---------------------------------------------------------------- stages

def units() -> list[str]:
    out = [f"{k}|{i}" for k in NEW for i in range(len(new_grid(k)))]
    return [u for k in NEW for u in [x for x in out if x.startswith(k + "|")][:2]] if R29.QUICK else out


def cmd_real(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    return R33._run_units([(u, R33.BASE_VAR) for u in units()[args.shard::args.shards]], args.out)


def sortino(m: np.ndarray) -> float:
    m = m[np.isfinite(m)]
    dn = np.sqrt(np.mean(np.minimum(m, 0.0) ** 2)) if len(m) else 0.0
    return float(m.mean() / dn * np.sqrt(12)) if dn > 0 else 0.0


def cmd_select(args) -> int:
    monthly, counts = R33._read(args.parts, "monthly"), R33._read(args.parts, "counts")
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    months = monthly.index
    cm = R33._cash(args, months)
    out: dict = {"n": len(meta), "errors": [m for m in meta if m["error"]][:20], "picks": {}, "alone": {}}
    for key in NEW:
        names = [n for n in monthly.columns if n.startswith(key + "|")]
        if not names:
            continue
        cfgs = [new_grid(key)[int(n.split("|")[1])] for n in names]
        M = monthly[names].to_numpy(float)
        Cn = counts.reindex(columns=names).fillna(0.0).to_numpy(float)
        Anb = R20.neighbours_matrix([{"rule": key, **{k: str(v) for k, v in c.items()}} for c in cfgs])
        picks = R22.walk_forward(M, Cn, cm, Anb, months, core.last_day().year)
        fam = R14.family_of(key)
        out["picks"][fam] = {str(y): {"name": names[i].rsplit("|", 3)[0], "score": s, "cfg": cfgs[i]}
                             for y, (i, s) in picks.items()}
        wf = np.concatenate([M[months.year == y, i] for y, (i, _) in sorted(picks.items())]) if picks else np.zeros(0)
        out["alone"][fam] = {"years": len(picks), "sortino": sortino(wf), "mean": float(np.nanmean(wf)) if len(wf)
                             else None, "best_in_sample": float(max(sortino(M[:, i]) for i in range(M.shape[1])))}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "picks.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps({"picks": {f: {y: p["name"] for y, p in v.items()} for f, v in out["picks"].items()},
                      "alone": out["alone"]}, indent=1, default=float), flush=True)
    return 0


def new_rows(picks: dict) -> list[dict]:
    return [{"year": int(y), "fam": fam, "name": p["name"], "var": list(R33.BASE_VAR)}
            for fam, by in picks["picks"].items() for y, p in by.items()]


def cmd_account(args) -> int:
    picks = json.loads((args.picks / "picks.json").read_text(encoding="utf-8"))
    rows = R35._rows(args) + new_rows(picks)
    newfams = set(picks["picks"])
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    args.out.mkdir(parents=True, exist_ok=True)
    for size, task in JOBS[args.shard::args.shards][:1 if R29.QUICK else None]:
        R = np.zeros((len(SETS), 2, len(LEVELS), len(pos)))
        for li, level in enumerate(LEVELS):
            its = R35.book_items(rows, float(level), size, None, **R33.TASKS[task])
            for mi, drop in enumerate(SETS.values()):
                for ni in range(2):
                    d = drop if ni else drop + tuple(newfams)
                    R[mi, ni, li] = R36.stream(*R36.apply_rules(its, d, "none"))[pos]
        np.save(args.out / f"acct_{size:.2f}_{task}.npy", R)
        print(size, task, np.round(R[:, :, 1].sum(axis=-1), 2).tolist(), flush=True)
    return 0


def cmd_final(args) -> int:
    picks = json.loads((args.picks / "picks.json").read_text(encoding="utf-8"))
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    rows, stress = [], {}
    for size in SIZES:
        for task in TASKS:
            f = args.runs / f"acct_{size:.2f}_{task}.npy"
            if not f.exists():
                continue
            R = np.load(f)
            for mi, m in enumerate(SETS):
                for ni in range(2):
                    st = R35.book_stats(R[mi, ni], idx if task == "base" else {"all": idx["all"]})
                    if task == "base":
                        rows.append({"set": m, "size": size, "new": bool(ni), **st})
                    else:
                        stress[(m, size, bool(ni), task)] = st["all"]
    c = R36.pick(rows)
    d = R35._d
    L = ["# v37: new daily small-cap members", "", f"{picks['n']} configurations of 3 new daily short families; "
         f"{len(rows)} books; {R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under $1,250 at any time; "
         "v31's liquidation. Choice: highest median on 2018-2022 paths with ruin <= 2.5% there.", "",
         "## 1. The question", ""]
    if c:
        L += [f"Choice: members {c['set']}, size {c['size']:.0%}, new members {c['new']}. All paths: median "
              f"{d(c['all']['med'])}, ruin {c['all']['p_ruin']:.1%}. **Target (median >= $30,000, ruin <= 2.5%) met: "
              f"{R35.met(c)}.**", ""]
    else:
        L += ["No book has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
    L += ["## 2. The new families", "", "| family | years picked | walk-forward Sortino alone | mean month | best "
          "in-sample config Sortino | picks |", "|---|---|---|---|---|---|"]
    for fam, a in picks["alone"].items():
        by = picks["picks"].get(fam, {})
        mean = "-" if a["mean"] is None else f"{a['mean']:.2%}"
        L.append(f"| {fam} | {a['years']} | {a['sortino']:.2f} | {mean} | {a['best_in_sample']:.2f} | " +
                 ", ".join(f"{y}: {p['name'].split('|')[1]}" for y, p in by.items()) + " |")
    L += ["", "## 3. Books", "", "| members | size | new | all median | all ruin | -50% | p10 | 2018-22 median | "
          "2018-22 ruin | 2023+ median | 2023+ ruin | HOT 5% | spreads x2 | high |", "|" + "---|" * 14]
    for r in sorted(rows, key=lambda r: -r["early"]["med"]):
        sx = [stress.get((r["set"], r["size"], r["new"], t)) for t in R35.STRESS]
        L.append(f"| {r['set']} | {r['size']:.0%} | {r['new']} | {d(r['all']['med'])} | {r['all']['p_ruin']:.1%} | "
                 f"{r['all']['p_half']:.1%} | {d(r['all']['p10'])} | {d(r['early']['med'])} | "
                 f"{r['early']['p_ruin']:.1%} | {d(r['late']['med'])} | {r['late']['p_ruin']:.1%} | " +
                 " | ".join(f"{d(x['med'])} / {x['p_ruin']:.1%}" if x else "-" for x in sx) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V37_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v37_summary.json").write_text(json.dumps({"met": R35.met(c), "choice": c, "books": rows,
                                                           "picks": picks, "stress": {"|".join(map(str, k)): v
                                                                                      for k, v in stress.items()}},
                                                          indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("real")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=1)
    s = sub.add_parser("select")
    s.add_argument("--parts", type=Path, required=True)
    a = sub.add_parser("account")
    a.add_argument("--choice", type=Path, required=True)
    a.add_argument("--picks", type=Path, required=True)
    a.add_argument("--shard", type=int, required=True)
    a.add_argument("--shards", type=int, default=1)
    f = sub.add_parser("final")
    f.add_argument("--picks", type=Path, required=True)
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"real": cmd_real, "select": cmd_select, "account": cmd_account, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v37"
    raise SystemExit(main())
