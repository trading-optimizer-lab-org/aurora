"""v54s (V54S_PREREGISTRATION.md): CRASH-long under strict fills of its limit orders.

  minute  v54d's CRASH-long cells on v51+v52's minute bars under one fill rule (asis, through1, vol3k1, vol3k5)
  final   V54S_REPORT.md and v54s_summary.json
Aggregates only: no prices or trades leave the runner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v54d as D  # noqa: E402

V, E = D.V, D.E
RULES = {"asis": None, "through1": 0.0, "vol3k1": 3 * 1_000.0, "vol3k5": 3 * 5_000.0}  # dollar volume needed
RULES.update({f"{k}o": v for k, v in list(RULES.items()) if v is not None})  # v54s2: the open's improvement kept
THROUGH = 0.01
TIMES = ("d1pm", "d1o")
POOL = tuple(range(2021, 2027))
MIN_POOL_PF, MIN_YEARS = 1.10, 5
CHECK = ("2024", 1935, 1.14, 1.16)  # v54d: c_1555 d1pm/t0.00/s0.00
_orig = {"limit": E._limit, "frames": V._frames}


def _frames(days, js) -> dict:
    """v51's frames with the volume row in split-adjusted shares, so volume x adjusted price is raw dollars."""
    out = _orig["frames"](days, js)
    F = V._G["G"]["F"]
    for (u, k), A in out.items():
        A[4] = A[4] / float(F[u, k])
    return out


def _strict(need: float, improve: bool):
    def limit(tl, day, m0, m1, lim, side):
        """A resting limit filled at ``lim`` once bars 1% through it hold ``need`` dollars of volume."""
        if day >= tl.K or not np.isfinite(lim):
            return None
        h, l_, v, vw, c = (getattr(tl, k)[day, m0:m1 + 1] for k in ("h", "l", "v", "vw", "c"))
        with np.errstate(invalid="ignore"):
            hit = np.nan_to_num((h > lim * (1 + THROUGH)) if side < 0 else (l_ < lim * (1 - THROUGH)), nan=0).astype(bool)
        px = np.where(np.isfinite(vw), vw, c)
        cum = np.cumsum(np.where(hit, np.nan_to_num(v) * np.nan_to_num(px), 0.0))
        k = E._first(hit & (cum >= need))
        if k < 0:
            return None
        o = float(tl.o[day, m0 + k])
        if improve and np.isfinite(o):
            return day, m0 + k, (max(lim, o) if side < 0 else min(lim, o)), E.L_PASS
        return day, m0 + k, float(lim), E.L_PASS
    return limit


def set_rule(rule: str) -> None:
    need = RULES[rule]
    E._limit = _orig["limit"] if need is None else _strict(need, rule.endswith("o"))
    V._frames = _frames


def cmd_minute(args) -> int:
    t0 = time.time()
    set_rule(args.rule)
    G, EV = D._setup(args)
    V._G["entries"] = [(n, s) for n, s in V._G["entries"] if n in D.ENTRIES]
    parts = V._map(V._pass1, V._chunks(EV["t"]), args.procs)
    order = np.concatenate(V._chunks(EV["t"]))
    P = {k: np.empty((len(order),) + parts[0][k].shape[1:], parts[0][k].dtype) for k in parts[0]}
    for k in P:
        P[k][order] = np.concatenate([p[k] for p in parts])
    Mb = E.filter_matrix().astype(bool)
    V._G.update(P1=P, Mb=Mb)
    names = [n for n, _ in V._G["entries"]]
    out = {"rule": args.rule, "events": int(len(EV["t"]))}
    for en in D.ENTRIES:
        q = names.index(en)
        ev, cells, _ = V._cells(q, (0,))
        yrs = G["year"][EV["t"][ev] + P["de"][ev, q]]
        keep0 = Mb[V.ALL][cells]
        for tg, st in D.EXITS:
            xs = {ti: E.EXITS.index((E.TIMES.index(ti), E.TGTS.index(tg), E.STOPS.index(st))) for ti in TIMES}
            for ti, x in xs.items():
                R = P["R"][ev, q, x].astype(float)
                keep = keep0 & np.isfinite(R)
                d = D.by_year(yrs[keep], R[keep])
                d["2021-2026"] = D.stats(R[keep & np.isin(yrs, POOL)])
                out[f"{en} {V.exit_name(x)}"] = d
            Rp, Ro = (P["R"][ev, q, xs[ti]].astype(float) for ti in TIMES)
            both = keep0 & np.isfinite(Rp) & np.isfinite(Ro)
            out[f"{en} {V.exit_name(xs['d1pm'])} limit share"] = {
                str(int(y)): round(float((Rp != Ro)[both & (yrs == y)].mean()), 4)
                for y in np.unique(yrs[both])}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"minute-{args.rule}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{args.rule} done {time.time() - t0:.0f}s, {len(EV['t'])} events", flush=True)
    return 0


def survives(M: dict) -> tuple[bool, dict]:
    why = {}
    for en in D.ENTRIES:
        d = M[f"{en} d1pm/t0.00/s0.00"]
        pool = d["2021-2026"]
        good = sum(1 for y in POOL if d.get(str(y), {"n": 0})["n"] and d[str(y)]["pf_trim"] >= 1.0)
        why[en] = {"pool_pf_trim": pool.get("pf_trim"), "years_ok": good,
                   "ok": bool(pool["n"] and pool["pf_trim"] >= MIN_POOL_PF and good >= MIN_YEARS)}
    return any(v["ok"] for v in why.values()), why


def cmd_final(args) -> int:
    R = {r: json.loads((args.res / f"minute-{r}.json").read_text(encoding="utf-8")) for r in RULES
         if (args.res / f"minute-{r}.json").exists()}
    yrs = [str(y) for y in range(2016, 2027)] + ["2021-2026"]
    c = R["asis"]["c_1555 d1pm/t0.00/s0.00"].get(CHECK[0], {"n": 0})
    check = bool(c["n"]) and c["n"] == CHECK[1] and round(c["pf"], 2) == CHECK[2] and round(c["pf_trim"], 2) == CHECK[3]
    V_ = {r: survives(M) for r, M in R.items()}
    L = ["# v54s report: CRASH-long under strict fills", "",
         f"Pre-registered in V54S_PREREGISTRATION.md. Check against v54d (c_1555 d1pm 2024: {CHECK[1]} / {CHECK[2]} / "
         f"{CHECK[3]}): {'passed' if check else 'FAILED'} ({c['n']} / {c.get('pf', 0):.2f} / {c.get('pf_trim', 0):.2f}).",
         ""]
    L += [f"- **{r}**: {'SURVIVES' if ok else 'does not survive'}; "
          + "; ".join(f"{en} pooled trimmed PF {w['pool_pf_trim']}, {w['years_ok']}/6 years at 1.0 or more"
                      for en, w in why.items()) for r, (ok, why) in V_.items()]
    L += ["", "Cells: trades / PF / PF without the top and bottom 1% / median trade."]
    for r, M in R.items():
        L += ["", f"## {r}", "", "| | " + " | ".join(yrs) + " |", "|---|" + "---|" * len(yrs)]
        for k, d in M.items():
            if k in ("rule", "events"):
                continue
            if k.endswith("limit share"):
                L.append(f"| {k} | " + " | ".join(f"{100 * d[y]:.0f}%" if y in d else "-" for y in yrs) + " |")
            else:
                L.append(D._row(k, d, yrs))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V54S_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"check": check, "verdict": {r: {"survives": ok, "why": why} for r, (ok, why) in V_.items()},
               "minute": R}
    (args.out / "v54s_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:9]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("minute")
    c.add_argument("--rule", choices=tuple(RULES), required=True)
    c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    c.add_argument("--extras", type=Path, default=Path("outputs/v28/inputs"))
    c.add_argument("--data", type=Path, default=Path("outputs/v53"))
    c.add_argument("--procs", type=int, default=4)
    c = sub.add_parser("final")
    c.add_argument("--res", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"minute": cmd_minute, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v54s"
    raise SystemExit(main())
