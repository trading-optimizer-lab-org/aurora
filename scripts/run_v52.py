"""v52 (V52_PREREGISTRATION.md): v51's frozen selections and books on 2016-02-01 to 2017-12-29, years v51 never used.

  factory  one group: v51's engine on the holdout events, the trades of v51's frozen selections in that group
           (cache only) and their trade-level summary (artifact)
  book     a shard of the frozen items: the books (31 seeds, the stress sets, the symbol halves, the history) and the
           CRASH-long selections alone
  final    V52_REPORT.md and v52_summary.json
Market data and trade prices stay in the Actions cache; artifacts hold aggregate statistics only.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v51 as V  # noqa: E402

E = V.E
FIRST, LAST = pd.Timestamp("2016-02-01"), pd.Timestamp("2017-12-29")
SINGLE_GROUP, SINGLE_SIZES, SINGLE_NEWS = "CRASH-long", (0.10, 0.20, 0.30, 0.40), (3, 5)
FROZEN = Path("docs/research/data/v52_frozen.json")


def load_frozen(path: Path) -> dict:
    fr = json.loads(path.read_text(encoding="utf-8"))
    assert [c["id"] for c in fr["configs"]] == list(range(len(fr["configs"])))
    return fr


def _part(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "pf": None, "mean": None}
    r = np.array([x["r"] for x in rows])
    return {"n": len(r), "pf": V._num(V._pf(r[r > 0].sum(), -r[r < 0].sum())), "mean": V._num(r.mean())}


def hold_summary(rows: list[dict]) -> dict:
    """A frozen configuration's located trades on the holdout: count, PF, mean, worst, by year."""
    out = _part(rows)
    out["worst"] = V._num(min(x["r"] for x in rows)) if rows else None
    out["years"] = {int(y): _part([x for x in rows if x["year"] == y]) for y in sorted({x["year"] for x in rows})}
    return out


def cmd_factory(args) -> int:
    t0 = time.time()
    setup, side = args.group.split("-")
    frozen = [c for c in load_frozen(args.frozen)["configs"] if c["group"] == args.group]
    G = V.load_inputs(args.inputs, args.extras)
    census = json.loads((args.data / "census.json").read_text(encoding="utf-8"))
    EV = V.setup_events(G, args.data, setup)
    kind = E.SETUPS[setup][0]
    entries = list(E.ENTRIES[kind].items())
    V._G.update(G=G, EV=EV, setup=setup, sgn=-1 if side == "short" else 1, entries=entries, H=int(census["hold"]),
                folder=args.data / "minutes")
    print(json.dumps({"group": args.group, "events": len(EV["t"]), "hold": V._G["H"], "frozen": len(frozen)}),
          flush=True)
    trades: list[dict] = []
    if len(EV["t"]) and frozen:
        parts = V._map(V._pass1, V._chunks(EV["t"]), args.procs)
        order = np.concatenate(V._chunks(EV["t"]))
        P = {k: np.empty((len(order),) + parts[0][k].shape[1:], parts[0][k].dtype) for k in parts[0]}
        for k in P:
            P[k][order] = np.concatenate([p[k] for p in parts])
        Mf = E.filter_matrix()
        V._G.update(P1=P, M=Mf.astype(np.float64), Mb=Mf.astype(bool))
        want: dict[int, list] = {}
        evs = []
        for c in frozen:
            e = V._signature(c["q"], c["x"], c["f"])[1]
            want.setdefault(c["q"], []).append((c["id"], c["x"], set(e.tolist())))
            evs.append(e)
        need = np.unique(np.concatenate(evs))
        V._G["want"] = want
        jobs = [need[c] for c in V._chunks(EV["t"][need])] if len(need) else []
        trades = [r for part in V._map(V._pass2, jobs, args.procs) for r in part]
    print(f"{time.time() - t0:.0f}s, {len(trades)} trades", flush=True)
    rows = {c["id"]: hold_summary([r for r in trades if r["cfg"] == c["id"] and r["code"] == 0]) for c in frozen}
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / "dn.npy", G["dn"])
    V.save_trades(args.out / "trades.npz", trades, frozen)
    (args.out / "report.json").write_text(json.dumps(
        {"group": args.group, "events": len(EV["t"]), "hold": V._G["H"], "configs": rows,
         "sec": round(time.time() - t0)}), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- the account on the holdout

def load_holdout(fac: Path, configs: list[dict]) -> dict:
    """Every group's holdout trades in one table, and v51's bootstrap over the holdout sessions."""
    parts = [V.load_trades(p)[0] for p in sorted(fac.glob("*/trades.npz"))]
    parts = [A for A in parts if len(A["t_in"])]
    shift = np.cumsum([0] + [len(A["mark"]) for A in parts])[:-1]
    A = {k: np.concatenate([p[k] for p in parts]) for k in parts[0] if k != "off"}
    A["off"] = np.concatenate([p["off"] + s for p, s in zip(parts, shift)]).astype(np.int64)
    dn = np.load(next(fac.glob("*/dn.npy")))
    dates = pd.DatetimeIndex(dn.astype("datetime64[D]"))
    pos = np.flatnonzero((dates >= FIRST) & (dates <= LAST))
    TR = E.Trades(**{k: A[k] for k in V.TR_FIELDS if k != "member"}, member=A["cfg"])
    return {"A": A, "TR": TR, "configs": configs, "T": len(dn), "pos": pos,
            "idx": {"hold": E.draws(len(pos), paths=V.PATHS)}, "years": np.asarray(dates[pos].year),
            "n": len(A["t_in"]), "by_cfg": {c["id"]: np.flatnonzero(A["cfg"] == c["id"]) for c in configs}}


def all_hot(S: dict) -> dict:
    """Every short at the HOT tier: HOT locate a share and HOT locate failures (no short interest before 2018)."""
    A = dict(S["A"])
    short = A["side"] < 0
    A["tier"] = np.where(short, 2, A["tier"])
    A["loc"] = np.where(short, E.LOC[2] / np.maximum(A["price"], 0.01), A["loc"])
    return {**S, "A": A, "TR": dataclasses.replace(S["TR"], tier=A["tier"], loc=A["loc"])}


def items(fr: dict) -> list[dict]:
    out = [{"kind": "book", **b} for b in fr["books"]]
    out += [{"kind": "single", "name": f"{c['id']}|{s}|{mn}", "book": [[[c["id"], s]], mn]}
            for c in fr["configs"] if c["group"] == SINGLE_GROUP for s in SINGLE_SIZES for mn in SINGLE_NEWS]
    return out


_S: dict = {}


def _job(job: tuple) -> tuple:
    name, which, members, mn, kw, seeds = job
    return name, V.evaluate(_S[which], members, mn, seeds=seeds, **kw)


def run_item(S: dict, it: dict, procs: int = 1) -> dict:
    members, mn = [(int(c), float(s)) for c, s in it["book"][0]], int(it["book"][1])
    if it["kind"] == "single":
        return {"res": {t: V.evaluate(S, members, mn, loc_hot=lh) for t, lh in V.TASKS.items()}}
    _S.update(base=S, hot_all=all_hot(S))
    jobs = [(t, "base", members, mn, {"loc_hot": lh}, V.SEEDS_CONF) for t, lh in V.TASKS.items()]
    jobs += [(t, "base", members, mn, kw, V.SEEDS_CONF) for t, kw in V.STRESS.items()]
    jobs += [("hot_all", "hot_all", members, mn, {}, V.SEEDS_CONF)]
    jobs += [(f"half{h}", "base", members, mn, {"half": h}, (0,)) for h in (0, 1)]
    res = dict(V._map(_job, jobs, procs))
    Rb = V.book_returns(S, members, mn, 0)
    cls = max(int(S["configs"][c]["cls"]) for c, _ in members)
    eq, low = E.paths(Rb, np.arange(len(S["pos"]))[None, :], E.FIXED[cls])
    lv = list(E.LEVELS).index(5_000.0)
    yearly = {int(y): float(Rb[lv][S["years"] == y].sum()) for y in np.unique(S["years"])}
    return {"res": res, "history": {"end": float(eq[0]), "low": float(low[0]), "yearly_at_5k": yearly}}


def cmd_book(args) -> int:
    fr = load_frozen(args.frozen)
    S = load_holdout(args.factory, fr["configs"])
    todo = items(fr)[args.shard::args.shards]
    out = {}
    for it in todo:
        out[it["name"]] = {"kind": it["kind"], "book": it["book"], **run_item(S, it, args.procs)}
        print(json.dumps({"item": it["name"], "base": out[it["name"]]["res"]["base"]["hold"]}), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"book-{args.shard}.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- final

def verdict(z: dict) -> bool:
    return all(z["res"][t]["hold"]["med"] >= V.TARGET and z["res"][t]["hold"]["ruin"] <= V.MAX_RUIN for t in V.TASKS)


def cmd_final(args) -> int:
    fr = load_frozen(args.frozen)
    cfg = fr["configs"]
    name = {c["id"]: f"{c['group']} {c['entry']} {c['exit']} [{c['filter']}]" for c in cfg}
    reports = {r["group"]: r for r in (json.loads(p.read_text(encoding="utf-8"))
                                       for p in sorted(args.factory.rglob("report.json")))}
    hold = {int(k): v for r in reports.values() for k, v in r["configs"].items()}
    res = V._read_json(args.runs, "book-*.json")
    h1 = res.get("H1")
    met = verdict(h1) if h1 else None
    _d, _p, _f = V._d, V._p, V._f

    def books_line(z: dict) -> str:
        return " + ".join(f"{name[int(c)]} {100 * float(s):.0f}%" for c, s in z["book"][0])

    L = ["# v52 report: v51's CRASH-long book on 2016-2017", "",
         "Pre-registered in V52_PREREGISTRATION.md. One-year paths drawn from the sessions 2016-02-01 to 2017-12-29, "
         "from $5,000, v51's engine and TZC costs.", ""]
    if h1 is None:
        L += ["**No result for H1.**", ""]
    else:
        b, h = h1["res"]["base"]["hold"], h1["res"]["hot5"]["hold"]
        L += [f"**{'MET' if met else 'NOT MET'}.** H1: {books_line(h1)}, {h1['book'][1]} new a day.", "",
              f"- base: median {_d(b['med'])}, ruin {_p(b['ruin'])} (90th percentile of the seeds {_p(b['ruin90'])}), "
              f"10th percentile {_d(b['p10'])}, a loss in {_p(b['p_loss'])}",
              f"- HOT 5%: median {_d(h['med'])}, ruin {_p(h['ruin'])}",
              f"- history from $5,000: {_d(h1['history']['end'])} at 2017-12-29, low {_d(h1['history']['low'])}; "
              "by year at the $5,000 level: " + ", ".join(f"{y} {100 * v:+.0f}%"
                                                         for y, v in h1["history"]["yearly_at_5k"].items()), ""]
    L += ["## Frozen books", "", "| book | role | new | median | ruin | HOT5 median | HOT5 ruin | borrow x2 | "
          "locates never fail | half rates | every short HOT | half 0 | half 1 | history from $5k |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in fr["books"]:
        k, role = b["name"], b["role"]
        if k not in res:
            L.append(f"| {k} | {role} | no result |")
            continue
        z = res[k]
        r = z["res"]
        L.append(f"| {k}: {books_line(z)} | {role} | {z['book'][1]} | {_d(r['base']['hold']['med'])} | "
                 f"{_p(r['base']['hold']['ruin'])} | {_d(r['hot5']['hold']['med'])} | {_p(r['hot5']['hold']['ruin'])} | "
                 + " | ".join(f"{_d(r[s]['hold']['med'])} / {_p(r[s]['hold']['ruin'])}"
                              for s in ("borrow2", "loc_never", "loc_half", "hot_all"))
                 + f" | {_d(r['half0']['hold']['med'])} | {_d(r['half1']['hold']['med'])} | "
                 f"{_d(z['history']['end'])} |")
    L += ["", f"## {SINGLE_GROUP} selections alone", "", "| configuration | size | new | median | ruin | HOT5 median |"
          " HOT5 ruin |", "|---|---|---|---|---|---|---|"]
    for it in items(fr):
        z = res.get(it["name"])
        if it["kind"] == "single" and z:
            (c, s), mn = z["book"][0][0], z["book"][1]
            r = z["res"]
            L.append(f"| {name[int(c)]} | {100 * float(s):.0f}% | {mn} | {_d(r['base']['hold']['med'])} | "
                     f"{_p(r['base']['hold']['ruin'])} | {_d(r['hot5']['hold']['med'])} | {_p(r['hot5']['hold']['ruin'])} |")
    L += ["", "## v51's 193 selections at the trade level ($1,000 reference size, TZC costs)", "",
          "| group | selections | holdout events | median PF 2018-22 | median PF 2023+ | median PF 2016-17 | "
          "PF 2016-17 over 1 | trades 2016-17 |", "|---|---|---|---|---|---|---|---|"]
    by_g: dict[str, list] = {}
    for c in cfg:
        by_g.setdefault(c["group"], []).append(c)
    for g, cs in by_g.items():
        pf = [hold.get(c["id"], {}).get("pf") for c in cs]
        ok = [x for x in pf if x is not None]
        med = (lambda xs: _f(float(np.median(xs))) if xs else "n/a")
        L.append(f"| {g} | {len(cs)} | {reports.get(g, {}).get('events', 0):,} | "
                 f"{med([c['pf_d'] for c in cs if c['pf_d'] is not None])} | "
                 f"{med([c['pf_l'] for c in cs if c['pf_l'] is not None])} | {med(ok)} | "
                 f"{sum(x > 1 for x in ok)} of {len(ok)} | {sum(hold.get(c['id'], {}).get('n', 0) for c in cs):,} |")
    L += ["", "| id | configuration | PF 2018-22 | PF 2023+ | trades 2016-17 | PF 2016-17 | mean | worst |",
          "|---|---|---|---|---|---|---|---|"]
    for c in cfg:
        z = hold.get(c["id"], {})
        L.append(f"| {c['id']} | {name[c['id']]}{' ' + c['tag'] if c['tag'] else ''} | {_f(c['pf_d'])} | "
                 f"{_f(c['pf_l'])} | {z.get('n', 0)} | {_f(z.get('pf'))} | {_p(z.get('mean'))} | {_p(z.get('worst'))} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V52_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"met": met, "results": res, "holdout_trades": hold,
               "events": {g: r["events"] for g, r in reports.items()}, "hold": {g: r["hold"] for g, r in reports.items()}}
    (args.out / "v52_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:12]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("factory")
    c.add_argument("--group", required=True, choices=V.GROUPS)
    c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    c.add_argument("--extras", type=Path, default=Path("outputs/v28/inputs"))
    c.add_argument("--data", type=Path, default=Path("outputs/v52"))
    c = sub.add_parser("book")
    c.add_argument("--factory", type=Path, required=True)
    c.add_argument("--shard", type=int, default=0)
    c.add_argument("--shards", type=int, default=1)
    c = sub.add_parser("final")
    c.add_argument("--factory", type=Path, required=True)
    c.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--frozen", type=Path, default=FROZEN)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--procs", type=int, default=4)
    args = ap.parse_args()
    return {"factory": cmd_factory, "book": cmd_book, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v52"
    raise SystemExit(main())
