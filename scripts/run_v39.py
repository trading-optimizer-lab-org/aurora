"""v39: volatility-cut sizes beyond v38's edge (V39_PREREGISTRATION.md). v38's members, each at its own size, every
trade's weight cut by min(1, (v_ref / vol) ^ p); the choice on 2018-2022 paths.

  run    one (costs, chunk of books) job: the books' daily returns at the five levels
  final  V39_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R38 = _script("run_v38")
R36, R35, R33, R29, R32 = R38.R36, R38.R35, R38.R33, R38.R29, R38.R32
R14 = R29.R14
LEVELS = R35.LEVELS
R38.MEMBER_SIZES = {"B:v19:DS1": (0.20, 0.30, 0.40), "B:v20:RU": (0.50, 0.60, 0.70), "B:v20:NS": (0.30, 0.40),
                    "B:v19:ON1": (0.0, 0.20)}
MEMBER_SIZES = R38.MEMBER_SIZES
POWERS = (0.0, 0.5, 1.0)
VOL_DAYS = 20
EARLY_END = 2022
TASKS, CHUNKS, DROP = R38.TASKS, R38.CHUNKS, R38.DROP
BOOKS = [(a, b, c, d, p) for a in MEMBER_SIZES["B:v19:DS1"] for b in MEMBER_SIZES["B:v20:RU"]
         for c in MEMBER_SIZES["B:v20:NS"] for d in MEMBER_SIZES["B:v19:ON1"] for p in POWERS]
JOBS = [(t, k) for t in TASKS for k in range(CHUNKS)]


def book_name(b: tuple) -> str:
    return "DS1 {:.0%} RU {:.0%} NS {:.0%} ON1 {:.0%} p {}".format(*b)


def trade_vol(C: np.ndarray, t: int, j: int) -> float:
    """Std of the symbol's 20 daily log returns ending the session before the entry session; nan when unknown."""
    if j < 0 or t - 1 - VOL_DAYS < 0:
        return float("nan")
    c = C[t - 1 - VOL_DAYS:t, j]
    if not np.all(np.isfinite(c)) or np.any(c <= 0):
        return float("nan")
    return float(np.std(np.diff(np.log(c))))


def v_refs(cache: dict, C: np.ndarray, dates) -> dict[str, float]:
    """Each member's median volatility over its 2018-2022 trades (at its smallest cached size)."""
    out = {}
    for m in MEMBER_SIZES:
        sizes = sorted(s for mm, s in cache if mm == m)
        if not sizes:
            continue
        v = [trade_vol(C, it["t"], it["j"]) for it in cache[(m, sizes[0])] if dates[it["t"]].year <= EARLY_END]
        v = [x for x in v if np.isfinite(x)]
        out[m] = float(np.median(v)) if v else float("nan")
    return out


def cut(its: list[dict], p: float, refs: dict[str, float], C: np.ndarray) -> list[dict]:
    if p == 0:
        return its
    out = []
    for it in its:
        vol, ref = trade_vol(C, it["t"], it["j"]), refs.get(it["member"], float("nan"))
        f = min(1.0, (ref / vol) ** p) if np.isfinite(vol) and np.isfinite(ref) and vol > 0 else 1.0
        out.append({**it, "w": it["w"] * f})
    return out


def cmd_run(args) -> int:
    rows = [r for r in R35._rows(args) if r["fam"] not in DROP]
    task, k = JOBS[args.shard]
    books = BOOKS[k::CHUNKS]
    if R29.QUICK:
        books = books[:2]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    D = R14._G["D"]
    C = np.asarray(D["C"], float)
    R = np.zeros((len(books), len(LEVELS), len(pos)))
    refs_out = {}
    for li, level in enumerate(LEVELS):
        cache = R38.member_cache(rows, float(level), books, **R33.TASKS[task])
        refs = v_refs(cache, C, D["dates"])
        refs_out[str(level)] = refs
        for bi, b in enumerate(books):
            R[bi, li] = R36.stream(cut(R38.book_its(cache, b), b[4], refs, C), None)[pos]
        print(task, k, level, refs, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / f"run_{task}_{k}.npy", R)
    (args.out / f"run_{task}_{k}.json").write_text(json.dumps({"books": [list(b) for b in books], "refs": refs_out}),
                                                   encoding="utf-8")
    return 0


def cmd_final(args) -> int:
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    rows, stress = [], {}
    refs: dict = {}
    for task in TASKS:
        for k in range(CHUNKS):
            f = args.runs / f"run_{task}_{k}.npy"
            if not f.exists():
                continue
            R = np.load(f)
            meta = json.loads((args.runs / f"run_{task}_{k}.json").read_text(encoding="utf-8"))
            refs = refs or meta["refs"]
            for bi, b in enumerate(tuple(b) for b in meta["books"]):
                st = R35.book_stats(R[bi], idx if task == "base" else {"all": idx["all"]})
                if task == "base":
                    rows.append({"book": list(b), **st})
                else:
                    stress[(b, task)] = st["all"]
    c = R36.pick(rows)
    d = R35._d
    L = ["# v39: volatility-cut sizes beyond v38's edge", "", f"v38's members; {len(rows)} books (a size for each "
         f"member x volatility cut power p); {R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under "
         "$1,250 at any time; v31's liquidation. Choice: highest median on 2018-2022 paths with ruin <= 2.5% there.",
         "", "## 1. The question", ""]
    if c:
        L += [f"Choice: {book_name(c['book'])}. All paths: median {d(c['all']['med'])}, ruin {c['all']['p_ruin']:.1%}. "
              f"**Target (median >= $30,000, ruin <= 2.5%) met: {R35.met(c)}.**", ""]
    else:
        L += ["No book has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
    check = next((r for r in rows if tuple(r["book"]) == (0.3, 0.5, 0.3, 0.2, 0.0)), None)
    if check:
        L += [f"Check (v38's choice, p 0): median {d(check['all']['med'])}, ruin {check['all']['p_ruin']:.1%}.", ""]
    ok = [r for r in rows if r["early"]["p_ruin"] <= R35.MAX_RUIN]
    best_all = max((r for r in rows if r["all"]["p_ruin"] <= R35.MAX_RUIN), key=lambda r: r["all"]["med"], default=None)
    top = sorted(ok, key=lambda r: -r["early"]["med"])[:10]
    if best_all and best_all not in top:
        top.append(best_all)
    L += ["## 2. Top 10 by 2018-2022 median (ruin <= 2.5% there), and the best on all paths", "",
          "| book | all median | all ruin | -50% | p10 | 2018-22 median | 2018-22 ruin | 2023+ median | 2023+ ruin | "
          "HOT 5% | spreads x2 | high |", "|" + "---|" * 12]
    for r in top:
        sx = [stress.get((tuple(r["book"]), t)) for t in R35.STRESS]
        L.append(f"| {book_name(r['book'])} | {d(r['all']['med'])} | {r['all']['p_ruin']:.1%} | {r['all']['p_half']:.1%} | "
                 f"{d(r['all']['p10'])} | {d(r['early']['med'])} | {r['early']['p_ruin']:.1%} | {d(r['late']['med'])} | "
                 f"{r['late']['p_ruin']:.1%} | " +
                 " | ".join(f"{d(x['med'])} / {x['p_ruin']:.1%}" if x else "-" for x in sx) + " |")
    mx = max(rows, key=lambda r: r["all"]["med"], default=None)
    if mx:
        L += ["", f"Highest all-paths median at any ruin: {book_name(mx['book'])}, {d(mx['all']['med'])}, ruin "
              f"{mx['all']['p_ruin']:.1%} (2018-22 {mx['early']['p_ruin']:.1%}).", "", f"v_ref by member: {refs}"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V39_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v39_summary.json").write_text(json.dumps({"met": R35.met(c), "choice": c, "books": rows, "refs": refs,
                                                           "stress": {f"{book_name(b)}|{t}": v
                                                                      for (b, t), v in stress.items()}},
                                                          indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--choice", type=Path, required=True)
    r.add_argument("--shard", type=int, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v39"
    raise SystemExit(main())
