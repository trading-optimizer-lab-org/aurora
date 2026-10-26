"""v36: dropping weak members and capping HOT shorts (V36_PREREGISTRATION.md). v33's limit members with a member
set (all, without ON1, without SYMPATHY, without both) x a HOT rule (none, cap 0.25, cap 0.50, half weight) x a size
(25-40%), under v31's liquidation; the choice on 2018-2022 paths.

  run    one (size, costs) job: the 16 (set, HOT rule) books' daily returns at the five levels
  final  V36_REPORT.md
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


R35 = _script("run_v35")
R33, R29, R31, R32, A, R14 = R35.R33, R35.R29, R35.R31, R35.R32, R35.A, R35.R14
LEVELS = R35.LEVELS
SETS: dict[str, tuple[str, ...]] = {"all": (), "no_on1": ("B:v19:ON1",), "no_sym": ("C:SYMPATHY",),
                                    "no_both": ("B:v19:ON1", "C:SYMPATHY")}
HOT_RULES: tuple[str, ...] = ("none", "cap25", "cap50", "half")
SIZES: tuple[float, ...] = (0.25, 0.30, 0.35, 0.40)
TASKS = ("base",) + R35.STRESS
JOBS = [(s, t) for s in SIZES for t in TASKS]
BOOKS = [(m, h, s) for m in SETS for h in HOT_RULES for s in SIZES]


def apply_rules(its: list[dict], drop: tuple[str, ...], hot: str) -> tuple[list[dict], float | None]:
    """The items a set keeps, with the HOT rule: half weight on HOT shorts, or the open HOT weight cap to pass."""
    out = [it for it in its if it["member"] not in drop]
    if hot == "half":
        out = [{**it, "w": it["w"] * 0.5} if it["side"] < 0 and it.get("tier") == 2 else it for it in out]
    return out, {"cap25": 0.25, "cap50": 0.50}.get(hot)


def stream(its: list[dict], hot_cap: float | None) -> np.ndarray:
    D = R14._G["D"]
    s, taken = A.joint(its, D["dates"], R33.GROSS, R33.MAX_OPEN, R33.MAX_NEW, "move", "none", "tzi", 0.0, 0.0, None,
                       None, hot_cap)
    r = s.to_numpy(float)
    out, _ = R31.liquidate(R31.position_days(taken, D, len(r)), len(r), R31.THETA)
    return out


def cmd_run(args) -> int:
    rows = R35._rows(args)
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    args.out.mkdir(parents=True, exist_ok=True)
    for size, task in JOBS[args.shard::args.shards]:
        R = np.zeros((len(SETS), len(HOT_RULES), len(LEVELS), len(pos)))
        for li, level in enumerate(LEVELS):
            its = R35.book_items(rows, float(level), size, None, **R33.TASKS[task])
            for mi, drop in enumerate(SETS.values()):
                for hi, hot in enumerate(HOT_RULES):
                    R[mi, hi, li] = stream(*apply_rules(its, drop, hot))[pos]
        np.save(args.out / f"run_{size:.2f}_{task}.npy", R)
        print(size, task, np.round(R[:, :, 1].sum(axis=-1), 2).tolist(), flush=True)
    return 0


def pick(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r["early"]["p_ruin"] <= R35.MAX_RUIN]
    return max(ok, key=lambda r: r["early"]["med"]) if ok else None


def cmd_final(args) -> int:
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    rows, stress = [], {}
    for size in SIZES:
        for task in TASKS:
            f = args.runs / f"run_{size:.2f}_{task}.npy"
            if not f.exists():
                continue
            R = np.load(f)
            for mi, m in enumerate(SETS):
                for hi, h in enumerate(HOT_RULES):
                    samples = idx if task == "base" else {"all": idx["all"]}
                    st = R35.book_stats(R[mi, hi], samples)
                    if task == "base":
                        rows.append({"set": m, "hot": h, "size": size, **st})
                    else:
                        stress[(m, h, size, task)] = st["all"]
    c = pick(rows)
    d = R35._d
    L = ["# v36: dropping weak members and capping HOT shorts", "",
         f"v33's limit members; {len(rows)} books (member set x HOT rule x size); {R29.PATHS} one-year bootstrap paths "
         "from $5,000; ruin = at or under $1,250 at any time; v31's liquidation. Choice: highest median on 2018-2022 "
         "paths with ruin <= 2.5% there.", "", "## 1. The question", ""]
    if c:
        L += [f"Choice: set {c['set']}, HOT rule {c['hot']}, size {c['size']:.0%}. All paths: median "
              f"{d(c['all']['med'])}, ruin {c['all']['p_ruin']:.1%}. **Target (median >= $30,000, ruin <= 2.5%) met: "
              f"{R35.met(c)}.**", ""]
    else:
        L += ["No book has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
    L += ["## 2. Every book (sorted by 2018-2022 median)", "", "| set | HOT rule | size | all median | all ruin | -50% | "
          "p10 | 2018-22 median | 2018-22 ruin | 2023+ median | 2023+ ruin | HOT 5% | spreads x2 | high |",
          "|" + "---|" * 14]
    for r in sorted(rows, key=lambda r: -r["early"]["med"]):
        sx = [stress.get((r["set"], r["hot"], r["size"], t)) for t in R35.STRESS]
        L.append(f"| {r['set']} | {r['hot']} | {r['size']:.0%} | {d(r['all']['med'])} | {r['all']['p_ruin']:.1%} | "
                 f"{r['all']['p_half']:.1%} | {d(r['all']['p10'])} | {d(r['early']['med'])} | "
                 f"{r['early']['p_ruin']:.1%} | {d(r['late']['med'])} | {r['late']['p_ruin']:.1%} | " +
                 " | ".join(f"{d(x['med'])} / {x['p_ruin']:.1%}" if x else "-" for x in sx) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V36_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v36_summary.json").write_text(json.dumps({"met": R35.met(c), "choice": c, "books": rows,
                                                           "stress": {"|".join(map(str, k)): v
                                                                      for k, v in stress.items()}},
                                                          indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--choice", type=Path, required=True)
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=1)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v36"
    raise SystemExit(main())
