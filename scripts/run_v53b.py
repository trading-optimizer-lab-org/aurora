"""v53b (V53B_PREREGISTRATION.md): v53's chosen books re-simulated with every size multiplied by one scale.

  oos    a shard of (chosen book x scale): daily returns at v53's seeds and stress sets
  final  V53B_REPORT.md and v53b_summary.json
Market data and trade prices stay in the Actions cache; artifacts hold aggregate statistics and account returns only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v53 as W  # noqa: E402

V = W.V
SCALES = (1.00, 0.75, 0.50, 0.35, 0.25, 0.15, 0.10, 0.05)


def items(n_books: int) -> list[tuple[int, float]]:
    return [(b, s) for b in range(n_books) for s in SCALES]


def cmd_oos(args) -> int:
    ch = json.loads((args.choose / "choose.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    todo = items(len(ch["books"]))[args.shard::args.shards]
    if not todo:
        return 0
    S = W.load_sel(args.sel)
    jobs = [(t, s, {"loc_hot": lh}) for t, lh in V.TASKS.items() for s in W.SEEDS_OOS]
    jobs += [(t, s, kw) for t, kw in V.STRESS.items() for s in W.SEEDS_STRESS]
    for b, k in todo:
        members, mn = ch["books"][b]
        members = [(int(c), float(s) * k) for c, s in members]
        W._W.update(S=S, book=(members, int(mn)))
        out: dict[str, list] = {}
        for name, seed, R in sorted(V._map(W._oos_job, jobs, args.procs), key=lambda z: (z[0], z[1])):
            out.setdefault(name, []).append(R)
        cls = max(int(S["configs"][c]["cls"]) for c, _ in members)
        np.savez_compressed(args.out / f"oos-{b}-{k:.2f}.npz", years=S["years"][S["years"] >= W.TEST_YEARS[0]],
                            cls=cls, **{n: np.stack(v) for n, v in out.items()})
        print(json.dumps({"book": b, "scale": k, "cls": cls}), flush=True)
    return 0


def cmd_final(args) -> int:
    ch = json.loads((args.choose / "choose.json").read_text(encoding="utf-8"))
    oos: dict[float, dict] = {k: {} for k in SCALES}
    years = None
    for p in sorted(args.oos.rglob("oos-*.npz")):
        _, b, k = p.stem.split("-")
        z = np.load(p)
        oos[float(k)][int(b)] = {n: z[n] for n in z.files}
        years = z["years"]
    grades = {(proc, k): W.grade(ch["chosen"][proc], oos[k], years) for proc in W.procedures() for k in SCALES}
    ok = [p for p in grades if W._eligible_sel(grades[p])]
    pick = max(ok, key=lambda p: grades[p]["base"]["sel"]["med"]) if ok else None
    met = None
    if pick:
        g = grades[pick]
        met = all(g[t]["lock"]["med"] >= V.TARGET and g[t]["lock"]["ruin"] <= V.MAX_RUIN for t in V.TASKS)
    _d, _p = V._d, V._p
    L = ["# v53b report: v53's walk-forward books at smaller sizes", "",
         "Pre-registered in V53B_PREREGISTRATION.md. Every chosen book's sizes times one scale, 2018-2026.", ""]
    if pick is None:
        L += ["**No (procedure, scale) keeps selection ruin at or under 2.5% at base and HOT 5%: NOT MET.**", ""]
    else:
        g = grades[pick]
        L += [f"**{'MET' if met else 'NOT MET'}.** Chosen: {pick[0]} at scale {pick[1]:.2f}.", "",
              f"- lockbox 2025-2026: median {_d(g['base']['lock']['med'])}, ruin {_p(g['base']['lock']['ruin'])} "
              f"(HOT 5%: {_d(g['hot5']['lock']['med'])}, {_p(g['hot5']['lock']['ruin'])})",
              f"- selection 2018-2024: median {_d(g['base']['sel']['med'])}, ruin {_p(g['base']['sel']['ruin'])}; "
              f"all 2018-2026: median {_d(g['base']['all']['med'])}, ruin {_p(g['base']['all']['ruin'])}",
              f"- sequence from $5,000 through 2018-2026: {_d(g['history']['end'])}, low {_d(g['history']['low'])}", ""]
    L += ["## Every (procedure, scale), out of sample", "",
          "| procedure | scale | sel med | sel ruin | sel HOT5 ruin | lock med | lock ruin | lock HOT5 ruin | all med | "
          "all ruin | borrow x2 all | locates never fail all | half rates all | history end | history low |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (proc, k), g in grades.items():
        L.append(f"| {proc}{' **chosen**' if (proc, k) == pick else ''} | {k:.2f} | {_d(g['base']['sel']['med'])} | "
                 f"{_p(g['base']['sel']['ruin'])} | {_p(g['hot5']['sel']['ruin'])} | {_d(g['base']['lock']['med'])} | "
                 f"{_p(g['base']['lock']['ruin'])} | {_p(g['hot5']['lock']['ruin'])} | {_d(g['base']['all']['med'])} | "
                 f"{_p(g['base']['all']['ruin'])} | "
                 + " | ".join(f"{_d(g[s]['all']['med'])} / {_p(g[s]['all']['ruin'])}" for s in V.STRESS)
                 + f" | {_d(g['history']['end'])} | {_d(g['history']['low'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V53B_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"met": met, "pick": list(pick) if pick else None,
               "grades": {f"{p}@{k:.2f}": g for (p, k), g in grades.items()}}
    (args.out / "v53b_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:10]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("oos")
    c.add_argument("--sel", type=Path, required=True)
    c.add_argument("--choose", type=Path, required=True)
    c.add_argument("--shard", type=int, default=0)
    c.add_argument("--shards", type=int, default=1)
    c = sub.add_parser("final")
    c.add_argument("--choose", type=Path, required=True)
    c.add_argument("--oos", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--procs", type=int, default=4)
    args = ap.parse_args()
    return {"oos": cmd_oos, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v53b"
    raise SystemExit(main())
