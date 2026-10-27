"""v44 part M: the book's trades on v43's minute engine (central realism case) with meta-label filters, entry
triggers, execution, emergency exits, the locate rule and a partial cover (V44_PREREGISTRATION.md section 1).

  run    one shard of the units (a replay combination: trigger x execution x emergency exit x locate x partial, or a
         chunk of the filter pairs), each through its filters at the four cost sets: each year's log growth and worst
         drawdown at the $10,000 level
  final  the walk-forward choice, the bootstrap, the symbol halves, V44M_REPORT.md and the picks for part C
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing as mp
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v44_new1m as v44
from aurora.research import v44_stats as st


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R43 = _script("run_v43")
DV = _script("run_v44_data")
R40, R35, R33, R32, R29, A = R43.R40, R43.R35, R43.R33, R43.R32, R43.R29, R43.A
OPEN, LAST, LEVEL, TASKS = R43.OPEN, R43.LAST, R43.LEVEL, R43.TASKS
QUICK = R29.QUICK
FILL, PART, LIQ, EFILL = "next_open", 0.10, "next_vwap", "auction"  # v43's central case

FEATS = ("dv_ratio", "pm_range", "gap", "to_vwap", "to_high", "bvc30", "trade_size", "rotation", "rv30", "vr60",
         "kalman", "bocpd15", "zscore", "news24", "offering24", "filing7", "hot_ratio", "iwm", "btc24", "spy_vwap",
         "lr30", "sweep", "oddlot", "block", "spread10", "depth10")
MODELS = ("lr", "gb")
ACTS = ("p40", "p50", "size")
FILTERS: list = ["none"] + [("terc", f, s) for f in range(len(FEATS)) for s in ("top", "bottom")] + \
    [("model", mdl, a) for mdl in MODELS for a in ACTS]
PAIRS = [((f1, s1), (f2, s2)) for f1, f2 in combinations(range(len(FEATS)), 2) for s1 in ("top", "bottom")
         for s2 in ("top", "bottom")]
TRIG_KINDS = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8")
TRIGS: list = ["none"] + [(k, w, to) for k in TRIG_KINDS for w in (15, 30, 60, 120) for to in ("skip", "deadline")]
EXES = ("auction", "twap3", "twap5", "passive")
XEXITS: list = ["none", ("X1", 0.6), ("X1", 0.7), ("X2", 30), ("X2", 90), ("X3", 1.0), ("X3", 2.0), ("X4", 5.0),
                ("X4", 10.0), ("X5", 0.05), ("X5", 0.10), ("X6", 3.0), ("X6", 4.0)]
LOCS = ("as now", "HOT flat 15:55", "HOT and HTB flat 15:55")
PARTIALS = (False, True)
RSH = (len(TRIGS), len(EXES), len(XEXITS), len(LOCS), len(PARTIALS))
NR = int(np.prod(RSH))
MSHAPE = (len(FILTERS),) + RSH
NB = int(np.prod(MSHAPE))
NLP = len(LOCS) * len(PARTIALS)
NPB = len(PAIRS) * NLP
NBOOK = NB + NPB
NCH = -(-len(PAIRS) // len(FILTERS))
NUNIT = NR + NLP * NCH
BASE = 0  # (none, none, auction, none, as now, as now)
GAIN, MAX_RUIN, E2K = 1.15, 0.025, 2_000.0
XCP = 0.5  # a BOCPD change point: probability >= 0.5 that the run began within the last five bars

_G: dict = {"sf": {}, "flt": {}, "delay": {}, "half": {}}


def book_of(bid: int) -> tuple:
    """(filter or pair, trigger, execution, emergency exit, locate, partial) indices; a pair as ('pair', index)."""
    if bid < NB:
        return tuple(int(x) for x in np.unravel_index(bid, MSHAPE))
    q, lp = divmod(bid - NB, NLP)
    lo, pa = divmod(lp, len(PARTIALS))
    return ("pair", q), 0, 0, 0, lo, pa


def _filter_name(f) -> str:
    if isinstance(f, tuple) and f[0] == "pair":
        (a, sa), (b, sb) = PAIRS[f[1]]
        return f"skip {FEATS[a]} {sa} and {FEATS[b]} {sb}"
    x = FILTERS[f]
    if x == "none":
        return "none"
    if x[0] == "terc":
        return f"skip {FEATS[x[1]]} {x[2]} tercile"
    return f"{x[1]} {'size x(0.5+p)' if x[2] == 'size' else f'skip p<0.{x[2][1:]}'}"


def book_name(bid: int) -> str:
    f, tr, ex, xx, lo, pa = book_of(bid)
    t = TRIGS[tr]
    tname = "none" if t == "none" else f"{t[0]} within {t[1]}m, {t[2]}"
    x = XEXITS[xx]
    xname = "none" if x == "none" else f"{x[0]} {x[1]:g}"
    return (f"filter {_filter_name(f)}; trigger {tname}; {EXES[ex]}; exit {xname}; locate {LOCS[lo]}; "
            f"partial {'half at the first close' if PARTIALS[pa] else 'none'}")


def half_of(sym) -> int:
    return int(hashlib.sha256(str(sym).encode()).hexdigest()[:8], 16) % 2  # v28's symbol halves


def _key(it: dict) -> tuple:
    return int(it["t"]), int(it["j"]), float(it["prio"])


# ---------------------------------------------------------------- session statistics (triggers, emergency exits)

def session_feats(B: dict) -> dict | None:
    """The regular session's statistics on its bars (``idx``: their steps), each from the bars up to it."""
    idx = np.flatnonzero(np.isfinite(B["o"][OPEN:LAST + 1])) + OPEN
    if len(idx) < 10:
        return None
    o, h, lo, c, v, vw = (np.asarray(B[k][idx], float) for k in ("o", "h", "l", "c", "v", "vw"))
    v = np.where(np.isfinite(v), v, 0.0)
    line = vi.vwap(c, v, vw)
    cp30, mu30 = st.bocpd(c, 1 / 30)
    cp90, mu90 = st.bocpd(c, 1 / 90)
    vel = st.alpha_beta(c, 0.01)
    with np.errstate(invalid="ignore", divide="ignore"):
        up5 = c / np.r_[np.full(5, np.nan), c[:-5]][: len(c)] - 1
        med = np.array([np.median(v[:k + 1]) for k in range(len(v))])
        vrel = np.where(med > 0, v / med, np.nan)
    out = {"o": o, "h": h, "lo": lo, "c": c, "line": line, "bvc5": st.bvc_imbalance(o, c, v, 5), "up5": up5,
           "cp30": cp30, "mu30": mu30, "cp90": cp90, "mu90": mu90, "vel": vel, "vsd": st._expanding_std(vel, 10),
           "vrel": vrel, "z": st.zscore(c, line, "sess"), "vr30": st.variance_ratio(c, 5, 30)}
    out = {k: np.asarray(x, np.float32) for k, x in out.items()}  # shared by the workers: kept small
    return {**out, "idx": idx.astype(np.int16), "newhi": h > np.r_[np.inf, np.maximum.accumulate(h)[:-1]]}


def _sf_job(key: tuple) -> tuple:
    B = R43.timeline(*key)
    return key, (session_feats(B) if B is not None else None)


def xmask_of(xx: int):
    """The emergency cover of XEXITS[xx] as replay's ``xmask`` (None: no emergency cover)."""
    if XEXITS[xx] == "none":
        return None
    kind, x = XEXITS[xx]

    def f(B: dict, u: int, j: int, e: float) -> np.ndarray:
        out = np.zeros(960, bool)
        F = _G["sf"].get((u, j))
        if F is None:
            return out
        with np.errstate(invalid="ignore"):
            if kind == "X1":
                m = (F["bvc5"] >= x) & (F["up5"] >= 0.05)
            elif kind == "X2":
                m = (F[f"cp{int(x)}"] >= XCP) & (F[f"mu{int(x)}"] > 0) & (F["c"] < e)
            elif kind == "X3":
                m = F["vel"] > x * F["vsd"]
            elif kind == "X4":
                m = (F["vrel"] >= x) & (F["c"] / F["o"] - 1 >= 0.03)
            elif kind == "X5":
                m = F["newhi"] & (F["h"] >= e * (1 + x))
            else:
                m = F["z"] >= x
        out[F["idx"]] = m
        return out

    return f


def trigger_steps(F: dict | None) -> np.ndarray:
    """The step of the first bar of each entry trigger T1-T8 (10,000: none), from the bars up to it."""
    out = np.full(len(TRIG_KINDS), 10_000)
    if F is None:
        return out
    idx, o, h, lo, c = F["idx"], F["o"], F["h"], F["lo"], F["c"]
    hod = np.r_[np.inf, np.maximum.accumulate(h)[:-1]]
    green = c > o
    run = np.zeros(len(c), int)
    for k in range(1, len(c)):
        run[k] = run[k - 1] + 1 if green[k - 1] else 0
    first5 = idx < OPEN + 5
    orl = lo[first5].min() if first5.any() else np.nan
    with np.errstate(invalid="ignore"):
        masks = (
            (h < hod) & (c < F["line"]),                      # T1 a lower high under VWAP after the session's high
            F["bvc5"] < 0,                                    # T2 5-bar flow imbalance below 0
            (c < o) & (run >= 3),                             # T3 the first red bar after 3 or more green
            (F["vel"] < 0) & (np.arange(len(c)) >= 1),        # T4 Kalman velocity below 0
            (F["cp30"] >= XCP) & (F["mu30"] < 0),             # T5 a change point with a lower mean
            (lo < orl) & ~first5,                             # T6 the 5-minute opening range low broken
            np.maximum.accumulate(F["z"] >= 2) & (c < o),     # T7 z-score 2 or more, then a red bar
            F["vr30"] < 0.8,                                  # T8 30-bar variance ratio under 0.8
        )
    for i, m in enumerate(masks):
        hit = np.flatnonzero(m)
        if len(hit):
            out[i] = int(idx[hit[0]])
    return out


def delay_of(steps: np.ndarray, tr: int) -> int | None:
    """The entry delay (minutes after 09:30, entry at the next bar's open) of trigger TRIGS[tr]; None: skipped."""
    if TRIGS[tr] == "none":
        return 0
    kind, w, to = TRIGS[tr]
    s = int(steps[TRIG_KINDS.index(kind)])
    if s <= OPEN + w - 1:
        return s + 1 - OPEN
    return None if to == "skip" else w


# ---------------------------------------------------------------- execution

def _at(o: np.ndarray, s: int, hi: int = LAST) -> int:
    k = np.flatnonzero(np.isfinite(o[s:hi + 1]))
    return int(k[0]) + s if len(k) else 10_000


def _half_spread(it: dict, kind: str, minute: int) -> float:
    """Half the quoted relative spread of the last five minutes to ``minute`` (from 04:00), else the tier's."""
    q = _G.get("ticks", {}).get((int(it["t"]), int(it["j"]), kind))
    if q is not None:
        sp = q["spread"].reindex(range(minute - 4, minute + 1)).dropna()
        if len(sp):
            return float(sp.iloc[-1]) / 2
    return float(core.half_spread(np.array([float(it["price"])]), "mid")[0])


def exe_of(ex: int):
    """EXES[ex] as replay's ``exe`` (None: the auction as now). TWAP: one entry at the last slice at the slices'
    average; passive: a sell limit at the ask from the bar before, filled when a bar's high trades above it within five
    minutes (at the better of its open and the limit), else at the open five minutes on."""
    name = EXES[ex]
    if name == "auction":
        return None

    def f(it: dict, m: dict, e: float, es: int):
        B = R43.timeline(int(it["t"]), int(it["j"]))
        if B is None:
            return e, es
        o, h, c = B["o"], B["h"], B["c"]
        close = m["kind"] != "open"
        if name.startswith("twap"):
            n = int(name[4:])
            if close:
                px = [o[s] for s in (_at(o, LAST + 1 - 5 * (n - i)) for i in range(1, n)) if s <= LAST] + [e]
                return float(np.mean(px)), es
            px, s = [], es
            for i in range(n):
                si = es if i == 0 else _at(o, es + 5 * i)
                if si > LAST:
                    break
                px.append(e if i == 0 else float(o[si]))
                s = si
            return float(np.mean(px)), s
        s0 = 950 if close else es
        before = np.flatnonzero(np.isfinite(c[:s0]))
        ref = float(c[before[-1]]) if len(before) else e
        lim = ref * (1 + _half_spread(it, m["kind"], s0 - 1 - R43.AH))
        for s in range(s0, min(s0 + 5, LAST + 1)):
            if np.isfinite(o[s]) and h[s] > lim:
                return float(max(o[s], lim)), (es if close else s)
        s = _at(o, s0 + 5)
        if s > LAST:
            return (e, es) if close else None
        return float(o[s]), (es if close else s)

    return f


# ---------------------------------------------------------------- features at the entry and the filters

def load_v44(folder: Path, D: dict) -> None:
    """News and filing events, SPY and IWM minutes, BTC closes and the tick aggregates (what is present)."""
    T = len(D["dates"])
    row = {pd.Timestamp(d): t for t, d in enumerate(D["dates"])}
    col = {str(c): j for j, c in enumerate(D["cols"])}
    _G["news"], _G["edgar"] = {}, {}
    if (folder / "news.parquet").exists():
        nw = pd.read_parquet(folder / "news.parquet")
        x = nw.assign(symbol=nw["symbols"].astype(str).str.split(",")).explode("symbol")
        x = x[x["symbol"].astype(bool)].reset_index(drop=True)
        when = pd.to_datetime(x["created_at"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
        ev = DV.session_events(D, x["symbol"], when)
        ev["code"] = x["headline"].map(v44.news_class).to_numpy()[ev.index]
        _G["news"] = v44.event_index(ev, "code")
    if (folder / "edgar.parquet").exists():
        ev = DV.edgar_events(D, pd.read_parquet(folder / "edgar.parquet"))
        ev["code"] = [v44.form_codes(f, i) for f, i in zip(ev["form"], ev["items"])]
        ev = ev.explode("code").dropna(subset=["code"]).astype({"code": int})
        _G["edgar"] = v44.event_index(ev, "code")
    if (folder / "index.parquet").exists():
        idx = pd.read_parquet(folder / "index.parquet")
        for sym in ("SPY", "IWM"):
            a = {k: np.full((T, 960), np.nan, np.float32) for k in ("c", "v", "vw")}
            for d, g in idx[idx["symbol"] == sym].groupby("date"):
                t = row.get(pd.Timestamp(d))
                if t is None:
                    continue
                mm = g["minute"].to_numpy(int)
                ok = (mm >= 0) & (mm < 960)
                for k in a:
                    a[k][t, mm[ok]] = g[k].to_numpy(float)[ok]
            _G[sym] = a
    if (folder / "btc.parquet").exists():
        b = pd.read_parquet(folder / "btc.parquet", columns=["ts", "c"])
        ts = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
        s = pd.Series(b["c"].to_numpy(float), index=ts.to_numpy()).sort_index()
        _G["btc"] = (s.index.to_numpy(), s.to_numpy())
    if (folder / "ticks.parquet").exists():
        tk = pd.read_parquet(folder / "ticks.parquet")
        out = {}
        for (d, sym, kind), g in tk.groupby(["date", "symbol", "kind"]):
            t, j = row.get(pd.Timestamp(d)), col.get(str(sym))
            if t is not None and j is not None:
                out[(t, j, str(kind))] = g.set_index("minute").sort_index()
        _G["ticks"] = out


def hot_ratio(D: dict) -> np.ndarray:
    """The day's count of small caps gapping 20% or more over its trailing 60-session median."""
    O, C, P1, DV1 = (np.asarray(D[k], float) for k in ("O", "C", "P1", "DV1"))
    ok = np.asarray(D["valid1"], bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = O[1:] / C[:-1] - 1
        small = ok[1:] & (P1[1:] >= 1) & (P1[1:] <= 20) & (DV1[1:] >= 5e5)
        n = np.r_[0.0, ((gap >= 0.2) & small).sum(axis=1)]
        med = pd.Series(n).shift(1).rolling(60, min_periods=40).median().to_numpy()
        return np.where(med > 0, n / med, np.nan)


def _count_events(ev: dict, t: int, j: int, minute: int, codes=None, sessions: int = 1) -> int:
    """Events in the ``sessions`` sessions before minute ``minute`` of session t (a pre event of t counts)."""
    n = 0
    for u in range(t - sessions, t + 1):
        a = ev.get((u, j))
        if a is None:
            continue
        mins, cs = a
        sel = np.ones(len(mins), bool) if codes is None else np.isin(cs, codes)
        if u == t:
            sel &= mins < max(minute, 0)
        elif sessions == 1:
            sel &= mins >= max(minute, 0)  # the session before: from the same clock minute on
        n += int(sel.sum())
    return n


def _btc_move(t: int, minute: int) -> float:
    if "btc" not in _G:
        return np.nan
    ts, c = _G["btc"]
    at = pd.Timestamp(_G["D"]["dates"][t]) + pd.Timedelta(minutes=570 + minute)
    now, ago = np.datetime64(at), np.datetime64(at - pd.Timedelta(days=1))
    a, b = int(np.searchsorted(ts, now, side="right")) - 1, int(np.searchsorted(ts, ago, side="right")) - 1
    if a < 0 or b < 0 or now - ts[a] > np.timedelta64(30, "m"):
        return np.nan
    return float(c[a] / c[b] - 1)


def trade_features(it: dict, kind: str) -> np.ndarray:
    """The 26 features of a trade at its entry: open entries from the premarket bars (04:00-09:29) and the days before,
    close entries from the session's bars to 15:49."""
    D = _G["D"]
    t, j = int(it["t"]), int(it["j"])
    f = np.full(len(FEATS), np.nan)
    pc = float(D["C"][t - 1, j]) if t > 0 else np.nan
    lo_s, hi_s = (R43.AH, OPEN - 1) if kind == "open" else (OPEN, 949)
    minute = -1 if kind == "open" else 950 - OPEN  # the entry decision's minute after 09:30 (15:50)
    B = R43.timeline(t, j)
    if B is not None:
        sl = slice(lo_s, hi_s + 1)
        ok = np.isfinite(B["o"][sl])
        o, h, lo, c, v, vw = (np.asarray(B[k][sl], float)[ok] for k in ("o", "h", "l", "c", "v", "vw"))
        v = np.where(np.isfinite(v), v, 0.0)
        if len(c):
            fac = float(D["F"][t, j]) if np.isfinite(D["F"][t, j]) and D["F"][t, j] > 0 else 1.0
            line = vi.vwap(c, v, vw)
            f[0] = float((v * c / fac).sum()) / float(D["DV1"][t, j]) if D["DV1"][t, j] > 0 else np.nan
            f[1] = (h.max() - lo.min()) / pc
            f[2] = c[-1] / pc - 1
            f[3] = c[-1] / line[-1] - 1
            f[4] = c[-1] / h.max() - 1
            f[5] = st.bvc_imbalance(o, c, v, 30)[-1] if len(c) >= 30 else np.nan
            so = float(it.get("so", np.nan))
            f[7] = v.sum() / so if so > 0 else np.nan
            if len(c) >= 31:
                lr = np.diff(np.log(c[-31:]))
                f[8] = float(lr.std(ddof=1))
            if len(c) >= 61:
                f[9] = st.variance_ratio(c, 5, 60)[-1]
            f[10] = st.alpha_beta(c, 0.01)[-1]
            if len(c) >= 15:
                f[11] = float(st.bocpd(c, 1 / 60)[0][-15:].max())
            f[12] = st.zscore(c, line, "sess")[-1]
    f[13] = _count_events(_G.get("news", {}), t, j, minute)
    f[14] = float(_count_events(_G.get("news", {}), t, j, minute, [v44.NEWS_CLASSES.index(k) for k in
                                                                    ("priced", "offering", "rsplit")]) > 0)
    f[15] = float(_count_events(_G.get("edgar", {}), t, j, minute, [v44.FORMS.index(k) for k in ("424B", "S1", "S3")],
                                sessions=5) > 0)
    hr = _G.get("hot_ratio")
    if hr is not None:
        f[16] = hr[t - 1] if kind == "open" else hr[t]  # the day's gaps are known only at its open
    step = hi_s - R43.AH  # the index minute (from 04:00) of the last bar before the decision
    if "IWM" in _G and t > 0:
        f[17] = _G["IWM"]["c"][t, step] / _G["IWM"]["c"][t - 1, 719] - 1
    f[18] = _btc_move(t, minute)
    if "SPY" in _G:
        a = _G["SPY"]
        w = slice(0, step + 1) if kind == "open" else slice(OPEN - R43.AH, step + 1)
        cv, vv, ww = (np.asarray(a[k][t, w], float) for k in ("c", "v", "vw"))
        okk = np.isfinite(cv) & np.isfinite(vv)
        if okk.any():
            line = vi.vwap(cv[okk], vv[okk], ww[okk])
            f[19] = float(cv[okk][-1] > line[-1])
    q = _G.get("ticks", {}).get((t, j, kind))
    if q is not None:
        last30 = q.loc[step - 29: step]
        so_far = q.loc[: step]
        vol = (last30["vb"] + last30["vs"]).sum()
        n30, n_all = last30["n"].sum(), so_far["n"].sum()
        if n30 > 0 and n_all > 0 and vol > 0:
            f[6] = (vol / n30) / ((so_far["vb"] + so_far["vs"]).sum() / n_all)
            f[20] = (last30["vb"].sum() - last30["vs"].sum()) / vol
            f[21], f[22], f[23] = (last30[k].sum() / vol for k in ("viso", "vodd", "vblk"))
        last10 = q.loc[step - 9: step]
        f[24], f[25] = last10["spread"].mean(), last10["dimb"].mean()
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(f), f, np.nan)


def fit_filters(keys: list[tuple], years: np.ndarray, X: np.ndarray, y: np.ndarray) -> dict:
    """Per trade: the 52 tercile flags (cuts from the trades of the years before; none in the first year) and the
    two models' probability of a net gain (trained on the years before; nan in the first year)."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    out = {k: {"skip": np.zeros(2 * len(FEATS), bool), "p": np.full(len(MODELS), np.nan)} for k in keys}
    for Y in sorted(set(int(v) for v in years))[1:]:
        tr, te = years < Y, np.flatnonzero(years == Y)
        if tr.sum() < 30 or not len(te):
            continue
        cuts = np.nanquantile(np.where(tr[:, None], X, np.nan), [1 / 3, 2 / 3], axis=0)
        enough = np.isfinite(X[tr]).sum(axis=0) >= 30
        with np.errstate(invalid="ignore"):
            top = (X[te] >= cuts[1]) & enough
            bot = (X[te] <= cuts[0]) & enough
        med = np.nanmedian(X[tr], axis=0)
        med = np.where(np.isfinite(med), med, 0.0)
        Xtr = np.where(np.isfinite(X[tr]), X[tr], med)
        Xte = np.where(np.isfinite(X[te]), X[te], med)
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        p = np.full((len(te), len(MODELS)), np.nan)
        if len(set(y[tr])) == 2:
            lr = LogisticRegression(max_iter=2000).fit((Xtr - mu) / sd, y[tr])
            p[:, 0] = lr.predict_proba((Xte - mu) / sd)[:, 1]
            gb = GradientBoostingClassifier(max_depth=3, n_estimators=100, random_state=44).fit(Xtr, y[tr])
            p[:, 1] = gb.predict_proba(Xte)[:, 1]
        for r, i in enumerate(te):
            z = out[keys[i]]
            z["skip"][0::2], z["skip"][1::2] = top[r], bot[r]
            z["p"] = p[r]
    return out


def filtered(items: list[dict], flt) -> list[dict]:
    """The items a filter (an index into FILTERS, or ('pair', index)) keeps, with the model sizes."""
    if not isinstance(flt, tuple) and FILTERS[flt] == "none":
        return items
    out = []
    for it in items:
        z = _G["flt"].get(_key(it))
        if z is None:
            out.append(it)
            continue
        if isinstance(flt, tuple):
            (a, sa), (b, sb) = PAIRS[flt[1]]
            if z["skip"][2 * a + (sa == "bottom")] and z["skip"][2 * b + (sb == "bottom")]:
                continue
        elif FILTERS[flt][0] == "terc":
            _, fi, side = FILTERS[flt]
            if z["skip"][2 * fi + (side == "bottom")]:
                continue
        else:
            _, mdl, act = FILTERS[flt]
            p = float(z["p"][MODELS.index(mdl)])
            if np.isfinite(p):
                if act == "size":
                    it = {**it, "w": float(it["w"]) * (0.5 + p)}
                elif p < (0.4 if act == "p40" else 0.5):
                    continue
        out.append(it)
    return out


# ---------------------------------------------------------------- the account

def items_for(its: list[dict], metas: list[dict], tr: int, ex: int, xx: int, lo: int, pa: int,
              half: int | None = None) -> tuple[list[dict], list[dict]]:
    """v43's items_for with the per-trade entry delay of the trigger, the locate's flat time and the hooks."""
    out, recs = [], []
    exe, xm = exe_of(ex), xmask_of(xx)
    for it, m in zip(its, metas):
        if half is not None and half_of(it["sym"]) != half:
            continue
        delay: int | None = 0
        if m["kind"] == "open" and TRIGS[tr] != "none":
            delay = _G["delay"].get((int(it["t"]), int(it["j"])), {}).get(tr, 0)
            if delay is None:
                continue
        tier = int(it.get("tier", 1))
        flat = 955 if (lo == 1 and tier == 2) or (lo == 2 and tier >= 1) else "hold"
        rec = R43.replay(it, m, (delay, 1.0, flat, None, None, 1.0), FILL, PART, EFILL, exe=exe, xmask=xm,
                         half=PARTIALS[pa])
        if rec is None:
            continue
        c0 = float(it["raw0"]) - float(it["r"][0])
        r = np.array(rec["g"], float)
        r[0] -= c0
        rec["cost"] = c0 + float(it.get("loc", 0.0))
        recs.append(rec)
        out.append({**it, "r": r, "raw0": rec["g"][0], "i0": rec["u"][0], "nights": rec["nights"],
                    "_rec": len(recs) - 1})
    return out, recs


def account(items: list[dict], recs: list[dict]) -> np.ndarray:
    D = _G["D"]
    _, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, R33.MAX_NEW, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return R43.liquidate(taken, recs, len(D["dates"]), LIQ, PART)


def book_returns(bid: int, level: float, task: str, half: int | None = None) -> np.ndarray:
    f, tr, ex, xx, lo, pa = book_of(bid)
    R43.LEVEL = level
    its, metas = R43._G["its"][(float(level), task)]
    items, recs = items_for(its, metas, tr, ex, xx, lo, pa, half)
    return account(filtered(items, f), recs)


# ---------------------------------------------------------------- setup and the stages

def setup(args, levels=(LEVEL,), procs: int = 1) -> None:
    R43.setup(args, levels)
    D = R43._G["D"]
    _G["D"] = D
    load_v44(args.v44, D)
    _G["hot_ratio"] = hot_ratio(D) if all(k in D for k in ("P1", "valid1")) else None
    keys = [k for k, b in R43._G["tl"].items() if b is not None]
    t0 = time.time()
    with mp.get_context("fork").Pool(procs) as pool:
        _G["sf"] = dict(pool.map(_sf_job, keys, chunksize=16))
    its, metas = R43._G["its"][(LEVEL, "base")]
    seen: dict = {}
    for lv in levels:
        for task in TASKS:
            for it, m in zip(*R43._G["its"][(float(lv), task)]):
                seen.setdefault(_key(it), (it, m["kind"]))
    for (t, j, _), (it, kind) in seen.items():
        if kind == "open" and (t, j) not in _G["delay"]:
            steps = trigger_steps(_G["sf"].get((t, j)))
            _G["delay"][(t, j)] = {tr: delay_of(steps, tr) for tr in range(1, len(TRIGS))}
    fkeys = list(seen)
    X = np.stack([trade_features(it, kind) for it, kind in seen.values()]) if fkeys else np.zeros((0, len(FEATS)))
    R43.LEVEL = LEVEL
    items, recs = items_for(its, metas, 0, 0, 0, 0, 0)
    net = {_key(it): float(np.sum(it["r"])) - float(it.get("loc", 0.0)) for it in items}
    have = [i for i, k in enumerate(fkeys) if k in net]
    yrs = np.array([pd.Timestamp(D["dates"][k[0]]).year for k in fkeys])
    _G["flt"] = fit_filters([fkeys[i] for i in have], yrs[have], X[have],
                            np.array([net[fkeys[i]] > 0 for i in have], int))
    _G["X"] = (fkeys, X)
    print(json.dumps({"sessions": len(keys), "with_stats": sum(v is not None for v in _G["sf"].values()),
                      "trades": len(fkeys), "with_target": len(have), "setup_s": round(time.time() - t0),
                      "coverage": {FEATS[i]: round(float(np.isfinite(X[:, i]).mean()), 3) for i in range(len(FEATS))}
                      if len(X) else {}}), flush=True)


def unit_books(uid: int) -> tuple[tuple, list, list[int]]:
    """(the replay combination, its filters, their book ids)."""
    if uid < NR:
        combo = tuple(int(x) for x in np.unravel_index(uid, RSH))
        return combo, list(range(len(FILTERS))), [int(np.ravel_multi_index((f,) + combo, MSHAPE))
                                                  for f in range(len(FILTERS))]
    lp, ch = divmod(uid - NR, NCH)
    lo, pa = divmod(lp, len(PARTIALS))
    qs = list(range(ch * len(FILTERS), min((ch + 1) * len(FILTERS), len(PAIRS))))
    return (0, 0, 0, lo, pa), [("pair", q) for q in qs], [NB + q * NLP + lp for q in qs]


def _unit(uid: int) -> tuple[list[int], np.ndarray]:
    combo, flts, bids = unit_books(uid)
    ys = R43._G["ys"]
    S = np.full((len(flts), len(TASKS), len(ys), 2), np.nan, np.float32)
    for ti, task in enumerate(TASKS):
        its, metas = R43._G["its"][(LEVEL, task)]
        items, recs = items_for(its, metas, *combo)
        for fi, flt in enumerate(flts):
            r = account(filtered(items, flt), recs)
            S[fi, ti] = R40.year_stats(r[R43._G["pos"]], R43._G["years"], ys)
    return bids, S


def units(shard: int, shards: int) -> list[int]:
    u = list(range(shard, NUNIT, shards))
    if QUICK:
        u = sorted(set(u[:2]) | ({0, NR} if shard == 0 else set()))
    return u


def cmd_run(args) -> int:
    setup(args, procs=args.procs)
    uids = units(args.shard, args.shards)
    t0 = time.time()
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_unit, uids, chunksize=1)
    bids = np.array([b for g in got for b in g[0]], np.int64)
    S = np.concatenate([g[1] for g in got])
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / f"part_{args.shard}.npz", bids=bids, S=S, ys=np.array(R43._G["ys"]))
    each = (time.time() - t0) / max(len(bids), 1) * args.procs
    print(args.shard, len(uids), "units", len(bids), "books", f"{each:.3f} cpu-s a book", flush=True)
    return 0


def walk_forward(G: np.ndarray, DD: np.ndarray, ys: list[int]) -> dict[int, int]:
    """v43's rule: for each year after the first, among the books whose worst yearly drawdown before it is no worse
    than the base book's, the highest log growth summed over the years before."""
    picks = {ys[0]: BASE}
    for k in range(1, len(ys)):
        g = np.nansum(G[:, :k], axis=1)
        dd = np.nanmin(DD[:, :k], axis=1)
        ok = np.isfinite(G[:, :k]).all(axis=1) & np.isfinite(dd)
        elig = ok & (dd >= dd[BASE] - 1e-12)
        picks[ys[k]] = int(np.flatnonzero(elig)[np.argmax(g[elig])])
    return picks


def _read(runs: Path) -> tuple[np.ndarray, list[int], int]:
    S, ys, n = None, None, 0
    for p in sorted(runs.rglob("part_*.npz")):
        z = np.load(p)
        if S is None:
            ys = [int(y) for y in z["ys"]]
            S = np.full((NBOOK, len(TASKS), len(ys), 2), np.nan, np.float32)
        S[z["bids"]] = z["S"]
        n += len(z["bids"])
    assert S is not None and ys is not None, "no parts"
    return S, ys, n


def _stream(job: tuple) -> tuple[tuple, np.ndarray]:
    level, task, bid, half = job
    return job, book_returns(bid, level, task, half)[R43._G["pos"]]


def marginals(S: np.ndarray, ys: list[int]) -> list[tuple[str, str, float, float]]:
    """Each dimension's values with the others at the base book (base costs, all years, in-sample)."""
    rows = []
    names = ("filter", "trigger", "execution", "emergency exit", "locate", "partial")
    for d, n in enumerate(MSHAPE):
        for v in range(n):
            idx = [0] * len(MSHAPE)
            idx[d] = v
            bid = int(np.ravel_multi_index(tuple(idx), MSHAPE))
            g, dd = S[bid, 0, :, 0].astype(float), S[bid, 0, :, 1].astype(float)
            if np.isfinite(g).all():
                rows.append((names[d], book_name(bid), float(g.sum()), float(dd.min())))
    return rows


def cmd_final(args) -> int:
    S, ys, n = _read(args.runs)
    lv2 = np.r_[E2K, R43.LEVELS]
    setup(args, levels=tuple(float(x) for x in lv2), procs=args.procs)
    cal = R43._G["cal"]
    idx = R32._sub_idx(cal)
    years = R43._G["years"]
    G, DDm = S[:, 0, :, 0].astype(float), S[:, 0, :, 1].astype(float)
    picks = walk_forward(G, DDm, ys)
    bids = sorted(set(picks.values()) | {BASE})
    jobs: list[tuple] = [(float(lv), task, b, None) for lv in lv2 for task in TASKS for b in bids]
    jobs += [(LEVEL, "base", b, h) for b in bids for h in (0, 1)]
    R43._G["count"] = {}
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_stream, jobs, chunksize=1))

    def series(task: str, wf: bool, half: int | None = None) -> np.ndarray:
        if half is not None:
            R = got[(LEVEL, "base", BASE, half)].copy()
            if wf:
                for y, b in picks.items():
                    R[years == y] = got[(LEVEL, "base", b, half)][years == y]
            return R
        R = np.stack([got[(float(lv), task, BASE, None)] for lv in lv2])
        if wf:
            for y, b in picks.items():
                R[:, years == y] = np.stack([got[(float(lv), task, b, None)] for lv in lv2])[:, years == y]
        return R

    res = {t: {b: R43.boot(series(t, b == "wf")[1:], idx if t == "base" else {"all": idx["all"]})
               for b in ("base", "wf")} for t in TASKS}
    two = {b: R43.boot(series("base", b == "wf"), {"all": idx["all"]}, E2K, lv2)["all"] for b in ("base", "wf")}
    halves = {}
    for h in (0, 1):
        for b in ("base", "wf"):
            r = series("base", b == "wf", h)
            halves[(h, b)] = float(np.nansum(R40.year_stats(r, years, ys)[:, 0]))
    a = {t: {b: res[t][b]["all"] for b in ("base", "wf")} for t in TASKS}
    q1 = bool(a["base"]["wf"]["med"] >= GAIN * a["base"]["base"]["med"] and a["base"]["wf"]["p_ruin"] <= MAX_RUIN
              and a["hot5"]["wf"]["p_ruin"] <= MAX_RUIN and a["high"]["wf"]["med"] >= a["high"]["base"]["med"]
              and all(halves[(h, "wf")] > halves[(h, "base")] for h in (0, 1)))
    d = R35._d
    ok = np.isfinite(G).all(axis=1)
    gall = np.where(ok, G.sum(axis=1), -np.inf)
    dmin = np.where(ok, DDm.min(axis=1), -np.inf)
    elig = ok & (dmin >= dmin[BASE] - 1e-12)
    top = np.flatnonzero(elig)[np.argsort(-gall[elig])[:15]]
    wf_hist = sum(float(G[picks[y], k]) for k, y in enumerate(ys))
    L = ["# v44 part M: the book's trades with meta-labels, entry triggers, execution and emergency exits", "",
         f"{n:,} of {NBOOK:,} books computed (each at four cost sets, v43's central realism case: `{FILL}` stops, "
         f"{PART:.0%} of a bar's volume, liquidation at `{LIQ}`); {R29.PATHS} one-year bootstrap paths from $5,000; "
         "ruin = at or under $1,250 at any time.", "",
         "## Q1. Does the walk-forward book improve the book?", "",
         f"**{q1}** (median >= {GAIN} x the base book's, ruin <= 2.5% at base and HOT 5%, high-cost median >= the "
         "base book's, summed log growth better on both symbol halves).", "",
         "| book | costs | all median | all ruin | p10 | 2018-22 median | 2023+ median |", "|---|---|---|---|---|---|---|"]
    for b in ("base", "wf"):
        for t in TASKS:
            s_ = res[t][b]
            L.append(f"| {'base book' if b == 'base' else 'walk-forward'} | {t} | {d(s_['all']['med'])} | "
                     f"{s_['all']['p_ruin']:.1%} | {d(s_['all']['p10'])} | "
                     f"{d(s_['early']['med']) if 'early' in s_ else '-'} | "
                     f"{d(s_['late']['med']) if 'late' in s_ else '-'} |")
    L += ["", "Symbol halves ($10,000 level, base costs, summed log growth):", "",
          "| half | base book | walk-forward |", "|---|---|---|"]
    L += [f"| {h} | {halves[(h, 'base')]:.2f} | {halves[(h, 'wf')]:.2f} |" for h in (0, 1)]
    L += ["", f"Historical path at $10,000: walk-forward {wf_hist:.2f} vs base {float(np.nansum(G[BASE])):.2f} "
          "(summed log growth).", "", "Walk-forward picks:", ""]
    L += [f"- {y}: {book_name(b)}" for y, b in picks.items()]
    L += ["", "## Each dimension alone (others as the base book; in-sample, all years, base costs)", "",
          "| dimension | book | log growth | worst yearly drawdown |", "|---|---|---|---|"]
    L += [f"| {dim} | {nm} | {g:.2f} | {dd:.1%} |" for dim, nm, g, dd in marginals(S, ys)]
    L += ["", "## Top fixed books (in-sample, all years, chosen after the fact; drawdown no worse than the base's)", "",
          "| book | log growth | worst yearly drawdown |", "|---|---|---|",
          f"| base | {gall[BASE]:.2f} | {dmin[BASE]:.1%} |"]
    L += [f"| {book_name(int(b))} | {gall[b]:.2f} | {dmin[b]:.1%} |" for b in top]
    L += ["", "## Q4. From $2,000 (base costs; ruin = at or under $500)", "",
          "| book | median | ruin | p10 | -50% |", "|---|---|---|---|---|"]
    for b, s_ in two.items():
        L.append(f"| {'base book' if b == 'base' else 'walk-forward'} | {d(s_['med'])} | {s_['p_ruin']:.1%} | "
                 f"{d(s_['p10'])} | {s_['p_half']:.1%} |")
    fk, X = _G["X"]
    L += ["", "## Feature coverage (share of the book's trades with the feature)", "",
          ", ".join(f"{FEATS[i]} {float(np.isfinite(X[:, i]).mean()):.0%}" for i in range(len(FEATS))) if len(X)
          else "none", "", "## Counts (final replays)", "", json.dumps(R43._G["count"]), ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V44M_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    summ = {"q1": q1, "picks": {str(y): int(b) for y, b in picks.items()},
            "pick_names": {str(y): book_name(b) for y, b in picks.items()}, "res": res, "two_k": two,
            "halves": {f"{h}_{b}": v for (h, b), v in halves.items()}, "books": n}
    (args.out / "v44m_summary.json").write_text(json.dumps(summ, indent=1, default=float), encoding="utf-8")
    print("\n".join(L[:14]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, required=True)
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--v44", type=Path, default=Path("outputs/v44"))
        p.add_argument("--out", type=Path, default=Path("outputs/v44w/m"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v44m"
    raise SystemExit(main())
