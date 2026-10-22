"""v28 after the report (V28_PREREGISTRATION.md section 6): the one-account book of COMBO28's members (and of
COMBO26's) under TradeZero's margin by price, locate and pre-borrow costs, book construction, the choice by the
owner's rule, a sensitivity battery around it, the worst trades, and each family's stream on each symbol half.

  core    one shard of the construction grid (book, risk, cap, gross, max open, new a day, order, sector cap) at the
          middle and high costs, TradeZero International's margin, 0.5% locate a short
  sens    the choice for each book and its battery (margin rules, locate, pre-borrow, spreads, entry delay,
          accounts, years left out, rule-change subsamples, worst trades)
  halves  one shard of families: the walk-forward stream on each symbol half with the same picks
  final   AFTER.md
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from aurora.research import v28_ideas as v28


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R28 = _script("run_v28")
R26, R22 = R28.R26, R28.R22
R14, R16 = R22.R14, R22.R16
S = _script("run_v19s")
DATA = Path("docs/research/data")
RISKS = (0.0025, 0.005, 0.01, 0.015, 0.02)
CAPS = (0.20, 0.40)
GROSS = (1.0, 1.5, 2.0)
MAX_OPEN = (10, 20, 30)
MAX_NEW = (3, 5, 10)
ORDERS = ("time", "move", "liquid", "risk")
SECTOR = ("none", "sic2")
LOCATE, PREBORROW = (0.0, 0.0025, 0.005, 0.01, 0.02, 0.03), (0.0, 0.005, 0.01)
SPREADS = (1.0, 1.25, 1.5, 1.75, 2.0)
DELAYS = (0, 1, 2, 5)
ACCOUNTS = (25_000.0, 100_000.0, 250_000.0, 500_000.0, 1_000_000.0)
BASE_LOCATE = 0.005
T1, NASDAQ = pd.Timestamp("2024-05-28"), pd.Timestamp("2025-01-17")
_HALF: dict = {}


def half_of(sym) -> int:
    s = str(sym)
    if s not in _HALF:
        _HALF[s] = int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) % 2
    return _HALF[s]


# ---------------------------------------------------------------- margin by price

def margin(price: np.ndarray, side: np.ndarray, rule: str, when: str) -> np.ndarray:
    """Equity a position needs per dollar of its value. ``when``: 'intra', 'night' (held over a close) or 'ah'."""
    p = np.maximum(np.asarray(price, float), 0.01)
    short = np.asarray(side) < 0
    if rule == "none":
        return np.zeros(len(p))
    if rule == "tzi":
        if when == "intra":
            m = np.where(p < 2.5, 2.5 / p, np.where(p < 5, 1.0, 1 / 6))
        elif when == "night":
            m = np.where(p < 2.5, 2.5 / p, np.where(p < 5, 1.0, 0.5))
        else:
            m = np.where(p < 2.5, 5.0 / p, np.where(p < 5, 1.0, 0.5))
        longm = 1 / 6 if when == "intra" else 0.5
    else:  # tzus
        m = np.where(p < 5, 5.0 / p, 0.25 if when == "intra" else 0.5)
        longm = 0.25 if when == "intra" else 0.5
    return np.where(short, m, longm)


# ---------------------------------------------------------------- trade items of one pick

def _v26_cfg(name: str) -> tuple[str, dict]:
    """A v26 configuration by its v26 name (v26's own grid), and its kind."""
    key, ci = name.rsplit("|", 1)
    kind, picks = R26.entries_of()[key]
    return kind, R26.shield_grid(kind, picks)[int(ci)]


def _rows_items(t: pd.DataFrame, table: dict, risk: float, cap: float, account: float, spread: float, fee: float,
                fam: str) -> list[dict]:
    """Intraday-style trade rows sized as v26's book (risk to the stop, the cap, 2% of the dollar volume before the
    entry, the family's first five a day)."""
    if t.empty:
        return []
    t = t.sort_values(["date", "minute", "prio"], ascending=[True, True, False], kind="stable").groupby(
        "date", sort=False).head(5)
    e, s = t["entry"].to_numpy(float), t["stop"].to_numpy(float)
    dist = np.abs(e - s) / e
    w = np.minimum(np.minimum(cap, risk / np.maximum(dist, 1e-4)), 0.02 * np.nan_to_num(t["liq"].to_numpy(float))
                   / account)
    cost, avail = v19._costs(t["price"].to_numpy(), t["so"].to_numpy(), t["side"].to_numpy(), t["nights"].to_numpy(),
                             t["opens"].to_numpy(), table, spread, fee, False,
                             (t["leg_in"].to_numpy(), t["leg_out"].to_numpy()))
    cols = t["symbol"].astype(str).map(R14._G["cols"]).fillna(-1).astype(int).to_numpy()
    out = []
    for i, (i0, r, pr) in enumerate(zip(t["t"].to_numpy(), t["rets"], t["prio"].to_numpy(float))):
        rr = np.array(r, float)
        rr[0] -= cost[i]
        out.append({"i0": int(i0), "r": rr, "prio": float(pr), "w": float(w[i] * avail[i]), "j": int(cols[i]),
                    "price": float(t["price"].iloc[i]), "side": int(t["side"].iloc[i]),
                    "nights": float(t["nights"].iloc[i]), "ah": int(t["leg_in"].iloc[i]) == sh.LEG_AH,
                    "liq": float(t["liq"].iloc[i]), "fam": fam, "sym": str(t["symbol"].iloc[i])})
    return out


def _spec_items(D: dict, specs: list, table: dict, risk: float, cap: float, account: float, spread: float,
                fee: float, fam: str) -> list[dict]:
    w_max = min(cap, 0.05 * risk / 0.005)
    out = []
    for s in specs:
        p = v19.path19(D, s, table, spread, fee, False, w_max)
        if p is None:
            continue
        raw = float(D["P"][max(s.t - 1, 0), s.j]) if s.kind == "open" else float(D["P"][s.t, s.j])
        out.append({"i0": p[0], "r": np.array(p[1], float), "prio": float(p[2]), "w": float(p[3]), "j": int(s.j),
                    "price": raw, "side": int(s.side), "nights": float(max(len(p[1]) - 1, 0)), "ah": False,
                    "liq": float(np.nan_to_num(D["DV1"][s.t, s.j])), "fam": fam, "sym": str(D["cols"][s.j])})
    return out


def pick_items(name: str, v26_name: bool, years: set, risk: float, cap: float, account: float, spread: float,
               fee: float, delay: int = 0) -> list[dict]:
    """Sized trade items of one pick in the given years (a v28 name, or a v26 name with v26's own grid)."""
    D, table = R14._G["D"], R16._W["table"]
    keep = core.ACCOUNT
    core.ACCOUNT = account
    fam = R14.family_of(name.split("|")[0])
    v19.set_costs("r4", R22.SLIP, R22.R4)
    try:
        if v26_name:
            kind_e, cfg = _v26_cfg(name)
            kind, key = "shield", name.rsplit("|", 1)[0]
        else:
            k, ci = name.rsplit("|", 1)
            kind, cfgs = R28.registry()[k]
            cfg = cfgs[int(ci)]
            key = k[2:] if kind == "shield" else k
        dates = D["dates"]

        def in_years(t: pd.DataFrame) -> pd.DataFrame:
            return t[pd.to_datetime(t["date"]).dt.year.isin(years)] if len(t) else t
        if kind == "shield":
            R28._TARGET["v"] = cfg.get("target", "none")
            sh.set_params({k2: cfg[k2] for k2 in ("hold", "stop", "ext", "rally", "scale")})
            ekind, g, data = R26.entries(key, cfg["entry"])
            if ekind == "intra":
                args = data if delay == 0 else [x for a in data if (x := R26._delayed(a, delay)) is not None]
                tr = R26._keep_rows(pd.DataFrame([sh.intra_row(D, *a) for a in args], columns=v19.COLS), cfg["filt"])
                return _rows_items(in_years(tr), table, risk, cap, account, spread, fee, fam)
            specs = [s for s in R26._keep_specs(data, cfg["filt"]) if dates[s.t].year in years]
            return _spec_items(D, specs, table, risk, cap, account, spread, fee, fam)
        if kind in ("event", "long"):
            specs = v28.event_specs(D, key, cfg) if kind == "event" else v28.long_specs(D, key, cfg)
            specs = [s for s in specs if dates[s.t].year in years]
            if kind == "event":
                sh.set_params({"hold": cfg["hold"], "stop": cfg["stop"], "ext": cfg["ext"], "rally": "none",
                               "scale": "all"})
            return _spec_items(D, specs, table, risk, cap, account, spread, fee, fam)
        if kind in ("pm", "ah"):
            tr = R28._ext_trades(kind, D, cfg)
            sh.set_params(None)
            return _rows_items(in_years(tr), table, risk, cap, account, spread, fee, fam)
        return []  # factor books and ETF pairs are added as streams (stream_members)
    finally:
        core.ACCOUNT = keep
        sh.set_params(None)
        R28._TARGET["v"] = "none"
        v19.set_costs("r4", R22.SLIP, R22.R4)


def members(book: str) -> list[tuple[int, str, str, bool]]:
    """(year, family, pick, v26 name?) of a book's members: COMBO28 from the v28 report, COMBO26 from v26's."""
    if book == "A26":
        summ = json.loads((DATA / "v26_summary.json").read_text(encoding="utf-8"))
        v26n = True
    else:
        summ = json.loads((Path(ARGS.report) / "summary.json").read_text(encoding="utf-8"))
        v26n = False
    out = []
    for y, fams in summ["members"].items():
        for fam in fams:
            nm = summ["families"][fam]["picks"].get(str(y))
            if nm:
                out.append((int(y), fam, nm, v26n))
    return out


def book_items(book: str, risk: float, cap: float, account: float, spread: float, fee: float, delay: int = 0
               ) -> tuple[list[dict], dict]:
    items, streams = [], {}
    for y, fam, nm, v26n in members(book):
        kind = "shield" if v26n else R28.registry()[nm.rsplit("|", 1)[0]][0]
        if kind in ("factor", "lev"):
            k, ci = nm.rsplit("|", 1)
            s = R22.evaluate(k, int(ci))[0]["mid"]
            streams.setdefault(fam, []).append(s[s.index.year == y])
            continue
        items += pick_items(nm, v26n, {y}, risk, cap, account, spread, fee, delay)
    return items, {f: pd.concat(v) for f, v in streams.items()}


# ---------------------------------------------------------------- the joint book

def joint(items: list[dict], dates: pd.DatetimeIndex, gross_cap: float, max_open: int = 20, max_new: int = 99,
          order: str = "time", sector: str = "none", rule: str = "tzi", locate: float = BASE_LOCATE,
          preborrow: float = 0.0, streams: dict | None = None) -> tuple[pd.Series, list[dict]]:
    """One account: one position a symbol, at most ``max_open`` open and ``max_new`` new a session, gross notional at
    most ``gross_cap``, the margin of the open positions at most the equity, at most two open a SIC code ('sic2')."""
    T = len(dates)
    out, gross, req = np.zeros(T), np.zeros(T), np.zeros(T)
    sq = v28.X.get("sq_p")
    sic = v28.X.get("sic")

    def okey(it: dict) -> tuple:
        if order == "move":
            return (it["i0"], -abs(it["prio"]))
        if order == "liquid":
            return (it["i0"], -it["liq"])
        if order == "risk":
            p = float(sq[it["i0"], it["j"]]) if sq is not None and it["j"] >= 0 else np.nan
            return (it["i0"], p if np.isfinite(p) else 9.0)
        return (it["i0"], -it["prio"])
    n_new = np.zeros(T, int)
    open_: list[tuple[int, int, str]] = []
    until: dict[int, int] = {}
    taken = []
    stream_w = 0.0
    if streams:
        stream_w = min(0.2, 1.0 / max(len(streams), 1))
        for s in streams.values():
            x = s.reindex(dates).fillna(0.0).to_numpy()
            out += stream_w * x
            gross += stream_w
            req += stream_w * 0.5
    for it in sorted(items, key=okey):
        i0, r, w = it["i0"], it["r"], it["w"]
        n = min(len(r), T - i0)
        if n <= 0 or w <= 0:
            continue
        open_ = [x for x in open_ if x[0] >= i0]
        j = it["j"]
        if j >= 0 and until.get(j, -1) >= i0:
            continue
        if len(open_) >= max_open or n_new[i0] >= max_new:
            continue
        code = str(sic[j])[:4] if sic is not None and j >= 0 else ""
        if sector == "sic2" and code and sum(1 for x in open_ if x[2] == code) >= 2:
            continue
        side = np.array([it["side"]])
        m_day = np.full(n, margin(np.array([it["price"]]), side, rule, "night")[0])
        m_day[-1] = margin(np.array([it["price"]]), side, rule, "intra")[0]
        if n > 1 or it["nights"] > 0:
            m_day[:max(n - 1, 1)] = np.maximum(m_day[:max(n - 1, 1)],
                                               margin(np.array([it["price"]]), side, rule, "night")[0])
        if it["ah"]:
            m_day[0] = max(m_day[0], margin(np.array([it["price"]]), side, rule, "ah")[0])
        if gross[i0:i0 + n].max() + w > gross_cap + 1e-9 or (rule != "none"
                                                              and (req[i0:i0 + n] + w * m_day).max() > 1.0 + 1e-9):
            continue
        rr = np.array(r[:n], float)
        if it["side"] < 0:
            rr[0] -= locate
            rr -= preborrow * it["nights"] / n
        out[i0:i0 + n] += w * rr
        gross[i0:i0 + n] += w
        req[i0:i0 + n] += w * m_day
        n_new[i0] += 1
        open_.append((i0 + n - 1, j, code))
        until[j] = i0 + n - 1
        taken.append({**it, "net": float(np.sum(rr)), "contrib": float(w * np.sum(rr)), "date": str(dates[i0].date())})
    return pd.Series(out, index=dates), taken


def _row(s: pd.Series, idx: np.ndarray, cash: pd.Series, **kw) -> dict:
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    return {**kw, "simple": float(s.clip(lower=-1.0).sum() / yrs), **S.stats(s, cash), **S.bootstrap(s.to_numpy(), idx)}


def _window(D: dict) -> tuple[pd.Timestamp, pd.Timestamp, pd.DatetimeIndex]:
    a, b = pd.Timestamp("2018-01-01"), core.last_day()
    return a, b, D["dates"][(D["dates"] >= a) & (D["dates"] <= b)]


CELLS = [(bk, r, c) for bk in ("A28", "A26") for r in RISKS for c in CAPS]


def cmd_core(args) -> int:
    R22.R19.load(args.inputs)
    D = R14._G["D"]
    a, b, cal = _window(D)
    idx = S.draws(len(cal), seed=28)
    rows = []
    for k, (bk, risk, cap) in enumerate(CELLS):
        if k % args.shards != args.shard:
            continue
        for cname, spread, fee in (("mid", 1.0, 1.0), ("high", 2.0, 3.0)):
            items, streams = book_items(bk, risk, cap, 100_000.0, spread, fee)
            for g in GROSS:
                for mo in MAX_OPEN:
                    for mn in MAX_NEW:
                        for od in ORDERS:
                            for sc in SECTOR:
                                s = joint(items, D["dates"], g, mo, mn, od, sc, "tzi", BASE_LOCATE, 0.0,
                                          streams)[0].loc[a:b]
                                rows.append(_row(s, idx, D["cash"], book=bk, risk=risk, cap=cap, gross=g, max_open=mo,
                                                 max_new=mn, order=od, sector=sc, costs=cname))
            print(f"{bk} risk {risk} cap {cap} {cname}: {len(items)} items", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"core_{args.shard:02d}.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    return 0


def choice(df: pd.DataFrame, bk: str) -> pd.Series | None:
    ok = df[(df["book"] == bk) & (df["costs"] == "mid") & (df["gross"] <= 2.0) & (df["p_dd75"] <= 0.01)]
    return ok.sort_values("cagr_med", ascending=False).iloc[0] if len(ok) else None


def _flags(D: dict, it: dict) -> dict:
    """The worst trades' checks: a split factor change while held, an open through a +50% gap during the hold."""
    j, i0, n = it["j"], it["i0"], len(it["r"])
    F = np.asarray(D["F"], float)
    seg = F[i0:i0 + n, j] if j >= 0 else np.array([])
    split = bool(len(seg) > 1 and np.nanmax(seg) / max(np.nanmin(seg), 1e-12) > 1.01)
    O, C = np.asarray(D["O"], float), np.asarray(D["C"], float)
    gap = bool(j >= 0 and any(np.isfinite(O[u, j]) and np.isfinite(C[u - 1, j]) and O[u, j] >= 1.5 * C[u - 1, j]
                              for u in range(max(i0 + 1, 1), min(i0 + n, len(D["dates"])))))
    return {"split_in_hold": split, "gap_through": gap}


def cmd_sens(args) -> int:
    R22.R19.load(args.inputs)
    D = R14._G["D"]
    a, b, cal = _window(D)
    idx = S.draws(len(cal), seed=28)
    core_rows = [r for p in sorted(args.core.rglob("core_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    df = pd.DataFrame(core_rows)
    out: dict = {"choice": {}, "battery": [], "worst": {}, "segments": {}}
    for bk in ("A28", "A26"):
        p = choice(df, bk) if len(df) else None
        if p is None:
            out["choice"][bk] = None
            continue
        c = {k: (p[k].item() if hasattr(p[k], "item") else p[k]) for k in ("risk", "cap", "gross", "max_open",
                                                                             "max_new", "order", "sector")}
        out["choice"][bk] = {**c, **{k: float(p[k]) for k in ("sortino", "cagr", "simple", "dd", "p_dd75",
                                                               "cagr_med", "worst_day")}}

        def run(rule="tzi", locate=BASE_LOCATE, pre=0.0, spread=1.0, fee=1.0, delay=0, account=100_000.0,
                c=c, bk=bk) -> tuple[pd.Series, list]:
            items, streams = book_items(bk, c["risk"], c["cap"], account, spread, fee, delay)
            return joint(items, D["dates"], c["gross"], c["max_open"], c["max_new"], c["order"], c["sector"], rule,
                         locate, pre, streams)
        base, taken = run()
        changes: list[tuple[str, dict]] = [(f"margin_{m}", {"rule": m}) for m in ("none", "tzi", "tzus")]
        changes += [(f"locate_{x}", {"locate": x}) for x in LOCATE]
        changes += [(f"preborrow_{x}", {"pre": x}) for x in PREBORROW]
        changes += [(f"spread_{x}", {"spread": x}) for x in SPREADS] + [("high", {"spread": 2.0, "fee": 3.0})]
        changes += [(f"delay_{x}", {"delay": x}) for x in DELAYS]
        changes += [(f"account_{int(x)}", {"account": x}) for x in ACCOUNTS]
        for nm, kw in changes:
            s = run(**kw)[0].loc[a:b]
            out["battery"].append(_row(s, idx, D["cash"], book=bk, change=nm))
            print(bk, nm, round(out["battery"][-1]["sortino"], 2), flush=True)
        s = base.loc[a:b]
        seg = {}
        for y in sorted(set(s.index.year)):
            seg[f"without_{y}"] = S.stats(s[s.index.year != y], D["cash"])
        for nm, lo, hi in (("before_T1", a, T1), ("after_T1", T1, b), ("before_nasdaq2025", a, NASDAQ),
                           ("after_nasdaq2025", NASDAQ, b)):
            seg[nm] = S.stats(s.loc[lo:hi], D["cash"])
        out["segments"][bk] = seg
        worst = sorted(taken, key=lambda it: it["net"])[:50]
        out["worst"][bk] = [{"date": it["date"], "sym": it["sym"], "fam": it["fam"], "net": it["net"],
                             "contrib": it["contrib"], "price": it["price"], "w": it["w"], **_flags(D, it)}
                            for it in worst]
        args.out.mkdir(parents=True, exist_ok=True)
        base.loc[a:b].astype(np.float32).to_frame(bk).to_parquet(args.out / f"stream_{bk}.parquet")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sens.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- symbol halves

_HALF_ON: dict = {"h": None}
_orig_intra, _orig_daily = v19.intra_book, v19.daily_book


def _intra_half(trades, dates, table, spread, fee_mult=1.0, gross=False):
    h = _HALF_ON["h"]
    if h is not None and len(trades):
        trades = trades[trades["symbol"].astype(str).map(half_of) == h]
    return _orig_intra(trades, dates, table, spread, fee_mult, gross)


def _daily_half(D, specs, table, spread, fee_mult=1.0, gross=False):
    h = _HALF_ON["h"]
    if h is not None:
        specs = [s for s in specs if half_of(D["cols"][s.j]) == h]
    return _orig_daily(D, specs, table, spread, fee_mult, gross)


def cmd_halves(args) -> int:
    summ = json.loads((args.report / "summary.json").read_text(encoding="utf-8"))
    fams = sorted(f for f, i in summ["families"].items() if i["picks"])
    mine = fams[args.shard::args.shards]
    if not mine:
        return 0
    R22.R19.load(args.inputs)
    v19.intra_book, v19.daily_book = _intra_half, _daily_half
    D = R14._G["D"]
    a, b, cal = _window(D)
    out = {}
    for fam in mine:
        picks = {int(y): n for y, n in summ["families"][fam]["picks"].items()}
        res = {}
        for h in (0, 1):
            _HALF_ON["h"] = h
            parts = []
            for y, nm in sorted(picks.items()):
                k, ci = nm.rsplit("|", 1)
                if R28.registry()[k][0] in ("factor", "lev"):
                    continue
                s = R22.evaluate(k, int(ci))[0]["mid"]
                parts.append(s.loc[pd.Timestamp(f"{y}-01-01"):min(b, pd.Timestamp(f"{y}-12-31"))])
            _HALF_ON["h"] = None
            if parts:
                st = R14._stats(pd.concat(parts).reindex(cal).fillna(0.0), D["cash"], str(a.date()), str(b.date()))
                res[f"h{h}"] = st
        out[fam] = res
        print(fam, {k: (v or {}).get("sortino") for k, v in res.items()}, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"halves_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- AFTER.md

def _f(x, pct: bool = False) -> str:
    if not isinstance(x, (int, float)) or not np.isfinite(x):
        return "-"
    return f"{x:.1%}" if pct else f"{x:.2f}"


def cmd_final(args) -> int:
    sens = json.loads((args.sens / "sens.json").read_text(encoding="utf-8")) if (args.sens / "sens.json").exists() \
        else {"choice": {}, "battery": [], "worst": {}, "segments": {}}
    halves: dict = {}
    for p in sorted(args.halves.rglob("halves_*.json")):
        halves.update(json.loads(p.read_text(encoding="utf-8")))
    summ = json.loads((args.report / "summary.json").read_text(encoding="utf-8"))
    L = ["# v28 after the report: one account under TradeZero's margin, construction, battery, symbol halves", "",
         "Walk-forward 2018-2026, $100k unless stated, middle costs, TradeZero International's margin by price and a "
         "0.5% locate cost a short unless stated. p75: the chance of a 75% drawdown in ten years (block bootstrap). "
         "The choice: the owner's rule (p75 <= 1%, gross <= 2x, the highest median bootstrap CAGR).", "",
         "## 1. The choice", "", "| book | risk | cap | gross | max open | new a day | order | sector | Sortino | CAGR | "
         "a year on the start | max DD | worst day | p75 | median CAGR |", "|" + "---|" * 15]
    for bk, c in sens["choice"].items():
        if not c:
            L.append(f"| {bk} | no book meets the rule |" + " |" * 13)
            continue
        L.append(f"| {bk} | {c['risk']:.2%} | {c['cap']:.0%} | {c['gross']:g} | {c['max_open']} | {c['max_new']} | "
                 f"{c['order']} | {c['sector']} | {_f(c['sortino'])} | {_f(c['cagr'], True)} | {_f(c['simple'], True)} | "
                 f"{_f(c['dd'], True)} | {_f(c['worst_day'], True)} | {c['p_dd75']:.1%} | {_f(c['cagr_med'], True)} |")
    L += ["", "## 2. Battery around the choice", "", "| book | change | Sortino | CAGR | a year on the start | max DD | "
          "worst day | p75 | ruined |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sens["battery"]:
        L.append(f"| {r['book']} | {r['change']} | {_f(r['sortino'])} | {_f(r['cagr'], True)} | "
                 f"{_f(r['simple'], True)} | {_f(r['dd'], True)} | {_f(r['worst_day'], True)} | {r['p_dd75']:.1%} | "
                 f"{'yes' if r['ruined'] else 'no'} |")
    L += ["", "## 3. Segments of the chosen book", "", "| book | segment | Sortino | CAGR | max DD |", "|---|---|---|---|---|"]
    for bk, seg in sens["segments"].items():
        for nm, st in seg.items():
            L.append(f"| {bk} | {nm} | {_f((st or {}).get('sortino'))} | {_f((st or {}).get('cagr'), True)} | "
                     f"{_f((st or {}).get('dd'), True)} |")
    L += ["", "## 4. The 20 worst trades of each chosen book", "", "| book | date | family | net | of the account | "
          "price | split while held | gap through |", "|---|---|---|---|---|---|---|---|"]
    for bk, ws in sens["worst"].items():
        for w in ws[:20]:
            L.append(f"| {bk} | {w['date']} | {w['fam']} | {w['net']:.0%} | {w['contrib']:.1%} | {w['price']:.2f} | "
                     f"{w['split_in_hold']} | {w['gap_through']} |")
    L += ["", "## 5. Symbol halves (the same picks on each half of the tickers)", "",
          "| family | WF Sortino all | half 0 | half 1 | CAGR half 0 | half 1 |", "|---|---|---|---|---|---|"]
    for fam, res in sorted(halves.items()):
        allw = (summ["families"].get(fam, {}).get("wf") or {}).get("sortino")
        h0, h1 = res.get("h0") or {}, res.get("h1") or {}
        L.append(f"| {fam} | {_f(allw)} | {_f(h0.get('sortino'))} | {_f(h1.get('sortino'))} | "
                 f"{_f(h0.get('cagr'), True)} | {_f(h1.get('cagr'), True)} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "AFTER.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "after_summary.json").write_text(json.dumps({"sens": sens, "halves": halves}, indent=1, default=float),
                                                 encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


ARGS = argparse.Namespace(report="outputs/v28w/report")


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("core", "halves"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, required=True)
        s.add_argument("--shards", type=int, required=True)
    s = sub.add_parser("sens")
    s.add_argument("--core", type=Path, required=True)
    f = sub.add_parser("final")
    f.add_argument("--sens", type=Path, required=True)
    f.add_argument("--halves", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    ARGS = args
    return {"core": cmd_core, "sens": cmd_sens, "halves": cmd_halves, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v28_after"
    raise SystemExit(main())
