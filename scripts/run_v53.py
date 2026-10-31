"""v53 (V53_PREREGISTRATION.md): walk-forward of the whole v51 grid on 2016-2026, every year chosen out of sample.

  merge    v51's and v52's events and one-minute bars in one folder (runner disk only)
  factory  one group: the grid scored on every training window (raw and capped returns), each window's top
           configurations, their trades (cache only)
  select   each window's 40 best configurations across groups
  account  a shard of (window x configuration x size x new a day) on the window's paths
  pick     each window's 8 best singles and their books
  books    a shard of the books on their window's paths
  choose   each procedure's book for each test year
  oos      one chosen book: daily returns at 31 seeds (base, HOT 5%) and the stress sets at 10 seeds
  final    V53_REPORT.md and v53_summary.json
Market data and trade prices stay in the Actions cache; artifacts hold aggregate statistics and account returns only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v51 as V  # noqa: E402

E = V.E
V.Y0, V.NPER = 2016, 11  # per-year cells 2016-2026 (read by V._cells)
FIRST = pd.Timestamp("2016-02-01")
TEST_YEARS = tuple(range(2018, 2027))
SEL_YEARS, LOCK_YEARS = tuple(range(2018, 2025)), (2025, 2026)
WINDOWS = {"exp": None, "roll3": 3}
VARIANTS = {"raw": None, "cap25": 0.25}
RULES = {"r25": 0.025, "r10": 0.010}
TOP_ENTRY, TOP_GROUP, TOP_CTX = 30, 5, 40
SIZES, NEWS = (0.10, 0.20, 0.30, 0.40), (3, 5)
SINGLES, BOOK_SIZES = 8, (0.10, 0.20, 0.30)
SEEDS_SEL, SEEDS_OOS, SEEDS_STRESS = (0, 1, 2), tuple(range(31)), tuple(range(10))
_W: dict = {}


def train_years(window: str, y: int) -> tuple[int, ...]:
    n = WINDOWS[window]
    return tuple(range(V.Y0 if n is None else max(V.Y0, y - n), y))


def tkey(years: tuple[int, ...]) -> str:
    return f"{years[0]}-{years[-1]}"


def contexts() -> list[str]:
    keys = sorted({tkey(train_years(w, y)) for w in WINDOWS for y in TEST_YEARS})
    return [f"{k}|{v}" for k in keys for v in VARIANTS]


def ctx_years(ctx: str) -> tuple[int, ...]:
    a, b = map(int, ctx.split("|")[0].split("-"))
    return tuple(range(a, b + 1))


def procedures() -> list[str]:
    return [f"{w}/{v}/{r}" for w in WINDOWS for v in VARIANTS for r in RULES]


def proc_ctx(proc: str, y: int) -> str:
    w, v, _ = proc.split("/")
    return f"{tkey(train_years(w, y))}|{v}"


# ---------------------------------------------------------------- data

def cmd_merge(args) -> int:
    """Two event folders in one: events joined, overlapping minute days joined by symbol and minute."""
    out = args.out
    (out / "minutes").mkdir(parents=True, exist_ok=True)
    holds = {json.loads((d / "census.json").read_text(encoding="utf-8"))["hold"] for d in args.src}
    assert len(holds) == 1, holds
    ev = pd.concat([pd.read_parquet(d / "events.parquet") for d in args.src]).drop_duplicates(["t", "j"])
    ev.sort_values(["t", "j"]).to_parquet(out / "events.parquet", index=False)
    (out / "census.json").write_text(json.dumps({"hold": holds.pop(), "events": len(ev)}), encoding="utf-8")
    days: dict[str, list[Path]] = {}
    for d in args.src:
        for p in sorted((d / "minutes").glob("*.parquet")):
            days.setdefault(p.name, []).append(p)
    both = 0
    for name, ps in days.items():
        if len(ps) == 1:
            shutil.move(str(ps[0]), out / "minutes" / name) if args.move else shutil.copy(ps[0], out / "minutes" / name)
            continue
        both += 1
        df = pd.concat([pd.read_parquet(p) for p in ps])
        df["symbol"] = df["symbol"].astype(str)
        df = df.drop_duplicates(["symbol", "minute"]).sort_values(["symbol", "minute"])
        df["symbol"] = df["symbol"].astype("category")
        df.to_parquet(out / "minutes" / name, index=False, compression="zstd")
    print(json.dumps({"events": len(ev), "days": len(days), "joined_days": both}), flush=True)
    return 0


# ---------------------------------------------------------------- factory

def _train_masks(G: dict) -> dict:
    dates = G["dates"]
    ok = np.asarray(dates >= FIRST)
    out = {}
    for ctx in contexts():
        k = ctx.split("|")[0]
        if k in out:
            continue
        yrs = ctx_years(ctx)
        mask = np.zeros(V.NPER, bool)
        mask[[y - V.Y0 for y in yrs]] = True
        out[k] = (mask, float((ok & np.isin(dates.year, yrs)).sum()) / 252)
    return out


def _grid53(q: int) -> tuple[int, dict, int]:
    ev, cells, per = V._cells(q)
    out: dict = {}
    if not len(ev):
        return q, out, 0
    R = V._G["P1"]["R"][ev, q].astype(float)
    M = V._G["M"]
    n_scored = 0
    for var, cap in VARIANTS.items():
        Rv = R if cap is None else np.clip(R, -cap, cap)
        cs = E.cell_sums(cells, Rv, per, V.NPER)
        for k, (mask, years) in _W["TRAIN"].items():
            Gt = (M @ cs[:, mask].sum(1).reshape(E.NCELL, -1)).reshape(len(E.FILTERS), E.NX, 4)
            sc = E.score(Gt[..., 0], Gt[..., 2], Gt[..., 3], years).ravel()
            n_scored += sc.size
            kk = min(TOP_ENTRY, int(np.isfinite(sc).sum()))
            if not kk:
                continue
            top = np.argpartition(-np.where(np.isfinite(sc), sc, -1e300), kk - 1)[:kk]
            out[f"{k}|{var}"] = [(q, int(z % E.NX), int(z // E.NX), float(sc[z])) for z in top]
    return q, out, n_scored


def cmd_factory(args) -> int:
    t0 = time.time()
    setup, side = args.group.split("-")
    G = V.load_inputs(args.inputs, args.extras)
    census = json.loads((args.data / "census.json").read_text(encoding="utf-8"))
    EV = V.setup_events(G, args.data, setup)
    kind = E.SETUPS[setup][0]
    entries = list(E.ENTRIES[kind].items())
    names = [n for n, _ in entries]
    V._G.update(G=G, EV=EV, setup=setup, sgn=-1 if side == "short" else 1, entries=entries, H=int(census["hold"]),
                folder=args.data / "minutes")
    _W["TRAIN"] = _train_masks(G)
    print(json.dumps({"group": args.group, "events": len(EV["t"]), "hold": V._G["H"]}), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / "dn.npy", G["dn"])
    trades: list[dict] = []
    configs: list[dict] = []
    ctx_rows: dict[str, list] = {}
    n_scored = n_kept = 0
    if len(EV["t"]):
        parts = V._map(V._pass1, V._chunks(EV["t"]), args.procs)
        order = np.concatenate(V._chunks(EV["t"]))
        P = {k: np.empty((len(order),) + parts[0][k].shape[1:], parts[0][k].dtype) for k in parts[0]}
        for k in P:
            P[k][order] = np.concatenate([p[k] for p in parts])
        Mf = E.filter_matrix()
        V._G.update(P1=P, M=Mf.astype(np.float64), Mb=Mf.astype(bool))
        print(f"pass 1 {time.time() - t0:.0f}s", flush=True)
        by_ctx: dict[str, list] = {}
        for _, out, ns in V._map(_grid53, list(range(len(entries))), args.procs):
            n_scored += ns
            for k, rows in out.items():
                by_ctx.setdefault(k, []).extend(rows)
        print(f"grid {time.time() - t0:.0f}s", flush=True)
        sig: dict[tuple, tuple] = {}
        kept: dict[str, list] = {}
        for k, rows in by_ctx.items():
            seen, keep = set(), []
            for q, x, f, s in sorted(rows, key=lambda r: -r[3]):
                if (q, x, f) not in sig:
                    sig[(q, x, f)] = V._signature(q, x, f)
                if sig[(q, x, f)][0] in seen:
                    continue
                seen.add(sig[(q, x, f)][0])
                keep.append(((q, x, f), s))
                if len(keep) == TOP_GROUP:
                    break
            kept[k] = keep
        union = sorted({c for keep in kept.values() for c, _ in keep})
        cid = {c: i for i, c in enumerate(union)}
        configs = [{"id": i, "group": args.group, "entry": names[q], "exit": V.exit_name(x),
                    "filter": V.filter_name(f), "q": q, "x": x, "f": f, "tag": "",
                    "cls": E.ENTRIES[kind][names[q]][0]} for i, (q, x, f) in enumerate(union)]
        ctx_rows = {k: [[cid[c], s] for c, s in keep] for k, keep in kept.items()}
        want: dict[int, list] = {}
        for i, (q, x, f) in enumerate(union):
            want.setdefault(q, []).append((i, x, set(sig[(q, x, f)][1].tolist())))
        need = np.unique(np.concatenate([sig[c][1] for c in union])) if union else np.array([], int)
        V._G["want"] = want
        jobs = [need[c] for c in V._chunks(EV["t"][need])] if len(need) else []
        trades = [r for part in V._map(V._pass2, jobs, args.procs) for r in part]
        n_kept = len(union)
        for c in configs:
            c.update(V._summary([r for r in trades if r["cfg"] == c["id"] and r["code"] == 0]))
    print(f"done {time.time() - t0:.0f}s, {n_kept} configurations, {len(trades)} trades", flush=True)
    V.save_trades(args.out / "trades.npz", trades, configs)
    (args.out / "report.json").write_text(json.dumps(
        {"group": args.group, "events": len(EV["t"]), "hold": V._G["H"], "n_scored": n_scored, "contexts": ctx_rows,
         "configs": configs, "sec": round(time.time() - t0)}), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- selection and the account

def cmd_select(args) -> int:
    parts, configs, ctx = [], [], {}
    for p in sorted(args.factory.glob("*/report.json")):
        rep = json.loads(p.read_text(encoding="utf-8"))
        A, cfgs = V.load_trades(p.parent / "trades.npz")
        base = len(configs)
        for c in cfgs:
            configs.append({**c, "id": base + c["id"], "src_id": c["id"]})
        if len(A["t_in"]):
            A["cfg"] = A["cfg"].astype(np.int64) + base
            parts.append(A)
        for k, rows in rep["contexts"].items():
            ctx.setdefault(k, []).extend((base + int(c), s) for c, s in rows)
    shift = np.cumsum([0] + [len(A["mark"]) for A in parts])[:-1]
    A = {k: np.concatenate([p[k] for p in parts]) for k in parts[0] if k != "off"}
    A["off"] = np.concatenate([p["off"] + s for p, s in zip(parts, shift)]).astype(np.int64)
    order = np.argsort(A["cfg"], kind="stable")
    starts = np.searchsorted(A["cfg"][order], np.arange(len(configs) + 1))
    rows_of = {c: order[starts[c]:starts[c + 1]] for c in range(len(configs))}
    hsig = {}
    out = {}
    for k, rows in ctx.items():
        seen, keep = set(), []
        for c, s in sorted(rows, key=lambda r: -r[1]):
            if c not in hsig:
                m = np.zeros(len(A["cfg"]), bool)
                m[rows_of[c]] = True
                hsig[c] = V._set_sig(A, m & (A["code"] == 0))
            if hsig[c] in seen:
                continue
            seen.add(hsig[c])
            keep.append([c, s])
            if len(keep) == TOP_CTX:
                break
        out[k] = keep
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / "trades.npz", **A, configs=np.array(json.dumps(configs)))
    np.save(args.out / "dn.npy", np.load(next(args.factory.glob("*/dn.npy"))))
    (args.out / "configs.json").write_text(json.dumps(configs), encoding="utf-8")
    (args.out / "contexts.json").write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps({"configs": len(configs), "trades": len(A["t_in"]), "contexts": len(out),
                      "per_context": sorted({len(v) for v in out.values()})}), flush=True)
    return 0


def load_sel(sel: Path) -> dict:
    A, configs = V.load_trades(sel / "trades.npz")
    dn = np.load(sel / "dn.npy")
    dates = pd.DatetimeIndex(dn.astype("datetime64[D]"))
    pos = np.flatnonzero(dates >= FIRST)
    TR = E.Trades(**{k: A[k] for k in V.TR_FIELDS if k != "member"}, member=A["cfg"])
    order = np.argsort(A["cfg"], kind="stable")
    starts = np.searchsorted(A["cfg"][order], np.arange(len(configs) + 1))
    return {"A": A, "TR": TR, "configs": configs, "T": len(dn), "pos": pos, "years": np.asarray(dates[pos].year),
            "n": len(A["t_in"]), "by_cfg": {c: np.sort(order[starts[c]:starts[c + 1]]) for c in range(len(configs))},
            "idx": {}}


def ctx_S(S: dict, ctx: str) -> dict:
    if ctx not in _W.setdefault("IDX", {}):
        sub = np.flatnonzero(np.isin(S["years"], ctx_years(ctx)))
        _W["IDX"][ctx] = sub[E.draws(len(sub), paths=V.PATHS)]
    return {**S, "idx": {"train": _W["IDX"][ctx]}}


def _eval_job(job: tuple) -> tuple:
    key, ctx, members, mn = job
    S = ctx_S(_W["S"], ctx)
    return key, {t: V.evaluate(S, members, mn, seeds=SEEDS_SEL, loc_hot=lh) for t, lh in V.TASKS.items()}


def _run_jobs(S: dict, jobs: list, procs: int) -> dict:
    _W["S"] = S
    for ctx in sorted({j[1] for j in jobs}):
        ctx_S(S, ctx)
    return dict(V._map(_eval_job, jobs, procs))


def _block(n: int, shard: int, shards: int) -> slice:
    a = shard * n // shards
    return slice(a, (shard + 1) * n // shards)


def account_tasks(ctxs: dict) -> list:
    return [(f"{k}#{c}|{s}|{mn}", k, [(int(c), s)], mn) for k in sorted(ctxs) for c, _ in ctxs[k]
            for s in SIZES for mn in NEWS]


def cmd_account(args) -> int:
    S = load_sel(args.sel)
    tasks = account_tasks(json.loads((args.sel / "contexts.json").read_text(encoding="utf-8")))
    mine = tasks[_block(len(tasks), args.shard, args.shards)]
    res = _run_jobs(S, mine, args.procs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"acc-{args.shard}.json").write_text(json.dumps(res), encoding="utf-8")
    print(f"{len(mine)} tasks", flush=True)
    return 0


def _ok(r: dict, cap: float) -> bool:
    return all(r[t]["train"]["ruin"] <= cap for t in V.TASKS)


def cmd_pick(args) -> int:
    res = V._read_json(args.runs, "acc-*.json")
    best: dict[str, dict] = {}
    for key, r in res.items():
        ctx, rest = key.split("#")
        c, s, mn = rest.split("|")
        if _ok(r, V.MAX_RUIN):
            med = r["base"]["train"]["med"]
            b = best.setdefault(ctx, {})
            if int(c) not in b or med > b[int(c)][0]:
                b[int(c)] = (med, float(s), int(mn))
    books = []
    for ctx in sorted(best):
        singles = sorted(best[ctx], key=lambda c: -best[ctx][c][0])[:SINGLES]
        books += [[ctx, [[c, s] for c, s in zip(combo, sz)], mn] for k in (1, 2, 3)
                  for combo in itertools.combinations(singles, k)
                  for sz in itertools.product(BOOK_SIZES, repeat=k) for mn in NEWS]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "picks.json").write_text(json.dumps({"books": books}), encoding="utf-8")
    print(json.dumps({"contexts_with_singles": len(best), "books": len(books)}), flush=True)
    return 0


def cmd_books(args) -> int:
    S = load_sel(args.sel)
    books = json.loads((args.picks / "picks.json").read_text(encoding="utf-8"))["books"]
    sl = _block(len(books), args.shard, args.shards)
    jobs = [(str(b), books[b][0], [(int(c), float(s)) for c, s in books[b][1]], int(books[b][2]))
            for b in range(len(books))[sl]]
    res = _run_jobs(S, jobs, args.procs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"books-{args.shard}.json").write_text(
        json.dumps({k: {"book": books[int(k)], "res": v} for k, v in res.items()}), encoding="utf-8")
    print(f"{len(jobs)} books", flush=True)
    return 0


def cmd_choose(args) -> int:
    cand: dict[str, list] = {}
    for key, r in V._read_json(args.acc, "acc-*.json").items():
        ctx, rest = key.split("#")
        c, s, mn = rest.split("|")
        cand.setdefault(ctx, []).append(([[int(c), float(s)]], int(mn), r))
    for z in V._read_json(args.books, "books-*.json").values():
        ctx, members, mn = z["book"]
        cand.setdefault(ctx, []).append((members, int(mn), z["res"]))
    chosen: dict[str, dict] = {}
    uniq: list = []
    for proc in procedures():
        cap = RULES[proc.split("/")[2]]
        chosen[proc] = {}
        for y in TEST_YEARS:
            ok = [x for x in cand.get(proc_ctx(proc, y), []) if _ok(x[2], cap)]
            if not ok:
                chosen[proc][str(y)] = None
                continue
            members, mn, r = max(ok, key=lambda x: x[2]["base"]["train"]["med"])
            book = [[[int(c), float(s)] for c, s in members], mn]
            if book not in uniq:
                uniq.append(book)
            chosen[proc][str(y)] = {"book": uniq.index(book), "train": r["base"]["train"],
                                    "train_hot5": r["hot5"]["train"]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "choose.json").write_text(json.dumps({"chosen": chosen, "books": uniq,
                                                      "candidates": {k: len(v) for k, v in cand.items()}}),
                                          encoding="utf-8")
    print(json.dumps({"books": len(uniq), "cash_years": sum(v is None for p in chosen.values() for v in p.values())}),
          flush=True)
    return 0


def _oos_job(job: tuple) -> tuple:
    name, seed, kw = job
    S = _W["S"]
    members, mn = _W["book"]
    lv = S["years"] >= TEST_YEARS[0]
    return name, seed, V.book_returns(S, members, mn, seed, **kw)[:, lv].astype(np.float32)


def cmd_oos(args) -> int:
    ch = json.loads((args.choose / "choose.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    if args.shard >= len(ch["books"]):
        return 0
    S = load_sel(args.sel)
    members, mn = ch["books"][args.shard]
    _W.update(S=S, book=([(int(c), float(s)) for c, s in members], int(mn)))
    jobs = [(t, s, {"loc_hot": lh}) for t, lh in V.TASKS.items() for s in SEEDS_OOS]
    jobs += [(t, s, kw) for t, kw in V.STRESS.items() for s in SEEDS_STRESS]
    out: dict[str, list] = {}
    for name, seed, R in sorted(V._map(_oos_job, jobs, args.procs), key=lambda z: (z[0], z[1])):
        out.setdefault(name, []).append(R)
    cls = max(int(S["configs"][c]["cls"]) for c, _ in members)
    np.savez_compressed(args.out / f"oos-{args.shard}.npz", years=S["years"][S["years"] >= TEST_YEARS[0]],
                        cls=cls, **{k: np.stack(v) for k, v in out.items()})
    print(json.dumps({"book": args.shard, "cls": cls}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _samples(years: np.ndarray) -> dict:
    out = {}
    for name, yrs in (("sel", SEL_YEARS), ("lock", LOCK_YEARS), ("all", TEST_YEARS)):
        sub = np.flatnonzero(np.isin(years, yrs))
        if len(sub):
            out[name] = sub[E.draws(len(sub), paths=V.PATHS)]
    return out


def grade(chosen: dict, oos: dict, years: np.ndarray) -> dict:
    """A procedure's joined test years: each year the chosen book's returns (cash when none), every sample."""
    idx = _samples(years)
    cls = max([int(oos[b["book"]]["cls"]) for b in chosen.values() if b] or [0])
    out = {}
    for name in list(V.TASKS) + list(V.STRESS):
        n_seeds = len(SEEDS_OOS) if name in V.TASKS else len(SEEDS_STRESS)
        per_seed = {}
        for s in range(n_seeds):
            R = np.zeros((len(E.LEVELS), len(years)))
            for y, b in chosen.items():
                if b:
                    m = years == int(y)
                    R[:, m] = oos[b["book"]][name][s][:, m]
            per_seed[s] = {k: E.year_stats(*E.paths(R, ix, E.FIXED[cls])) for k, ix in idx.items()}
            if name == "base" and s == 0:
                eq, low = E.paths(R, np.arange(len(years))[None, :], E.FIXED[cls])
                lv = list(E.LEVELS).index(5_000.0)
                out["history"] = {"end": float(eq[0]), "low": float(low[0]),
                                  "yearly_at_5k": {int(y): float(R[lv][years == y].sum()) for y in np.unique(years)}}
        out[name] = V.ensemble(per_seed)
    out["cls"] = cls
    return out


def _eligible_sel(g: dict) -> bool:
    return all(g[t]["sel"]["ruin"] <= V.MAX_RUIN for t in V.TASKS)


def cmd_final(args) -> int:
    ch = json.loads((args.choose / "choose.json").read_text(encoding="utf-8"))
    configs = json.loads((args.sel / "configs.json").read_text(encoding="utf-8"))
    name = {c["id"]: f"{c['group']} {c['entry']} {c['exit']} [{c['filter']}]" for c in configs}
    oos, years = {}, None
    for p in sorted(args.oos.rglob("oos-*.npz")):
        z = np.load(p)
        oos[int(p.stem.split("-")[1])] = {k: z[k] for k in z.files}
        years = z["years"]
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.factory.rglob("report.json"))]
    n_scored = sum(r["n_scored"] for r in reports)
    grades = {proc: grade(ch["chosen"][proc], oos, years) for proc in procedures()}
    ok = [p for p in grades if _eligible_sel(grades[p])]
    pick = max(ok, key=lambda p: grades[p]["base"]["sel"]["med"]) if ok else None
    met = None
    if pick:
        g = grades[pick]
        met = all(g[t]["lock"]["med"] >= V.TARGET and g[t]["lock"]["ruin"] <= V.MAX_RUIN for t in V.TASKS)
    _d, _p = V._d, V._p

    def bk(b) -> str:
        if not b:
            return "cash"
        members, mn = ch["books"][b["book"]]
        return " + ".join(f"{name[int(c)]} {100 * float(s):.0f}%" for c, s in members) + f", {mn} new"

    L = ["# v53 report: the whole grid by walk-forward, every year chosen out of sample", "",
         f"Pre-registered in V53_PREREGISTRATION.md. Configuration scorings: {n_scored:,} "
         f"(every configuration on every training window and score). Books chosen: {len(ch['books'])}.", ""]
    if pick is None:
        L += ["**No procedure keeps selection ruin at or under 2.5% at base and HOT 5%: NOT MET.**", ""]
    else:
        g = grades[pick]
        L += [f"**{'MET' if met else 'NOT MET'}.** Chosen procedure: {pick}.", "",
              f"- lockbox 2025-2026: median {_d(g['base']['lock']['med'])}, ruin {_p(g['base']['lock']['ruin'])} "
              f"(HOT 5%: {_d(g['hot5']['lock']['med'])}, {_p(g['hot5']['lock']['ruin'])})",
              f"- selection 2018-2024: median {_d(g['base']['sel']['med'])}, ruin {_p(g['base']['sel']['ruin'])}; "
              f"all 2018-2026: median {_d(g['base']['all']['med'])}, ruin {_p(g['base']['all']['ruin'])}",
              f"- sequence from $5,000 through 2018-2026: {_d(g['history']['end'])}, low {_d(g['history']['low'])}", ""]
    L += ["## Procedures (out of sample)", "", "| procedure | sel med | sel ruin | lock med | lock ruin | lock HOT5 med | "
          "lock HOT5 ruin | all med | all ruin | borrow x2 all | locates never fail all | half rates all | "
          "history from $5k |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for proc, g in grades.items():
        L.append(f"| {proc}{' **chosen**' if proc == pick else ''} | {_d(g['base']['sel']['med'])} | "
                 f"{_p(g['base']['sel']['ruin'])} | {_d(g['base']['lock']['med'])} | {_p(g['base']['lock']['ruin'])} | "
                 f"{_d(g['hot5']['lock']['med'])} | {_p(g['hot5']['lock']['ruin'])} | {_d(g['base']['all']['med'])} | "
                 f"{_p(g['base']['all']['ruin'])} | "
                 + " | ".join(f"{_d(g[s]['all']['med'])} / {_p(g[s]['all']['ruin'])}" for s in V.STRESS)
                 + f" | {_d(g['history']['end'])} |")
    for proc in procedures():
        g = grades[proc]
        L += ["", f"## {proc}: the book of each test year", "",
              "| year | book | train med | train ruin | year return at $5k |", "|---|---|---|---|---|"]
        for y in TEST_YEARS:
            b = ch["chosen"][proc][str(y)]
            L.append(f"| {y} | {bk(b)} | {_d(b['train']['med']) if b else 'n/a'} | "
                     f"{_p(b['train']['ruin']) if b else 'n/a'} | "
                     f"{100 * g['history']['yearly_at_5k'].get(y, 0.0):+.0f}% |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V53_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"met": met, "pick": pick, "grades": grades, "chosen": ch["chosen"],
               "books": [[[[name[int(c)], s] for c, s in m], mn] for m, mn in ch["books"]], "n_scored": n_scored,
               "events": {r["group"]: r["events"] for r in reports}}
    (args.out / "v53_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:10]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("merge")
    c.add_argument("--src", type=Path, nargs="+", required=True)
    c.add_argument("--move", action="store_true", help="move single-source minute files instead of copying")
    c = sub.add_parser("factory")
    c.add_argument("--group", required=True, choices=V.GROUPS)
    c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    c.add_argument("--extras", type=Path, default=Path("outputs/v28/inputs"))
    c.add_argument("--data", type=Path, default=Path("outputs/v53"))
    c = sub.add_parser("select")
    c.add_argument("--factory", type=Path, required=True)
    for n in ("account", "books", "oos"):
        c = sub.add_parser(n)
        c.add_argument("--sel", type=Path, required=True)
        c.add_argument("--shard", type=int, default=0)
        c.add_argument("--shards", type=int, default=1)
        if n == "books":
            c.add_argument("--picks", type=Path, required=True)
        if n == "oos":
            c.add_argument("--choose", type=Path, required=True)
    c = sub.add_parser("pick")
    c.add_argument("--runs", type=Path, required=True)
    c = sub.add_parser("choose")
    c.add_argument("--acc", type=Path, required=True)
    c.add_argument("--books", type=Path, required=True)
    c = sub.add_parser("final")
    for k in ("factory", "sel", "choose", "oos"):
        c.add_argument(f"--{k}", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--procs", type=int, default=4)
    args = ap.parse_args()
    return {"merge": cmd_merge, "factory": cmd_factory, "select": cmd_select, "account": cmd_account,
            "pick": cmd_pick, "books": cmd_books, "choose": cmd_choose, "oos": cmd_oos,
            "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v53"
    raise SystemExit(main())
