"""v47d: the sessions behind v47's ruin jumps (diagnostic). At $10,000 and base costs, for each variant: the worst
sessions of the account, the trades open on them with their contribution, and whether the base book took them.

  run  writes V47D_REPORT.md
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v47 as V  # noqa: E402

R43 = V.R43
NAMES = ("base", "O1", "U10", "M05", "M10", "TZA")
WORST = 6


def _job(name: str) -> tuple:
    v = V.VARIANTS[name]
    R43._G["count"] = {}
    R43.LEVEL = V.LEVEL
    items, recs = V.items_for(*V.pairs(V.LEVEL, "base", v), v)
    r, taken = V.account(items, recs)
    D = R43._G["D"]
    rows = []
    for u in np.argsort(r)[:WORST]:
        tr = []
        for it in taken:
            rec = recs[it["_rec"]]
            if u in rec["u"]:
                i = rec["u"].index(u)
                tr.append((float(it["w"]) * float(rec["g"][i]), str(it["sym"]), it.get("member"), rec["kind"],
                           str(D["dates"][int(it["t"])].date()), float(it["w"]), int(it["tier"])))
        tr.sort()
        rows.append((str(D["dates"][int(u)].date()), float(r[u]), tr[:4]))
    keys = {(str(it["sym"]), int(it["t"]), it.get("member")) for it in taken}
    return name, rows, keys, R43._G["count"].get("liquidations", 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v43"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v47d"))
    args = ap.parse_args()
    R43.setup(args, (float(V.LEVEL),))
    V._G.update(rows=V.R35._rows(args), days=V.candidates())
    _, (oi, om, _) = V._o1_job((float(V.LEVEL), "base"))
    V._G["o1"][(float(V.LEVEL), "base")] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_job, NAMES, chunksize=1)
    base_keys = got[0][2]
    L = ["# v47d: the worst sessions at $10,000, base costs", ""]
    for name, rows, _, liq in got:
        L += [f"## {name} (liquidations {liq})", "", "| session | account return | trade: contribution, symbol, member, "
              "kind, entry, weight, tier, in base |", "|---|---|---|"]
        for d, ret, tr in rows:
            s = "; ".join(f"{c:+.1%} {sym} {m} {k} {e} w{w:.2f} t{t} {'yes' if (sym, _t(e), m) in base_keys else 'NO'}"
                          for c, sym, m, k, e, w, t in tr)
            L.append(f"| {d} | {ret:+.1%} | {s} |")
        L.append("")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V47D_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def _t(date: str) -> int:
    return int(np.flatnonzero(R43._G["D"]["dates"].strftime("%Y-%m-%d") == date)[0])


if __name__ == "__main__":
    sys.argv[0] = "run_v47d"
    raise SystemExit(main())
