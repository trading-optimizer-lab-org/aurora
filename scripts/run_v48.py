"""v48: per-name sizes judged on an ensemble of trade sets (V48_PREREGISTRATION.md).

  run     one shard: one (DS1, NS, RU) size set at 3 and 5 new positions a day, every level and cost set, seeds 0-30
  select  the choice on 2018-2022 paths from the shards
  api     the choice or the base book under v47's API rules (TZA), with the same ensemble
  final   V48_REPORT.md and v48_summary.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v47 as V  # noqa: E402

R43, R40, R35, R33, R32, R29, A = V.R43, V.R40, V.R35, V.R33, V.R32, V.R29, V.A
LEVEL, TASKS, LEVELS, E2K = V.LEVEL, V.TASKS, V.LEVELS, V.E2K
QUICK = R29.QUICK
MEMBERS = list(R40.SIZES)  # DS1, RU, NS: the base book's order, which the account's ties follow
DS1, RU, NS = "B:v19:DS1", "B:v20:RU", "B:v20:NS"
RUS = (0.70, 0.50, 0.40, 0.30, 0.25, 0.20, 0.15)
NSS = (0.40, 0.30, 0.25)
DSS = (0.20, 0.25, 0.30)
NEWS = (3, 5)
COMBOS = [(ds, ns, ru) for ru in RUS for ns in NSS for ds in DSS]
BASE = (0.20, 0.40, 0.70, 3)
SEEDS = tuple(range(3)) if QUICK else tuple(range(31))
DROP = 0.10
ENS_TASKS = ("base", "hot5")
MAX_RUIN = 0.025
CHECK, CHECK_TZA = (22_006.0, 0.001, 200.0, 0.002), (20_742.0, 0.059, 300.0, 0.005)
TZA = V.VARIANTS["TZA"]

_G: dict = {"cap": {}}


def book_id(ds: float, ns: float, ru: float, mn: int) -> str:
    return f"DS{ds:.2f}-NS{ns:.2f}-RU{ru:.2f}-N{mn}"


def sizes_of(ds: float, ns: float, ru: float) -> dict[str, float]:
    s = {DS1: ds, RU: ru, NS: ns}
    return {m: s[m] for m in MEMBERS}


def dropped(it: dict, seed: int) -> bool:
    return seed > 0 and V._u(seed, it["sym"], int(it["t"]), it["member"], "48drop") < DROP


def merge(parts: list[tuple[list, list]]) -> tuple[list, list]:
    """Members' replayed trades joined into one book, each trade pointing at its replay in the joined list."""
    items: list[dict] = []
    recs: list[dict] = []
    for its, rs in parts:
        items += [{**it, "_rec": it["_rec"] + len(recs)} for it in its]
        recs += rs
    return items, recs


def account(items: list[dict], recs: list[dict], max_new: int) -> np.ndarray:
    D = R43._G["D"]
    _, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, max_new, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return R43.liquidate(taken, recs, len(D["dates"]), V.LIQ, V.PART)


def ensemble(per_seed: dict, sample: str) -> dict:
    """Mean median and ruin over the seeds, the 90th percentile of ruin, and seed 0's."""
    m = np.array([per_seed[s][sample]["med"] for s in per_seed])
    r = np.array([per_seed[s][sample]["p_ruin"] for s in per_seed])
    z = per_seed[min(per_seed, key=int)][sample]
    return {"med": float(m.mean()), "ruin": float(r.mean()), "ruin90": float(np.quantile(r, 0.9)),
            "med0": float(z["med"]), "ruin0": float(z["p_ruin"])}


def choose(books: dict) -> str | None:
    """The eligible book (ensemble ruin on 2018-2022 paths at most 2.5% at base costs and HOT 5%) with the highest
    ensemble median on 2018-2022 paths."""
    ok = [b for b, z in books.items()
          if all(ensemble(z["res"][t], "early")["ruin"] <= MAX_RUIN for t in ENS_TASKS)]
    return max(ok, key=lambda b: ensemble(books[b]["res"]["base"], "early")["med"]) if ok else None


def _setup(args, sizes: dict[str, set], tasks) -> None:
    """v43's setup with each member captured alone at each of its sizes."""
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    D = R43.R14._G["D"]
    R43._G["D"] = D
    rows = R35._rows(args)
    _G["rows"] = rows
    keep = R40.SIZES
    try:
        for m, ss in sizes.items():
            for s in ss:
                R40.SIZES = {m: s}
                for lv in np.r_[E2K, LEVELS]:
                    for task in tasks:
                        _G["cap"][(m, s, float(lv), task)] = R43.capture(rows, float(lv), task)
    finally:
        R40.SIZES = keep
    R43.load_bars(args.data / "minutes", D)
    cal, pos = R29._cal()
    R43._G.update(pos=pos, years=np.asarray(cal.year), ys=sorted(set(int(y) for y in cal.year)), cal=cal)


def _boot(Rs: list[np.ndarray], samples: tuple[str, ...]) -> dict:
    idx = R32._sub_idx(R43._G["cal"])
    return R43.boot(np.stack(Rs[1:]), {k: idx[k] for k in samples})


# ---------------------------------------------------------------- run

def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    sz = _G["sizes"]
    items, recs = merge([V.items_for(*_G["cap"][(m, sz[m], level, task)], {}) for m in MEMBERS])
    seeds = SEEDS if task in ENS_TASKS else (0,)
    out, count = {}, {}
    for mn in NEWS:
        for s in seeds:
            R43._G["count"] = {}
            out[(mn, s)] = account([it for it in items if not dropped(it, s)], recs, mn)[R43._G["pos"]]
            if s == 0 and level == LEVEL and task == "base":
                count[mn] = {"candidates": len(items), **R43._G["count"]}
    halves = {}
    if level == LEVEL and task == "base":
        for mn in NEWS:
            halves[mn] = [float(np.nansum(R40.year_stats(
                account([it for it in items if V.half_of(it["sym"]) == h], recs, mn)[R43._G["pos"]],
                R43._G["years"], R43._G["ys"])[:, 0])) for h in (0, 1)]
    return job, out, count, halves


def cmd_run(args) -> int:
    ds, ns, ru = COMBOS[args.shard]
    _G["sizes"] = sizes_of(ds, ns, ru)
    t0 = time.time()
    _setup(args, {m: {s} for m, s in _G["sizes"].items()}, TASKS)
    lv2 = [float(x) for x in np.r_[E2K, LEVELS]]
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_job, [(lv, t) for t in TASKS for lv in lv2], chunksize=1)
    R = {(lv, t, mn, s): r for (lv, t), out, _, _ in got for (mn, s), r in out.items()}
    count = {mn: c for (_, _, cnt, _) in got for mn, c in cnt.items()}
    halves = {mn: h for (_, _, _, hv) in got for mn, h in hv.items()}
    books = {}
    for mn in NEWS:
        res = {}
        for t in TASKS:
            seeds = SEEDS if t in ENS_TASKS else (0,)
            samples = ("all", "early", "late") if t in ENS_TASKS else ("all",)
            res[t] = {str(s): _boot([R[(lv, t, mn, s)] for lv in lv2], samples) for s in seeds}
        idx = R32._sub_idx(R43._G["cal"])
        two = R43.boot(np.stack([R[(lv, "base", mn, 0)] for lv in lv2]), {"all": idx["all"]}, E2K, np.r_[E2K, LEVELS])
        books[book_id(ds, ns, ru, mn)] = {"sizes": [ds, ns, ru, mn], "res": res, "two_k": two["all"],
                                          "halves": halves[mn], "count": count.get(mn, {})}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"v48_{args.shard:02d}.json").write_text(json.dumps(books, default=float), encoding="utf-8")
    for b, z in books.items():
        e = ensemble(z["res"]["base"], "all")
        print(b, f"ens median {e['med']:,.0f} ruin {e['ruin']:.1%} p90 {e['ruin90']:.1%} | seed0 {e['med0']:,.0f} "
              f"{e['ruin0']:.1%}", z["halves"], z["count"], flush=True)
    print(json.dumps({"sec": round(time.time() - t0)}), flush=True)
    return 0


def _read(runs: Path) -> dict:
    books = {}
    for p in sorted(runs.rglob("v48_[0-9]*.json")):
        books.update(json.loads(p.read_text(encoding="utf-8")))
    return books


def cmd_select(args) -> int:
    books = _read(args.runs)
    if not QUICK and len(books) != len(COMBOS) * len(NEWS):
        raise SystemExit(f"books {len(books)} of {len(COMBOS) * len(NEWS)}")
    c = choose(books)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "choice.json").write_text(json.dumps({"choice": c, "sizes": books[c]["sizes"] if c else None}),
                                          encoding="utf-8")
    print("choice:", c, flush=True)
    return 0


# ---------------------------------------------------------------- api

def _api_job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    items, recs = V.items_for(*V.pairs(level, task, TZA), TZA)
    return job, {s: account([it for it in items if not dropped(it, s)], recs, _G["mn"])[R43._G["pos"]]
                 for s in SEEDS}


def cmd_api(args) -> int:
    if args.which == "base":
        ds, ns, ru, mn = BASE
    else:
        ch = json.loads((args.choice_dir / "choice.json").read_text(encoding="utf-8"))
        if ch["sizes"] is None:
            print("no choice", flush=True)
            return 0
        ds, ns, ru, mn = ch["sizes"]
    _G["mn"] = int(mn)
    R40.SIZES = sizes_of(ds, ns, ru)
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[E2K, LEVELS]]
    R43.setup(args, tuple(lv2))
    V._G.update(rows=R35._rows(args), days=V.candidates())
    jobs = [(lv, t) for t in ENS_TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, _) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_api_job, jobs, chunksize=1))
    res = {t: {str(s): _boot([got[(lv, t)][s] for lv in lv2], ("all", "early", "late")) for s in SEEDS}
           for t in ENS_TASKS}
    out = {"which": args.which, "book": book_id(ds, ns, ru, int(mn)), "res": res, "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"api_{args.which}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    e = ensemble(res["base"], "all")
    print(out["book"], f"TZA ens median {e['med']:,.0f} ruin {e['ruin']:.1%} | seed0 {e['med0']:,.0f} {e['ruin0']:.1%}",
          flush=True)
    return 0


# ---------------------------------------------------------------- final

def _d(x: float) -> str:
    return f"${x:,.0f}"


def cmd_final(args) -> int:
    books = _read(args.runs)
    ch = json.loads((args.choice_dir / "choice.json").read_text(encoding="utf-8"))["choice"]
    api = {p.stem.split("_", 1)[1]: json.loads(p.read_text(encoding="utf-8")) for p in args.api.rglob("api_*.json")}
    base = book_id(*BASE)
    b = books[base]
    e = {(k, t, smp): ensemble(books[k]["res"][t], smp) for k in books for t in ENS_TASKS for smp in ("all", "early",
                                                                                                     "late")}
    check = abs(e[(base, "base", "all")]["med0"] - CHECK[0]) <= CHECK[2] and \
        abs(e[(base, "base", "all")]["ruin0"] - CHECK[1]) <= CHECK[3]
    q1 = None
    if ch:
        c = books[ch]
        q1 = bool(all(e[(ch, t, "all")]["ruin"] <= MAX_RUIN for t in ENS_TASKS)
                  and e[(ch, "base", "all")]["med"] >= e[(base, "base", "all")]["med"]
                  and e[(ch, "base", "late")]["med"] >= e[(base, "base", "late")]["med"] and min(c["halves"]) > 0)
    L = ["# v48: per-name sizes judged on an ensemble of trade sets", "",
         f"{R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under $1,250. Ensemble: seed 0 (history) and "
         f"{len(SEEDS) - 1} seeds that each drop {DROP:.0%} of candidate trades. ens = mean over seeds; p90 = the "
         "90th percentile of ruin over seeds.", "",
         f"Check (base book seed 0 vs v47's {_d(CHECK[0])}, {CHECK[1]:.1%}): **{'reproduced' if check else 'NOT reproduced'}**.",
         "", f"## Q1. The choice on 2018-2022 paths: **{ch}**", "",
         f"**{q1}** (ensemble ruin <= 2.5% on all paths at base and HOT 5%, ensemble median >= the base book's on all "
         "paths and on 2023+ paths, both symbol halves positive).", ""]
    hdr = ("| book | ens median | ens ruin | p90 ruin | seed 0 | 2018-22 ens | 2023+ ens | HOT 5% ens | spreads x2 / high "
           "seed 0 | halves | from $2k |")
    L += [hdr, "|---|---|---|---|---|---|---|---|---|---|---|"]

    def row(k: str) -> str:
        z, a = books[k], e[(k, "base", "all")]
        s2, hi = z["res"]["spread2"]["0"]["all"], z["res"]["high"]["0"]["all"]
        h = e[(k, "hot5", "all")]
        return (f"| {k} | {_d(a['med'])} | {a['ruin']:.1%} | {a['ruin90']:.1%} | {_d(a['med0'])} / {a['ruin0']:.1%} | "
                f"{_d(e[(k, 'base', 'early')]['med'])} / {e[(k, 'base', 'early')]['ruin']:.1%} | "
                f"{_d(e[(k, 'base', 'late')]['med'])} / {e[(k, 'base', 'late')]['ruin']:.1%} | "
                f"{_d(h['med'])} / {h['ruin']:.1%} | {_d(s2['med'])} / {s2['p_ruin']:.1%}, {_d(hi['med'])} / "
                f"{hi['p_ruin']:.1%} | {z['halves'][0]:.2f} / {z['halves'][1]:.2f} | {_d(z['two_k']['med'])} / "
                f"{z['two_k']['p_ruin']:.1%} |")

    L += [row(k) for k in dict.fromkeys([base] + ([ch] if ch else []))]
    L += ["", "## Q3. Under v47's API rules (TZA), same ensemble", ""]
    q3 = None
    for w in ("base", "chosen"):
        if w not in api:
            continue
        z = api[w]
        a, h = ensemble(z["res"]["base"], "all"), ensemble(z["res"]["hot5"], "all")
        L.append(f"- {w} ({z['book']}): ens median {_d(a['med'])}, ruin {a['ruin']:.1%} (p90 {a['ruin90']:.1%}); "
                 f"HOT 5% {_d(h['med'])} / {h['ruin']:.1%}; seed 0 {_d(a['med0'])} / {a['ruin0']:.1%}; 2023+ "
                 f"{_d(ensemble(z['res']['base'], 'late')['med'])}")
        if w == "chosen":
            q3 = bool(a["ruin"] <= MAX_RUIN and h["ruin"] <= MAX_RUIN)
        if w == "base":
            ok = abs(a["med0"] - CHECK_TZA[0]) <= CHECK_TZA[2] and abs(a["ruin0"] - CHECK_TZA[1]) <= CHECK_TZA[3]
            L.append(f"  TZA check (seed 0 vs v47's {_d(CHECK_TZA[0])}, {CHECK_TZA[1]:.1%}): "
                     f"{'reproduced' if ok else 'NOT reproduced'}")
    L += ["", f"Q3 (the choice operable: ensemble ruin <= 2.5% at base and HOT 5% under TZA): **{q3}**", "",
          "## Q2. Every book (base costs unless named)", "", hdr, "|---|---|---|---|---|---|---|---|---|---|---|"]
    L += [row(k) for k in sorted(books, key=lambda k: -e[(k, "base", "all")]["med"])]
    L += ["", "Counts at $10,000, base costs, seed 0:", "",
          *[f"- {k}: {books[k]['count']}" for k in sorted(books)]]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V48_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v48_summary.json").write_text(json.dumps({"choice": ch, "q1": q1, "q3": q3, "check": check,
                                                           "ensemble": {"|".join(k): v for k, v in e.items()},
                                                           "api": api}, default=float), encoding="utf-8")
    print("\n".join(L[:40]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    s = sub.add_parser("select")
    s.add_argument("--runs", type=Path, required=True)
    a = sub.add_parser("api")
    a.add_argument("--which", choices=("base", "chosen"), required=True)
    a.add_argument("--choice-dir", type=Path, default=Path("outputs/v48w/choice"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--api", type=Path, required=True)
    f.add_argument("--choice-dir", type=Path, default=Path("outputs/v48w/choice"))
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v48w"))
    args = ap.parse_args()
    return {"run": cmd_run, "select": cmd_select, "api": cmd_api, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v48"
    raise SystemExit(main())
