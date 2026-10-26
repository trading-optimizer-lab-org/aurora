"""v38: a size for each member (V38_PREREGISTRATION.md). v33's limit members without SYMPATHY, each member at its own
size, HOT shorts at full or half weight, under v31's liquidation; the choice on 2018-2022 paths.

  run    one (costs, chunk of books) job: the books' daily returns at the five levels
  final  V38_REPORT.md
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


R36 = _script("run_v36")
R35, R33, R29, R32 = R36.R35, R36.R33, R36.R29, R36.R32
LEVELS = R35.LEVELS
MEMBER_SIZES: dict[str, tuple[float, ...]] = {"B:v19:DS1": (0.20, 0.30, 0.40), "B:v20:RU": (0.20, 0.30, 0.40, 0.50),
                                              "B:v20:NS": (0.10, 0.20, 0.30), "B:v19:ON1": (0.0, 0.10, 0.20)}
HOT_RULES = ("none", "half")
DROP = ("C:SYMPATHY",)
TASKS = ("base",) + R35.STRESS
CHUNKS = 6
BOOKS = [(a, b, c, d, h) for a in MEMBER_SIZES["B:v19:DS1"] for b in MEMBER_SIZES["B:v20:RU"]
         for c in MEMBER_SIZES["B:v20:NS"] for d in MEMBER_SIZES["B:v19:ON1"] for h in HOT_RULES]
JOBS = [(t, k) for t in TASKS for k in range(CHUNKS)]


def book_name(b: tuple) -> str:
    return "DS1 {:.0%} RU {:.0%} NS {:.0%} ON1 {:.0%} HOT {}".format(*b)


def member_cache(rows: list[dict], level: float, books: list[tuple], **costs) -> dict[tuple[str, float], list[dict]]:
    """Each (member, size) the books need: that member's trades at that size."""
    need = {(m, b[i]) for b in books for i, m in enumerate(MEMBER_SIZES) if b[i] > 0}
    return {(m, s): R35.book_items([r for r in rows if r["fam"] == m], level, s, None, **costs) for m, s in need}


def book_its(cache: dict, b: tuple) -> list[dict]:
    return [it for i, m in enumerate(MEMBER_SIZES) if b[i] > 0 for it in cache[(m, b[i])]]


def cmd_run(args) -> int:
    rows = [r for r in R35._rows(args) if r["fam"] not in DROP]
    task, k = JOBS[args.shard]
    books = BOOKS[k::CHUNKS]
    if R29.QUICK:
        books = books[:2]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    R = np.zeros((len(books), len(LEVELS), len(pos)))
    for li, level in enumerate(LEVELS):
        cache = member_cache(rows, float(level), books, **R33.TASKS[task])
        for bi, b in enumerate(books):
            R[bi, li] = R36.stream(*R36.apply_rules(book_its(cache, b), (), b[4]))[pos]
        print(task, k, level, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / f"run_{task}_{k}.npy", R)
    (args.out / f"run_{task}_{k}.json").write_text(json.dumps([list(b) for b in books]), encoding="utf-8")
    return 0


def cmd_final(args) -> int:
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    rows, stress = [], {}
    for task in TASKS:
        for k in range(CHUNKS):
            f = args.runs / f"run_{task}_{k}.npy"
            if not f.exists():
                continue
            R = np.load(f)
            books = [tuple(b) for b in json.loads((args.runs / f"run_{task}_{k}.json").read_text(encoding="utf-8"))]
            for bi, b in enumerate(books):
                st = R35.book_stats(R[bi], idx if task == "base" else {"all": idx["all"]})
                if task == "base":
                    rows.append({"book": list(b), **st})
                else:
                    stress[(b, task)] = st["all"]
    c = R36.pick(rows)
    d = R35._d
    L = ["# v38: a size for each member", "", f"v33's limit members without SYMPATHY; {len(rows)} books (a size for each "
         f"member x HOT rule); {R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under $1,250 at any time; "
         "v31's liquidation. Choice: highest median on 2018-2022 paths with ruin <= 2.5% there.", "",
         "## 1. The question", ""]
    if c:
        L += [f"Choice: {book_name(c['book'])}. All paths: median {d(c['all']['med'])}, ruin {c['all']['p_ruin']:.1%}. "
              f"**Target (median >= $30,000, ruin <= 2.5%) met: {R35.met(c)}.**", ""]
    else:
        L += ["No book has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
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
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V38_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v38_summary.json").write_text(json.dumps({"met": R35.met(c), "choice": c, "books": rows,
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
    sys.argv[0] = "run_v38"
    raise SystemExit(main())
