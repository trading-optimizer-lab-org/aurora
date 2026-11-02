"""v54m (V54M_PREREGISTRATION.md): what a step of safety margin on every member costs the fixed daily book.

  final  every v54 book held fixed 2019-2026, graded as v54's references; the margin rule, V54M_REPORT.md and
         v54m_summary.json
Reads v54's daily account returns (artifacts v54-run-*); aggregates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v54 as M  # noqa: E402

GRID = ((0.0, 0.20, 0.30, 0.40), (0.0, 0.40, 0.60, 0.80), (0.0, 0.15, 0.20, 0.25))
WORST_YEAR = -0.30
CHEAP = 0.90
MAIN, TASKS, MAX_RUIN = M.MAIN, M.TASKS, M.MAX_RUIN


def neighbours(b: int) -> list | None:
    """The books one grid step larger in one held member; None if a held member is at the top of its grid."""
    bk = M.BOOKS[b]
    out = []
    for i in range(3):
        if bk[i] == 0:
            continue
        g = GRID[i].index(bk[i])
        if g + 1 == len(GRID[i]):
            return None
        up = list(bk)
        up[i] = GRID[i][g + 1]
        out.append(M.BOOKS.index(tuple(up)))
    return out


def sound(g: dict) -> bool:
    return (all(g[f"{MAIN}|{t}"]["all"]["ruin"] <= MAX_RUIN for t in TASKS)
            and min(g["history"]["yearly"].values()) >= WORST_YEAR)


def cmd_final(args) -> int:
    Z, years = {}, None
    for p in sorted(args.runs.rglob("b*.npz")):
        z = np.load(p)
        Z[int(p.stem[1:])] = {k: z[k] for k in z.files if k != "years"}
        years = z["years"]
    M._F.update(Z=Z, years=years)
    books = sorted(Z)
    G = dict(M._map(M._grade, [(b, {y: b for y in M.TEST_YEARS}) for b in books], args.procs))
    v49 = M.BOOKS.index(M.REFS["v49"])
    margin = {}
    for b in books:
        nb = neighbours(b)
        margin[b] = (nb is not None and all(n in G for n in nb) and sound(G[b]) and all(sound(G[n]) for n in nb)
                     and all(G[b][f"{n}|base"]["all"]["ruin"] <= MAX_RUIN for n in M.STRESS.values()))
    ok = [b for b in books if margin[b]]
    pick = max(ok, key=lambda b: G[b][f"{MAIN}|base"]["all"]["med"]) if ok else None
    ref = G[v49][f"{MAIN}|base"]
    cheap = None if pick is None else G[pick][f"{MAIN}|base"]["all"]["med"] >= CHEAP * ref["all"]["med"]
    _d = M.F._d

    def bk(b):
        return M.W.book_id(*M.BOOKS[b][:3], int(M.BOOKS[b][3]))

    def row(b, tag=""):
        g = G[b]
        m, h = g[f"{MAIN}|base"], g[f"{MAIN}|hot5"]
        yr = " ".join(f"{100 * v:+.0f}" for v in g["history"]["yearly"].values())
        return (f"| {bk(b)}{tag} | {_d(m['sel']['med'])} | {_d(m['lock']['med'])} | {_d(m['all']['med'])} | "
                f"{m['all']['ruin']:.1%} | {h['all']['ruin']:.1%} | "
                + " | ".join(f"{g[f'{n}|base']['all']['ruin']:.1%}" for n in M.STRESS.values())
                + f" | {yr} | {'yes' if margin[b] else 'no'} |")
    head = ["| book | sel med | lock med | all med | all ruin | all HOT5 ruin | borrow x2 ruin | locates never fail ruin | "
            "locates fail half as often ruin | years 2019-2026 at $5k, % | margin |", "|---" * 11 + "|"]
    L = ["# v54m report: the cost of a safety margin on the fixed daily book", "",
         f"Pre-registered in V54M_PREREGISTRATION.md. {len(books)} v54 books held fixed 2019-2026. v49's book "
         f"{bk(v49)}: all {_d(ref['all']['med'])}, ruin {ref['all']['ruin']:.1%}; lockbox {_d(ref['lock']['med'])}.", ""]
    if pick is None:
        L += ["**No book has margin.**", ""]
    else:
        p = G[pick][f"{MAIN}|base"]
        L += [f"**Margin pick: {bk(pick)}. All {_d(p['all']['med'])} against v49's {_d(ref['all']['med'])} "
              f"({p['all']['med'] / ref['all']['med'] - 1:+.0%}); lockbox {_d(p['lock']['med'])} against "
              f"{_d(ref['lock']['med'])}. Margin is {'cheap' if cheap else 'dear'}.**", ""]
    L += ["## v49's book, its neighbours and the margin pick", ""] + head + [row(v49, " (v49)")]
    L += [row(n, " (v49 +1 step)") for n in (neighbours(v49) or [])]
    if pick is not None:
        L += [row(pick, " **margin pick**")] + [row(n, " (pick +1 step)") for n in neighbours(pick)]
    top = sorted(ok, key=lambda b: -G[b][f"{MAIN}|base"]["all"]["med"])[:15]
    L += ["", f"## The best books with margin ({len(ok)} of {len(books)})", ""] + head + [row(b) for b in top]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V54M_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"pick": None if pick is None else bk(pick), "cheap": cheap, "v49": bk(v49),
               "margin": {bk(b): margin[b] for b in books}, "grades": {bk(b): G[b] for b in books}}
    (args.out / "v54m_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("\n".join(L[:6]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--procs", type=int, default=4)
    f.add_argument("--out", type=Path, default=Path("outputs/v54mw"))
    args = ap.parse_args()
    return {"final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v54m"
    raise SystemExit(main())
