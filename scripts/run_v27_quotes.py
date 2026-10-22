"""v27 A: v26's $100k one-account book with each trade's own quoted spreads (V27_PREREGISTRATION.md, section A).

  legs    the trades book A takes (COMBO26's members, each year its v26 pick; v26's sizing choice for $100k), with
          their entry and exit minutes, gross paths and weights (kept on the runner, never uploaded)
  quotes  Alpaca SIP quotes in each leg's minute: the median quoted spread over the mid
  costs   book A rebuilt with the tier half-spreads (must reproduce v26), the measured ones (the tier value where no
          quote was found) and 1.5 times the measured ones: QUOTES.md, quotes_summary.json, quote_streams.parquet
Reads v26's report (``V26_REPORT``) and final report (``V26_FINAL``).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R26 = _script("run_v26")
R22, R19, R16, R14 = R26.R22, R26.R19, R26.R16, R26.R14
V26_REPORT = Path(os.environ.get("V26_REPORT", "outputs/v26w/report"))
V26_FINAL = Path(os.environ.get("V26_FINAL", "outputs/v26w/final"))
DEFAULT = (0.005, 0.20, 1.0)
ACCOUNT = 100_000.0
LEG = {"open": 0, "session": 1, "close": 2, "stop": 2, "ah": sh.LEG_AH, "pm": sh.LEG_PM}


def book_terms(final: Path) -> tuple[float, float, float, str]:
    """(risk, cap, gross, name) of v26's $100k choice for book A, or the pre-registered default."""
    p = final / "final_summary.json"
    name = json.loads(p.read_text(encoding="utf-8")).get("choice", {}).get("A100000") if p.exists() else None
    m = re.match(r"A_A100k_R([\d.]+)_C(\d+)_G([\d.]+)_mid$", name or "")
    if not m:
        return (*DEFAULT, "default (risk 0.5%, cap 20%, gross 1x)")
    return float(m.group(1)) / 100, int(m.group(2)) / 100, float(m.group(3)), str(name)


def leg_time(day: pd.Timestamp, kind: str, minute: int, nxt: pd.Timestamp | None) -> pd.Timestamp:
    """The UTC start of a leg's minute: the open, a session minute, the last minute (a close or a stop inside a later
    day's daily bar), an after-hours minute, or a minute of the next session's premarket."""
    ny = pd.Timestamp(day.year, day.month, day.day, tz="America/New_York")
    if kind == "open":
        t = ny + pd.Timedelta(hours=9, minutes=30)
    elif kind in ("close", "stop"):
        t = ny + pd.Timedelta(hours=15, minutes=59)
    elif kind == "session":
        t = ny + pd.Timedelta(hours=9, minutes=30 + minute)
    elif kind == "ah":
        t = ny + pd.Timedelta(hours=16, minutes=minute)
    else:
        assert nxt is not None
        t = pd.Timestamp(nxt.year, nxt.month, nxt.day, tz="America/New_York") + \
            pd.Timedelta(hours=4, minutes=minute - sh.AH_END)
    return t.tz_convert("UTC")


def taken_ids(items: list[tuple], n_dates: int, gross_cap: float, max_open: int = 20) -> list[int]:
    """run_v26._net then run_v19s.joint_book, returning the ids of the trades the book takes. Items: (first row,
    returns, priority, weight, column, id)."""
    netted: list[tuple] = []
    until: dict[int, int] = {}
    for it in sorted(items, key=lambda p: (p[0], -p[2])):
        i0, r, _, _, j, _ = it
        if j >= 0 and until.get(j, -1) >= i0:
            continue
        until[j] = i0 + len(r) - 1
        netted.append(it)
    gross, out = np.zeros(n_dates), []
    open_until: list[int] = []
    for i0, r, _, w, _, tid in sorted(netted, key=lambda p: (p[0], -p[2])):
        open_until = [x for x in open_until if x >= i0]
        n = min(len(r), n_dates - i0)
        if n <= 0 or w <= 0 or len(open_until) >= max_open or gross[i0:i0 + n].max() + w > gross_cap + 1e-9:
            continue
        gross[i0:i0 + n] += w
        open_until.append(i0 + n - 1)
        out.append(tid)
    return out


def cmd_legs(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v27 runs on the whole sample: the unlock must be set")
    R19.load(args.inputs)
    risk, cap, gcap, name = book_terms(V26_FINAL)
    summ = json.loads((V26_REPORT / "summary.json").read_text(encoding="utf-8"))
    D, table = R14._G["D"], R16._W["table"]
    dates, cols = D["dates"], R14._G["cols"]
    keep_acct, core.ACCOUNT = core.ACCOUNT, ACCOUNT
    rows: list[dict] = []
    try:
        for y, fams in summ["members"].items():
            for fam in fams:
                nm = summ["families"][fam]["picks"].get(str(y))
                if not nm:
                    continue
                k26, ci = R26._split(nm)
                cfg = R26.registry()[k26][1][ci]
                sh.set_params({k: cfg[k] for k in ("hold", "stop", "ext", "rally", "scale")})
                v19.set_costs("r4", R22.SLIP, R22.R4)
                kind, _, data = R26.entries(k26, cfg["entry"])
                if kind == "intra":
                    tr = R26._keep_rows(pd.DataFrame([sh.intra_row(D, *a) for a in data]), cfg["filt"])
                    if tr.empty:
                        continue
                    tr = tr[pd.to_datetime(tr["date"]).dt.year == int(y)]
                    tr = tr.sort_values(["date", "minute", "prio"], ascending=[True, True, False],
                                        kind="stable").groupby("date", sort=False).head(5)
                    e, s_ = tr["entry"].to_numpy(float), tr["stop"].to_numpy(float)
                    w = np.minimum(np.minimum(cap, risk / np.maximum(np.abs(e - s_) / e, 1e-4)),
                                   0.02 * np.nan_to_num(tr["liq"].to_numpy(float)) / ACCOUNT)
                    for r, ww in zip(tr.to_dict("records"), w):
                        rows.append({"family": fam, "symbol": str(r["symbol"]), "t": int(r["t"]), "first": int(r["t"]),
                                     "in_kind": "open" if int(r["leg_in"]) == 0 else "session",
                                     "in_min": int(r["minute"]), "x_row": int(r["x_row"]), "x_kind": str(r["x_kind"]),
                                     "x_min": int(r["x_min"]), "price": float(r["price"]), "so": float(r["so"]),
                                     "nights": float(r["nights"]), "prio": float(r["prio"]),
                                     "rets": np.asarray(r["rets"], float), "w": float(ww), "daily": False})
                else:
                    w_max = min(cap, 0.05 * risk / 0.005)
                    for s in R26._keep_specs(data, cfg["filt"]):
                        if dates[s.t].year != int(y):
                            continue
                        p = sh.daily_path(D, s, table, 1.0, 1.0, True, w_max)
                        if p is None:
                            continue
                        x = dict(sh.EXIT)
                        raw = float(D["P"][s.t if s.kind == "close" else s.t - 1, s.j])
                        rows.append({"family": fam, "symbol": str(D["cols"][s.j]), "t": int(s.t), "first": int(p[0]),
                                     "in_kind": "close" if s.kind == "close" else "open", "in_min": -1,
                                     "x_row": int(x.get("row", s.t)), "x_kind": str(x.get("kind", "close")),
                                     "x_min": int(x.get("minute", -1)), "price": raw, "so": float(D["SO"][s.t, s.j]),
                                     "nights": float(len(p[1]) - (0 if s.kind == "close" else 1)),
                                     "prio": float(s.prio), "rets": np.asarray(p[1], float), "w": float(p[3]),
                                     "daily": True})
                sh.set_params(None)
    finally:
        core.ACCOUNT = keep_acct
        sh.set_params(None)
    t = pd.DataFrame(rows)
    if t.empty:
        raise SystemExit("book A has no trades")
    t["j"] = t["symbol"].map(cols).fillna(-1).astype(int)
    intra = ~t["daily"].to_numpy(bool)
    if intra.any():  # an intraday trade's weight carries its availability, as in v26's book
        _, avail = v19._costs(t["price"].to_numpy(float), t["so"].to_numpy(float), -np.ones(len(t)),
                              t["nights"].to_numpy(float), np.zeros(len(t)), table, 1.0, 1.0, True)
        t["w"] = np.where(intra, t["w"].to_numpy(float) * avail, t["w"].to_numpy(float))
    items = [(int(f), r, float(p), float(w), int(j), i)
             for i, (f, r, p, w, j) in enumerate(zip(t["first"], t["rets"], t["prio"], t["w"], t["j"]))]
    t = t.iloc[sorted(taken_ids(items, len(dates), gcap))].reset_index(drop=True)
    last = len(dates) - 1
    t["in_ts"] = [leg_time(dates[u], k, m, None) for u, k, m in zip(t["t"], t["in_kind"], t["in_min"])]
    t["out_ts"] = [leg_time(dates[u], k, m, dates[min(u + 1, last)])
                   for u, k, m in zip(t["x_row"], t["x_kind"], t["x_min"])]
    args.out.mkdir(parents=True, exist_ok=True)
    t.to_pickle(args.out / "legs.pkl")
    (args.out / "book.json").write_text(json.dumps({"risk": risk, "cap": cap, "gross": gcap, "name": name,
                                                    "trades": len(t)}), encoding="utf-8")
    print(json.dumps({"book": name, "trades": len(t), "exits": t["x_kind"].value_counts().to_dict()}), flush=True)
    return 0


def cmd_quotes(args) -> int:
    D26 = _script("run_v26_data")
    D14 = D26.D14
    t = pd.read_pickle(args.out / "legs.pkl")
    legs = pd.concat([t[["symbol", "in_ts"]].set_axis(["symbol", "ts"], axis=1),
                      t[["symbol", "out_ts"]].set_axis(["symbol", "ts"], axis=1)]).drop_duplicates()
    legs = legs.iloc[np.random.default_rng(27).permutation(len(legs))]
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    print(f"quote minutes: {len(legs)}", flush=True)

    def one(sym: str, ts: pd.Timestamp) -> tuple:
        if time.time() - t0 > args.budget_min * 60:
            return sym, ts, np.nan, -1
        return (sym, ts, *D26._quote(sym, ts, headers, limiter))

    out = []
    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, s, pd.Timestamp(x)) for s, x in zip(legs["symbol"], legs["ts"])]
        for n, f in enumerate(as_completed(futs)):
            out.append(dict(zip(("symbol", "ts", "spread", "n"), f.result())))
            if n % 1000 == 0:
                print(f"quotes: {n}/{len(futs)}, {time.time() - t0:.0f}s", flush=True)
    q = pd.DataFrame(out)
    q.to_pickle(args.out / "spreads.pkl")
    print(json.dumps({"minutes": len(q), "with_quotes": int(q["spread"].notna().sum()),
                      "not_asked": int((q["n"] < 0).sum())}), flush=True)
    return 0


def cmd_costs(args) -> int:
    R19.load(args.inputs)
    S = _script("run_v19s")
    D, table = R14._G["D"], R16._W["table"]
    t = pd.read_pickle(args.out / "legs.pkl")
    q = pd.read_pickle(args.out / "spreads.pkl")
    book = json.loads((args.out / "book.json").read_text(encoding="utf-8"))
    quoted = {(s, pd.Timestamp(x)): v for s, x, v in zip(q["symbol"], q["ts"], q["spread"])}
    half = R22.R4
    v19.set_costs("r4", R22.SLIP, half)
    px = np.maximum(t["price"].to_numpy(float), 0.01)
    tier = np.select([px < 2, px < 5, px < 10], [0, 1, 2], 3)
    li, lo = t["in_kind"].map(LEG).to_numpy(int), t["x_kind"].map(LEG).to_numpy(int)
    tier_in, tier_out = half[tier, li], half[tier, lo]
    m_in = np.array([quoted.get((s, pd.Timestamp(x)), np.nan) for s, x in zip(t["symbol"], t["in_ts"])]) / 2
    m_out = np.array([quoted.get((s, pd.Timestamp(x)), np.nan) for s, x in zip(t["symbol"], t["out_ts"])]) / 2
    meas = np.where(np.isfinite(m_in), m_in, tier_in) + np.where(np.isfinite(m_out), m_out, tier_out)
    other, _ = v19._costs(px, t["so"].to_numpy(float), -np.ones(len(t)), t["nights"].to_numpy(float),
                          np.zeros(len(t)), table, 0.0, 1.0, False, (li, lo))
    dates, cash = D["dates"], D["cash"]
    a, b = "2018-01-01", str(core.last_day().date())
    idx = S.draws(len(dates[(dates >= a) & (dates <= b)]), seed=26)
    res, streams = {}, {}
    for nm, hs in (("tier", tier_in + tier_out), ("measured", meas), ("measured x1.5", 1.5 * meas)):
        paths = []
        for i in range(len(t)):
            rr = np.array(t["rets"].iat[i], float)
            rr[0] -= hs[i] + other[i]
            paths.append((int(t["first"].iat[i]), rr, float(t["prio"].iat[i]), float(t["w"].iat[i])))
        s = S.joint_book(paths, dates, book["gross"]).loc[a:b]  # type: ignore[misc]
        streams[nm] = s
        res[nm] = {**S.stats(s, cash), **S.bootstrap(s.to_numpy(), idx)}
    by: list[dict] = []
    for kind in LEG:
        for k in range(4):
            si = (t["in_kind"].to_numpy() == kind) & (tier == k)
            so = (t["x_kind"].to_numpy() == kind) & (tier == k)
            vals, tv = np.r_[m_in[si], m_out[so]], np.r_[tier_in[si], tier_out[so]]
            if len(vals):
                ok = np.isfinite(vals)
                by.append({"leg": kind, "tier": k, "legs": int(len(vals)), "quoted": int(ok.sum()),
                           "measured": float(np.median(vals[ok])) if ok.any() else np.nan,
                           "tier_value": float(np.median(tv))})
    names = ("<$2", "$2-5", "$5-10", "$10-20")
    L = [f"# v27 A: v26's $100k book with each trade's own quotes ({book['name']})", "",
         f"{len(t)} trades the book took (risk {book['risk']:.2%}, cap {book['cap']:.0%}, gross {book['gross']:g}x); "
         f"{int(np.isfinite(m_in).sum() + np.isfinite(m_out).sum())} of {2 * len(t)} legs with a quote in their minute "
         "(the tier value elsewhere). Half-spreads (half the quoted spread over the mid).", "",
         "| leg | price | legs | quoted | median measured | tier value |", "|---|---|---|---|---|---|"]
    L += [f"| {r['leg']} | {names[int(r['tier'])]} | {r['legs']} | {r['quoted']} | {R26._pc(r['measured'])} | "
          f"{R26._pc(r['tier_value'])} |" for r in by]
    L += ["", "| half-spreads | Sortino | CAGR | max DD | worst day | p75 | median bootstrap CAGR |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {nm} | {R26._f2(r['sortino'])} | {R26._pc(r['cagr'])} | {R26._pc(r['dd'])} | {R26._pc(r['worst_day'])} "
          f"| {r['p_dd75']:.1%} | {R26._pc(r['cagr_med'])} |" for nm, r in res.items()]
    (args.out / "QUOTES.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "quotes_summary.json").write_text(json.dumps({"book": book, "results": res, "legs": by}, indent=1,
                                                             default=float), encoding="utf-8")
    pd.DataFrame(streams).astype(np.float32).to_parquet(args.out / "quote_streams.parquet")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("legs", "quotes", "costs"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--budget-min", type=float, default=280.0)
    ap.add_argument("--out", type=Path, default=Path("outputs/v27w/quotes"))
    args = ap.parse_args()
    return {"legs": cmd_legs, "quotes": cmd_quotes, "costs": cmd_costs}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
