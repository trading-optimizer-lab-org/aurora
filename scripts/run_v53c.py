"""v53c (V53C_PREREGISTRATION.md): v53's walk-forward books with each year's size chosen from the years before only.

  final  V53C_REPORT.md and v53c_summary.json, from v53's choices and v53b's (book x scale) daily returns
Artifacts hold aggregate statistics and account returns only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v53b as B  # noqa: E402

W, V = B.W, B.V
E = W.E
START = 0.10
VARIANTS = ("safe", "best")
HIST_SEEDS = (0, 1, 2)


def load_oos(root: Path) -> tuple[dict, np.ndarray]:
    oos: dict = {}
    years = None
    for p in sorted(root.rglob("oos-*.npz")):
        _, b, k = p.stem.split("-")
        z = np.load(p)
        oos[(int(b), float(k))] = {n: z[n] for n in z.files}
        years = z["years"]
    return oos, years


def hist_stats(chosen: dict, oos: dict, years: np.ndarray, k: float, y: int) -> dict:
    """The procedure's own sessions 2018..y-1 at scale k: ensemble ruin and median at base and HOT 5%."""
    sub = np.flatnonzero(years < y)
    ix = sub[E.draws(len(sub), paths=V.PATHS)]
    books = {int(yy): b for yy, b in chosen.items() if b and int(yy) < y}
    cls = max([int(oos[(b["book"], k)]["cls"]) for b in books.values()] or [0])
    out = {}
    for t in V.TASKS:
        per_seed = {}
        for s in HIST_SEEDS:
            R = np.zeros((len(E.LEVELS), len(years)))
            for yy, b in books.items():
                m = years == yy
                R[:, m] = oos[(b["book"], k)][t][s][:, m]
            per_seed[s] = {"h": E.year_stats(*E.paths(R, ix, E.FIXED[cls]))}
        out[t] = V.ensemble(per_seed)["h"]
    return out


def size_rule(chosen: dict, oos: dict, years: np.ndarray, variant: str) -> dict:
    """{year: scale or None (cash)} for one procedure."""
    scales = {}
    for y in W.TEST_YEARS:
        if not chosen[str(y)]:
            scales[y] = None
            continue
        if y == W.TEST_YEARS[0]:
            scales[y] = START
            continue
        st = {k: hist_stats(chosen, oos, years, k, y) for k in B.SCALES}
        ok = [k for k in B.SCALES if all(st[k][t]["ruin"] <= V.MAX_RUIN for t in V.TASKS)]
        if not ok:
            scales[y] = None
        elif variant == "safe":
            scales[y] = max(ok)
        else:
            k = max(ok, key=lambda k: st[k]["base"]["med"])
            scales[y] = k if st[k]["base"]["med"] >= E.E0 else None
    return scales


def cmd_final(args) -> int:
    ch = json.loads((args.choose / "choose.json").read_text(encoding="utf-8"))
    oos, years = load_oos(args.oos)
    keyed = {f"{b}@{k:.2f}": v for (b, k), v in oos.items()}
    grades, scales = {}, {}
    for proc in W.procedures():
        for var in VARIANTS:
            sc = size_rule(ch["chosen"][proc], oos, years, var)
            chosen = {str(y): ({"book": f"{ch['chosen'][proc][str(y)]['book']}@{sc[y]:.2f}"} if sc[y] else None)
                      for y in W.TEST_YEARS}
            grades[(proc, var)] = W.grade(chosen, keyed, years)
            scales[(proc, var)] = sc
    ok = [p for p in grades if W._eligible_sel(grades[p])]
    pick = max(ok, key=lambda p: grades[p]["base"]["sel"]["med"]) if ok else None
    met = robust = None
    if pick:
        g = grades[pick]
        met = all(g[t]["lock"]["med"] >= V.TARGET and g[t]["lock"]["ruin"] <= V.MAX_RUIN for t in V.TASKS)
        robust = met and all(g[s]["all"]["ruin"] <= V.MAX_RUIN for s in V.STRESS)
    _d, _p = V._d, V._p
    L = ["# v53c report: the size chosen out of sample too", "",
         "Pre-registered in V53C_PREREGISTRATION.md. Each year's scale from the procedure's own earlier years only.", ""]
    if pick is None:
        L += ["**No (procedure, variant) keeps selection ruin at or under 2.5% at base and HOT 5%: NOT MET.**", ""]
    else:
        g = grades[pick]
        L += [f"**{'MET' if met else 'NOT MET'}{', ROBUST' if robust else ''}.** Chosen: {pick[0]} {pick[1]}.", "",
              f"- lockbox 2025-2026: median {_d(g['base']['lock']['med'])}, ruin {_p(g['base']['lock']['ruin'])} "
              f"(HOT 5%: {_d(g['hot5']['lock']['med'])}, {_p(g['hot5']['lock']['ruin'])})",
              f"- selection 2018-2024: median {_d(g['base']['sel']['med'])}, ruin {_p(g['base']['sel']['ruin'])}; "
              f"all 2018-2026: median {_d(g['base']['all']['med'])}, ruin {_p(g['base']['all']['ruin'])}",
              f"- sequence from $5,000 through 2018-2026: {_d(g['history']['end'])}, low {_d(g['history']['low'])}", ""]
    L += ["## Every (procedure, variant), out of sample", "",
          "| procedure | variant | scale by year 2018-2026 | sel med | sel ruin | sel HOT5 ruin | lock med | lock ruin | "
          "all med | all ruin | borrow x2 all | locates never fail all | half rates all | history end | history low |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (proc, var), g in grades.items():
        sc = " ".join("cash" if v is None else f"{v:.2f}" for v in scales[(proc, var)].values())
        L.append(f"| {proc}{' **chosen**' if (proc, var) == pick else ''} | {var} | {sc} | "
                 f"{_d(g['base']['sel']['med'])} | {_p(g['base']['sel']['ruin'])} | {_p(g['hot5']['sel']['ruin'])} | "
                 f"{_d(g['base']['lock']['med'])} | {_p(g['base']['lock']['ruin'])} | {_d(g['base']['all']['med'])} | "
                 f"{_p(g['base']['all']['ruin'])} | "
                 + " | ".join(f"{_d(g[s]['all']['med'])} / {_p(g[s]['all']['ruin'])}" for s in V.STRESS)
                 + f" | {_d(g['history']['end'])} | {_d(g['history']['low'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V53C_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"met": met, "robust": robust, "pick": list(pick) if pick else None,
               "scales": {f"{p}/{v}": {str(y): k for y, k in s.items()} for (p, v), s in scales.items()},
               "grades": {f"{p}/{v}": g for (p, v), g in grades.items()}}
    (args.out / "v53c_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:10]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("final")
    c.add_argument("--choose", type=Path, required=True)
    c.add_argument("--oos", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v53c"
    raise SystemExit(main())
