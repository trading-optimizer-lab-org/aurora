#!/usr/bin/env python3
"""Options study 2: 0DTE structures, delta-hedged overnight and intraday straddles (SPY, QQQ), and monthly
single-stock straddles sorted on HV - IV.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_options_study2.py data --cache outputs/os2_cache \
        --end 2026-10-23
    python scripts/run_options_study2.py eval --cache outputs/os2_cache --out outputs/options_study2

See docs/research/OPTIONS_STUDY2_PREREGISTRATION.md. Only reports, counts and strategy returns are printed or
uploaded; raw market data stays in the cache folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_earnings_options import (  # noqa: E402
    DATA,
    TRADE,
    _cached_json,
    _days,
    _frame,
    _load,
    _utc,
    alpaca,
    contracts,
    daily_frame,
    fetch_bars,
)

from aurora.research import earnings_options as eo  # noqa: E402
from aurora.research import options_study2 as os2  # noqa: E402

ETFS = ("SPY", "QQQ")
START = "2024-01-22"
COLS = ["symbol", "expiration_date", "strike_price", "type", "root_symbol", "size"]
DAY = pd.Timedelta(days=1)


def cmd_probe(args) -> int:
    """Data-format checks only: which expiries are listed, bar coverage of 0DTE contracts, 1-minute bars."""
    a = alpaca()
    out: dict = {}
    for und in ("SPY", "QQQ", "IWM"):
        for lo, hi in (("2024-02-05", "2024-02-16"), ("2025-06-02", "2025-06-13")):
            ch = contracts(a, und, "inactive", pd.Timestamp(lo), pd.Timestamp(hi), 1, 2000, "call")
            out[f"{und} expiries {lo}"] = sorted({c["expiration_date"] for c in ch})
    for und, day, k in (("SPY", "2024-03-05", 505), ("QQQ", "2024-03-05", 435), ("SPY", "2025-06-10", 600)):
        ch = contracts(a, und, "inactive", pd.Timestamp(day), pd.Timestamp(day), k - 3, k + 3)
        syms = sorted(c["symbol"] for c in ch)
        out[f"{und} {day} contracts near {k}"] = len(syms)
        for tf in ("15Min", "1Min"):
            b = _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", syms,
                                  {"timeframe": tf, "start": f"{day}T13:00:00Z", "end": f"{day}T21:30:00Z"}))
            if b.empty:
                out[f"{und} {day} {tf}"] = "no bars"
                continue
            per = b.groupby("symbol")["t"].agg(["count", "min", "max"])
            out[f"{und} {day} {tf}"] = {"symbols_with_bars": len(per), "median_bars": float(per["count"].median()),
                                        "first": str(per["min"].min().time()), "last": str(per["max"].max().time())}
    # a weekly SPY contract on a day before its expiry: are there bars after 16:00 (SPY options trade to 16:15)?
    ch = contracts(a, "SPY", "inactive", pd.Timestamp("2024-03-08"), pd.Timestamp("2024-03-08"), 503, 507, "call")
    b = _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", sorted(c["symbol"] for c in ch),
                          {"timeframe": "15Min", "start": "2024-03-05T13:00:00Z", "end": "2024-03-05T21:30:00Z"}))
    out["SPY 2024-03-08 expiry on 2024-03-05, bar times"] = sorted({str(t.time()) for t in b["t"]}) if len(b) else []
    print(json.dumps(out, indent=1))
    return 0


def cmd_probe2(args) -> int:
    """Format check of the assets list: counts and attribute names only."""
    a = alpaca()
    out = {}
    for params in ({"status": "active", "asset_class": "us_equity"},
                   {"status": "active", "asset_class": "us_equity", "attributes": "options_enabled"}):
        got = a.get(f"{TRADE}/v2/assets", params) or []
        attrs: dict[str, int] = {}
        for x in got:
            for t in x.get("attributes") or []:
                attrs[t] = attrs.get(t, 0) + 1
        out[json.dumps(params)] = {"n": len(got), "tradable": sum(bool(x.get("tradable")) for x in got),
                                   "attributes": attrs, "keys": sorted(got[0]) if got else [],
                                   "spy_aapl": [x for x in got if x.get("symbol") in ("AAPL", "SPY")][:2]}
    print(json.dumps(out, indent=1))
    return 0


def _chain(df: pd.DataFrame, und: str) -> pd.DataFrame:
    df = df[(df["root_symbol"].fillna(und) == und) & (df["size"].fillna("100").astype(str) == "100")].copy()
    df["exp"] = pd.to_datetime(df["expiration_date"])
    df["k"] = df["strike_price"].astype(float)
    df["kind"] = np.where(df["type"] == "call", "C", "P")
    return df


def _expiry(ch: pd.DataFrame, e: pd.Timestamp) -> tuple[np.ndarray, dict]:
    """Strikes of expiry e listed as both call and put, and the (kind, strike) -> contract map."""
    g = ch[ch["exp"] == e]
    occ = {(r.kind, r.k): r.symbol for r in g.itertuples()}
    both = np.array(sorted({k for kind, k in occ if kind == "C"} & {k for kind, k in occ if kind == "P"}))
    return both, occ


def etf_plan(und: str, sessions: pd.DatetimeIndex, eday: dict, ch: pd.DataFrame) -> list[dict]:
    """Per session: the legs of every 0DTE structure at the 10:00 bar, and the N1 (15:45) and N2 (09:45)
    straddles of the first expiry 7 or more calendar days later."""
    rows: list[dict] = []
    exps = np.array(sorted(ch["exp"].unique()))
    for d in sessions:
        day = eday.get((und, d))
        both, occ = _expiry(ch, d)
        s0 = os2.bar_vw(day, 10, 0)
        if s0 and len(both):
            for trial in os2.ZDTE:
                legs = os2.structure(trial, both, s0)
                if legs:
                    rows.append({"und": und, "d": str(d.date()), "trial": trial, "s0": s0, "exp": str(d.date()),
                                 "legs": [[kind, k, q, occ[(kind, k)]] for kind, k, q in legs]})
        later = exps[exps >= np.datetime64(d + 7 * DAY)]
        if not len(later):
            continue
        e = pd.Timestamp(later[0])
        both, occ = _expiry(ch, e)
        if not len(both):
            continue
        for trial, (hh, mm) in (("N1", (15, 45)), ("N2", (9, 45))):
            s = os2.bar_vw(day, hh, mm)
            if s:
                k = eo.atm(both, s)
                rows.append({"und": und, "d": str(d.date()), "trial": trial, "s0": s, "exp": str(e.date()),
                             "legs": [["C", k, 1, occ[("C", k)]], ["P", k, 1, occ[("P", k)]]]})
    return rows


def third_friday(p: pd.Period) -> pd.Timestamp:
    d = pd.Timestamp(p.year, p.month, 15)
    return d + pd.Timedelta(days=(4 - d.weekday()) % 7)


def _contracts_both(a, syms: str, lo_e, hi_e, lo_k, hi_k) -> list[dict]:
    rows = contracts(a, syms, "inactive", lo_e, hi_e, lo_k, hi_k)
    if hi_e >= pd.Timestamp.now().normalize() - 3 * DAY:
        rows += contracts(a, syms, "active", lo_e, hi_e, lo_k, hi_k)
    return rows


def _bars_file(a, f: Path, url: str, syms: list[str], d: pd.Timestamp, extra: dict | None = None) -> None:
    if not f.exists():
        _frame(fetch_bars(a, url, sorted(set(syms)), dict({"timeframe": "15Min", "start": _utc(d, "13:00"),
                                                           "end": _utc(d, "21:15")}, **(extra or {})))
               ).to_parquet(f, index=False)


def data_etf(a, C: Path, start: pd.Timestamp, end: pd.Timestamp) -> None:
    sf = C / "etf15.parquet"
    if not sf.exists():
        _frame(fetch_bars(a, f"{DATA}/v2/stocks/bars", list(ETFS),
                          {"timeframe": "15Min", "start": _utc(start, "00:00"), "end": _utc(end + DAY, "04:00"),
                           "adjustment": "raw", "feed": "sip"})).to_parquet(sf, index=False)
    e15 = _load(C, "etf15")
    eday = _days(e15)
    spy = e15[e15["symbol"] == "SPY"]
    clock = spy["t"] - spy["t"].dt.normalize()
    open_ = set(spy.loc[clock == 9.5 * eo.H, "t"].dt.normalize())
    close_ = set(spy.loc[clock == 15.75 * eo.H, "t"].dt.normalize())
    sessions = pd.DatetimeIndex(sorted(d for d in open_ & close_ if start <= d <= end))
    pd.Series(sessions).to_frame("session").to_parquet(C / "sessions.parquet", index=False)
    print(f"etf sessions {len(sessions)}", flush=True)
    cf = C / "etf_contracts"
    cf.mkdir(exist_ok=True)
    plan: list[dict] = []
    for und in ETFS:
        px = e15[e15["symbol"] == und].set_index("t")["vw"]
        parts = []
        for m in pd.period_range(sessions[0], sessions[-1], freq="M"):
            f = cf / f"{und}_{m}.parquet"
            if not f.exists():
                p = px[(px.index >= m.start_time) & (px.index < m.end_time + DAY)]
                pd.DataFrame(_contracts_both(a, und, m.start_time, m.end_time + 15 * DAY, 0.95 * p.min(),
                                             1.05 * p.max()), columns=COLS).drop_duplicates("symbol").to_parquet(
                    f, index=False)
            parts.append(pd.read_parquet(f))
        ch = _chain(pd.concat(parts, ignore_index=True).drop_duplicates("symbol"), und)
        plan += etf_plan(und, sessions, eday, ch)
    (C / "etf_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    print(f"etf plan rows {len(plan)}", flush=True)
    need: dict[pd.Timestamp, set] = {}
    nxt = {d: sessions[i + 1] for i, d in enumerate(sessions[:-1])}
    for r in plan:
        d = pd.Timestamp(r["d"])
        syms = {leg[3] for leg in r["legs"]}
        need.setdefault(d, set()).update(syms)
        if r["trial"] == "N1" and d in nxt:
            need.setdefault(nxt[d], set()).update(syms)
    of = C / "etf_opt"
    of.mkdir(exist_ok=True)
    for n, (d, syms) in enumerate(sorted(need.items())):
        _bars_file(a, of / f"{d.date()}.parquet", f"{DATA}/v1beta1/options/bars", list(syms), d)
        if n % 100 == 0:
            print(f"etf option bars {n}/{len(need)}", flush=True)


def data_x(a, C: Path, end: pd.Timestamp, symbols: list[str], top: int) -> None:
    def fetch_assets():
        got = a.get(f"{TRADE}/v2/assets", {"status": "active", "asset_class": "us_equity",
                                            "attributes": "options_enabled"}) or []
        return sorted(x["symbol"] for x in got
                      if x.get("tradable") and "has_options" in (x.get("attributes") or []))
    assets = _cached_json(C / "assets.json", fetch_assets)
    if symbols:
        assets = [s for s in assets if s in set(symbols)]
    print(f"optionable assets {len(assets)}", flush=True)
    daily = daily_frame(a, assets, str(end.date()), C / "daily")
    close = daily.pivot_table(index="date", columns="symbol", values="c")
    dvol = (daily.assign(dv=daily["c"] * daily["v"])).pivot_table(index="date", columns="symbol", values="dv")
    dates = close.index
    rows, drops = [], {"no_contract": 0, "no_stock_price": 0, "no_expiry_price": 0, "split": 0, "no_hv": 0}
    for m in pd.period_range("2024-01", end.to_period("M"), freq="M"):
        t3, t3n = third_friday(m), third_friday(m + 1)
        after = dates[dates > t3]
        if t3n > end or not len(after) or after[0] < os2.DISCOVERY[0]:
            continue
        F = after[0]
        iF = int(dates.get_loc(F))
        prior = close.iloc[iF - 1]
        win = dvol.iloc[iF - 20:iF]
        med = win.median().where(win.count() >= 15)
        ok = med[(prior >= eo.MIN_PRICE) & med.notna()]
        uni = list(ok.sort_values(ascending=False).index[:top])
        lr = np.log(close.iloc[iF - 253:iF]).diff().iloc[1:]
        hv = (lr.std() * np.sqrt(252)).where(lr.count() >= 240)
        xc = C / "x_contracts"
        xc.mkdir(exist_ok=True)
        parts = []
        for j in range(0, len(uni), 100):
            f = xc / f"{m}_{j:04d}.parquet"
            if not f.exists():
                pd.DataFrame(_contracts_both(a, ",".join(uni[j:j + 100]), t3n - 3 * DAY, t3n + 3 * DAY, 0.01, 1e6),
                             columns=COLS).drop_duplicates("symbol").to_parquet(f, index=False)
            parts.append(pd.read_parquet(f))
        allc = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
        xs = C / "x_stock"
        xs.mkdir(exist_ok=True)
        _bars_file(a, xs / f"{F.date()}.parquet", f"{DATA}/v2/stocks/bars", uni, F,
                   {"adjustment": "raw", "feed": "sip"})
        sday = _days(_load(xs, str(F.date())))
        picks = []
        for sym in uni:
            ch = _chain(allc[allc["root_symbol"] == sym], sym)
            if ch.empty:
                drops["no_contract"] += 1
                continue
            e = min(ch["exp"].unique(), key=lambda x: (abs(pd.Timestamp(x) - t3n), x))
            both, occ = _expiry(ch, pd.Timestamp(e))
            s_f = os2.bar_vw(sday.get((sym, F)), 15, 30)
            if not len(both) or not s_f:
                drops["no_contract" if not len(both) else "no_stock_price"] += 1
                continue
            if pd.isna(hv.get(sym)):
                drops["no_hv"] += 1
                continue
            k = eo.atm(both, s_f)
            picks.append({"month": str(m), "F": F, "symbol": sym, "exp": pd.Timestamp(e), "k": k,
                          "C": occ[("C", k)], "P": occ[("P", k)], "s_f": s_f, "raw_f": eo.last_close(
                              sday.get((sym, F))), "hv": float(hv[sym])})
        xo = C / "x_opt"
        xo.mkdir(exist_ok=True)
        _bars_file(a, xo / f"{F.date()}.parquet", f"{DATA}/v1beta1/options/bars",
                   [p["C"] for p in picks] + [p["P"] for p in picks], F)
        for e in sorted({p["exp"] for p in picks}):
            _bars_file(a, xs / f"{e.date()}.parquet", f"{DATA}/v2/stocks/bars",
                       [p["symbol"] for p in picks if p["exp"] == e], e, {"adjustment": "raw", "feed": "sip"})
        exp_days = {e: _days(_load(xs, str(e.date()))) for e in {p["exp"] for p in picks}}
        for p in picks:
            s_t = eo.last_close(exp_days[p["exp"]].get((p["symbol"], p["exp"])))
            if s_t is None or p["exp"] not in dates or not p["raw_f"]:
                drops["no_expiry_price"] += 1
                continue
            f1 = p["raw_f"] / close.at[F, p["symbol"]]
            f2 = s_t / close.at[p["exp"], p["symbol"]]
            if not (abs(f2 / f1 - 1) <= 0.05):
                drops["split"] += 1
                continue
            rows.append(dict(p, s_t=s_t))
        print(f"x month {m}: universe {len(uni)}, positions planned {len(picks)}", flush=True)
    pd.DataFrame(rows).to_parquet(C / "x_plan.parquet", index=False)
    (C / "x_drops.json").write_text(json.dumps(drops), encoding="utf-8")


def cmd_data(args) -> int:
    a = alpaca()
    C = args.cache
    C.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(args.end)
    data_etf(a, C, pd.Timestamp(args.start), end)
    data_x(a, C, end, [s for s in args.symbols.split(",") if s], args.x_top)
    print(f"done; alpaca calls {a.calls}", flush=True)
    return 0


def _leg_exit(day, kind: str, k: float, s_last: float | None, short: bool, p_in: float, rule) -> tuple[float, bool]:
    p = rule(day)
    if p is not None:
        return p, False
    v = eo.intrinsic(kind, k, s_last) if s_last else 0.0
    return (v + 0.1 * p_in if short else v), True


def _base(und: str, d: pd.Timestamp) -> dict | None:
    per = os2.period(d)
    if per is None:
        return None
    y, w, _ = d.isocalendar()
    return {"symbol": und, "entry": d, "period": per, "week": f"{y}-{w:02d}", "year": d.year,
            "weekday": d.day_name()[:3]}


def etf_trades(C: Path) -> tuple[list[dict], dict]:
    plan = json.loads((C / "etf_plan.json").read_text(encoding="utf-8"))
    sessions = pd.DatetimeIndex(pd.read_parquet(C / "sessions.parquet")["session"])
    nxt = {d: sessions[i + 1] for i, d in enumerate(sessions[:-1])}
    eday = _days(_load(C, "etf15"))
    oday = _days(_load(C / "etf_opt"))
    gaps = set()
    for r in plan:
        if r["und"] == "SPY" and r["trial"] == "Z1_short_straddle":
            d = pd.Timestamp(r["d"])
            if eo.last_close(oday.get((r["legs"][0][3], d))) is None:
                gaps.add(d)
    rows: list[dict] = []
    drop = {"gap_days": len(gaps), "gap": 0, "no_entry": 0, "no_iv": 0, "no_exit_price": 0}
    for r in plan:
        d = pd.Timestamp(r["d"])
        base = _base(r["und"], d)
        if base is None:
            continue
        exit_day = nxt.get(d) if r["trial"] == "N1" else d
        if d in gaps or exit_day is None or exit_day in gaps:
            drop["gap"] += 1
            continue
        legs = [(kind, float(k), int(q)) for kind, k, q, _ in r["legs"]]
        occs = [x[3] for x in r["legs"]]
        s0 = float(r["s0"])
        if r["trial"].startswith("Z"):
            p_in = [os2.bar_vw(oday.get((o, d)), 10, 0) for o in occs]
            if any(p is None for p in p_in):
                drop["no_entry"] += 1
                continue
            s_close = os2.bar_close(eday.get((r["und"], d)), 15, 45) or eo.last_close(eday.get((r["und"], d)))
            if s_close is None:
                drop["no_exit_price"] += 1
                continue
            outs, fb = [], False
            for (kind, k, _), o in zip(legs, occs):
                p = os2.bar_vw(oday.get((o, d)), 15, 45)
                fb = fb or p is None
                outs.append((p, True) if p is not None and p > os2.EXPIRE_AT else (eo.intrinsic(kind, k, s_close),
                                                                                    False))
            pnl = {c: sum(os2.leg_pnl(q, pi, po, cl, cost) for (_, _, q), pi, (po, cl) in zip(legs, p_in, outs))
                   for c, cost in (("base", os2.ETF_BASE), ("high", os2.ETF_HIGH))}
            ml = os2.max_loss(legs, p_in, os2.ETF_BASE)
            rows.append(dict(base, trial=r["trial"], net=pnl["base"] / s0, net_high=pnl["high"] / s0, fallback=fb,
                             ret_ml=pnl["base"] / ml if ml > 0 else float("nan"),
                             t_in=d + 10 * eo.H, t_out=d + 16 * eo.H))
            continue
        hh, mm = (15, 45) if r["trial"] == "N1" else (9, 45)
        p_in = [os2.bar_vw(oday.get((o, d)), hh, mm) for o in occs]
        if any(p is None for p in p_in):
            drop["no_entry"] += 1
            continue
        k = legs[0][1]
        t_in = d + hh * eo.H + mm * eo.M
        t = ((pd.Timestamp(r["exp"]) + 16 * eo.H) - t_in) / pd.Timedelta(days=365)
        v = os2.implied_vol(sum(p_in), s0, k, t)
        if v is None:
            drop["no_iv"] += 1
            continue
        delta = os2.straddle_delta(s0, k, t, v)
        side = -1 if r["trial"] == "N1" else 1
        uday = eday.get((r["und"], exit_day))
        s_last = eo.last_close(uday)
        if r["trial"] == "N1":
            def rule(x):
                return eo.price_morning(x)
            s_out = eo.price_morning(uday)
        else:
            def rule(x):
                return os2.bar_vw(x, 15, 45)
            s_out = os2.bar_vw(uday, 15, 45)
        if s_out is None:
            drop["no_exit_price"] += 1
            continue
        outs = [_leg_exit(oday.get((o, exit_day)), kind, k, s_last, side < 0, pi, rule)
                for (kind, _, _), o, pi in zip(legs, occs, p_in)]
        p_out = [x for x, _ in outs]
        net = {c: os2.hedged_return(side, p_in, p_out, s0, s_out, delta, cost)
               for c, cost in (("base", os2.ETF_BASE), ("high", os2.ETF_HIGH))}
        row = dict(base, net=net["base"], net_high=net["high"], fallback=any(f for _, f in outs),
                   ret_ml=float("nan"), t_in=t_in, t_out=exit_day + 9.75 * eo.H if side < 0 else d + 15.75 * eo.H)
        if r["trial"] == "N1":
            rows.append(dict(row, trial="N1_overnight_short"))
            if (exit_day - d).days >= 3:
                rows.append(dict(row, trial="N3_weekend_short"))
        else:
            rows.append(dict(row, trial="N2_intraday_long"))
    return rows, drop


def x_trades(C: Path) -> tuple[list[dict], dict]:
    plan = pd.read_parquet(C / "x_plan.parquet")
    drop = json.loads((C / "x_drops.json").read_text(encoding="utf-8"))
    drop["no_entry"] = drop["no_iv"] = 0
    if plan.empty:
        return [], drop
    xo = _days(_load(C / "x_opt"))
    pos = []
    for p in plan.itertuples():
        c, q = os2.bar_vw(xo.get((p.C, p.F)), 15, 30), os2.bar_vw(xo.get((p.P, p.F)), 15, 30)
        if c is None or q is None:
            drop["no_entry"] += 1
            continue
        t = ((p.exp + 16 * eo.H) - (p.F + 15.5 * eo.H)) / pd.Timedelta(days=365)
        iv = os2.implied_vol(c + q, p.s_f, p.k, t)
        if iv is None:
            drop["no_iv"] += 1
            continue
        pos.append({"month": p.month, "F": p.F, "symbol": p.symbol, "signal": p.hv - iv,
                    **{f"{side}_{c_}": os2.hold_return(sgn, c, q, p.k, p.s_t, cost)
                       for side, sgn in (("long", 1), ("short", -1))
                       for c_, cost in (("base", os2.STOCK_BASE), ("high", os2.STOCK_HIGH))}})
    df = pd.DataFrame(pos)
    rows = []
    for month, g in df.groupby("month"):
        if len(g) < 10:
            continue
        dec = os2.deciles(g["signal"])
        top, bot = g[dec == 9], g[dec == 0]
        base = _base("stocks", g["F"].iloc[0])
        if base is None:
            continue
        base["month"] = month
        rows.append(dict(base, trial="X2_long_cheap", net=top["long_base"].mean(), net_high=top["long_high"].mean(),
                         positions=len(top), fallback=False))
        rows.append(dict(base, trial="X3_short_rich", net=bot["short_base"].mean(),
                         net_high=bot["short_high"].mean(), positions=len(bot), fallback=False))
        rows.append(dict(base, trial="X1_vol_spread", net=top["long_base"].mean() + bot["short_base"].mean(),
                         net_high=top["long_high"].mean() + bot["short_high"].mean(), positions=len(top) + len(bot),
                         fallback=False))
    return rows, drop


def trades(C: Path) -> tuple[pd.DataFrame, dict]:
    er, ed = etf_trades(C)
    xr, xd = x_trades(C)
    return pd.DataFrame(er + xr), {"etf": ed, "x": xd}


def _pct(x) -> str:
    return "-" if x is None or x != x else f"{100 * x:.3f}%"


def _num(x) -> str:
    return "-" if x is None or x != x else f"{x:.2f}"


def evaluate(tr: pd.DataFrame, drop: dict) -> dict:
    res: dict = {"drops": drop, "discovery": {}, "validation": {}, "books": {}, "breakdown": {}}
    for per in ("discovery", "validation"):
        for k in os2.TRIALS:
            t = tr[(tr["trial"] == k) & (tr["period"] == per)] if len(tr) else tr
            res[per][k] = os2.stats(t, monthly=k.startswith("X"))
    res["decision"] = os2.decide(res["discovery"], res["validation"])
    for k in os2.TRIALS:
        t = tr[tr["trial"] == k] if len(tr) else tr
        groups = ("year",) if k.startswith("X") else ("symbol", "year", "weekday")
        res["breakdown"][k] = {f"{c}={v}": os2.stats(g, monthly=k.startswith("X")) for c in groups
                               for v, g in t.groupby(c)} if len(t) else {}
        if k in ("Z2_iron_fly", "Z3_iron_condor") and len(t):
            res["breakdown"][k]["on_max_loss"] = {per: float(g["ret_ml"].mean()) for per, g in t.groupby("period")}
    for k in res["decision"]["discovery_pass"]:
        if k not in ("Z2_iron_fly", "Z3_iron_condor"):
            continue
        for per in ("discovery", "validation"):
            t = tr[(tr["trial"] == k) & (tr["period"] == per)]
            res["books"][f"{k}:{per}"] = eo.book([eo.Trade(r.t_in, r.t_out, r.ret_ml, 0.0) for r in t.itertuples()
                                                  if r.ret_ml == r.ret_ml])
    res["fallback_share"] = {k: float(g["fallback"].mean()) for k, g in tr.groupby("trial")} if len(tr) else {}
    return res


def cmd_eval(args) -> int:
    tr, drop = trades(args.cache)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.counts_only:
        info = {"drops": drop, "trades": {} if tr.empty else tr.groupby(["trial", "period"]).size().unstack()
                .fillna(0).astype(int).to_dict(),
                "fallback_share": 0 if tr.empty else float(tr["fallback"].mean())}
        print(json.dumps(info, indent=1, default=str))
        return 0
    res = evaluate(tr, drop)
    (args.out / "summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    tr[["trial", "symbol", "entry", "period", "net", "net_high"]].to_csv(args.out / "trades.csv", index=False)
    (args.out / "REPORT.md").write_text(render(res), encoding="utf-8")
    print(render(res))
    return 0


def render(res: dict) -> str:
    d = res["decision"]
    lines = ["# Options study 2 (pre-registered, 11 trials)", "",
             f"Drops: {json.dumps(res['drops'])}.", "",
             "Z: net P&L in percent of spot. N: on the straddle price. X: monthly mean straddle return "
             "(trades = straddle positions).", "",
             "| trial | disc trades | mean | t | mean high | hit | ES 1% | val trades | mean | t | mean high | hit |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in os2.TRIALS:
        a, b = res["discovery"][k], res["validation"][k]
        lines.append(f"| {k} | {a.get('trades', 0)} | {_pct(a.get('mean'))} | {_num(a.get('t'))} | "
                     f"{_pct(a.get('mean_high'))} | {_pct(a.get('hit'))} | {_pct(a.get('es1'))} | "
                     f"{b.get('trades', 0)} | {_pct(b.get('mean'))} | {_num(b.get('t'))} | "
                     f"{_pct(b.get('mean_high'))} | {_pct(b.get('hit'))} |")
    lines += ["", f"Discovery pass (t >= {os2.T_DISCOVERY}, mean high > 0, 200+ trades): "
              f"{', '.join(d['discovery_pass']) or 'none'}. Validation pass (t >= {os2.T_VALIDATION}, mean high > 0): "
              f"{', '.join(d['validation_pass']) or 'none'}. **{'Met' if d['met'] else 'Not met'}.**", ""]
    if res["books"]:
        lines += ["| book ($100k, 2% of equity on max loss, 15% at most) | taken | end | CAGR | max DD | worst session |",
                  "|---|---|---|---|---|---|"]
        for k, b in res["books"].items():
            lines.append(f"| {k} | {b['taken']} | {b['end']:,.0f} | {_pct(b['cagr'])} | {_pct(b['max_dd'])} | "
                         f"{_pct(b['worst_session'])} |")
        lines.append("")
    lines += ["## Breakdown (all periods, base costs, no decision)", "",
              "| trial | group | trades | mean | t | hit |", "|---|---|---|---|---|---|"]
    for k, br in res["breakdown"].items():
        for g, s in br.items():
            if g == "on_max_loss":
                lines.append(f"| {k} | mean on max loss | - | " + ", ".join(f"{p} {_pct(v)}" for p, v in s.items())
                             + " | - | - |")
                continue
            lines.append(f"| {k} | {g} | {s.get('trades', 0)} | {_pct(s.get('mean'))} | {_num(s.get('t'))} | "
                         f"{_pct(s.get('hit'))} |")
    lines += ["", "Exit fallbacks share: " + ", ".join(f"{k} {_pct(v)}" for k, v in res["fallback_share"].items())]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("probe")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("probe2")
    p.set_defaults(fn=cmd_probe2)
    p = sub.add_parser("data")
    p.add_argument("--cache", type=Path, default=Path("outputs/os2_cache"))
    p.add_argument("--start", default=START)
    p.add_argument("--end", required=True)
    p.add_argument("--symbols", default="")
    p.add_argument("--x-top", type=int, default=500)
    p.set_defaults(fn=cmd_data)
    p = sub.add_parser("eval")
    p.add_argument("--cache", type=Path, default=Path("outputs/os2_cache"))
    p.add_argument("--out", type=Path, default=Path("outputs/options_study2"))
    p.add_argument("--counts-only", action="store_true")
    p.set_defaults(fn=cmd_eval)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
