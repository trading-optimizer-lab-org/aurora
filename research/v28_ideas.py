"""v28 megarun: the new name filters, the squeeze-risk model, the new event entries, the premarket and after-hours
entries, the long and diversifying books (V28_PREREGISTRATION.md).

Every input is known before the entry: filings map to the first session after their date, fails-to-deliver files
and short interest are used only after their publication lag (scripts/run_v28_data.py), XBRL facts from their
filing date, the threshold list of a session is the one published for it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v18_rules as v18
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh

X: dict = {}  # extras28 plus the derived panels (prepare)
HOLD_EXTRA = {"d10": 9}
TARGETS = ("none", "t20", "t30", "t50")  # cover at a fall of 20/30/50% from the entry (sessions after the entry day)
FILTERS28 = ("none", "ftd05", "ftd1", "ftd2", "thr", "thronly", "si10", "si20", "dtc3", "dtc5", "run6", "run12",
             "runok", "gc", "nogc", "dil20", "dil50", "mania80", "mania90", "btc10", "iwm4", "arkk", "hyg", "vix15",
             "nofri", "nothu", "noearn", "ml10", "ml20", "ml30")
BANDS = ("low", "high")
TRIGS = ("open", "lowclose", "redclose")
RUNS = ("any", "up30_5", "up100_20")
ML_FEATURES = ("gap", "r1", "rise20", "logp", "logdv", "logso", "rot1", "ftd", "thr", "si", "si_known", "dtc",
               "runway", "gc", "offer", "dil", "mania", "vix", "fri", "age", "sq60", "earn")


def _shift(a: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype=float)
    out[k:] = a[:-k]
    return out


def _col(D: dict, sym: str) -> int | None:
    m = np.flatnonzero(np.asarray(D["cols"]).astype(str) == sym)
    return int(m[0]) if len(m) else None


def _series(D: dict, sym: str) -> np.ndarray:
    j = _col(D, sym)
    return np.full(len(D["dates"]), np.nan) if j is None else np.asarray(D["C"][:, j], float)


def prepare(D: dict, E: dict, extras: dict, btc: pd.Series | None) -> None:
    """The derived panels: the daily count of small caps closing +50% (mania), market regimes known at the prior
    close, listing age, and the squeeze-risk model's walk-forward predictions."""
    X.clear()
    X.update(extras)
    C, P1, DV1 = np.asarray(D["C"], float), np.asarray(D["P1"], float), np.asarray(D["DV1"], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r1 = C / _shift(C) - 1
        small = (P1 >= 1) & (P1 <= 20) & (DV1 >= 5e5) & D["valid"] & D["valid1"]
        mania = np.where(small & (r1 >= 0.5), 1.0, 0.0).sum(axis=1)
    ms = pd.Series(mania)
    X["mania"] = mania
    for q in (80, 90):
        X[f"mania_q{q}"] = np.array(ms.rolling(250, min_periods=60).quantile(q / 100).shift(1), float)
    T = len(D["dates"])

    def ret5(a: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return _shift(a / _shift(a, 5) - 1)  # known at the prior close
    X["iwm5"] = ret5(_series(D, "IWM"))
    arkk = _series(D, "ARKK")
    X["arkk_up"] = _shift(arkk > pd.Series(arkk).rolling(50, min_periods=40).mean().to_numpy()) > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = _series(D, "HYG") / _series(D, "IEF")
    X["hyg_up"] = _shift(ratio > pd.Series(ratio).rolling(50, min_periods=40).mean().to_numpy()) > 0
    if btc is not None and len(btc):
        b = btc.sort_index()
        b = b[~b.index.duplicated()].reindex(pd.date_range(b.index.min(), max(b.index.max(), D["dates"][-1])))
        b = b.ffill()
        X["btc5"] = _shift((b / b.shift(5) - 1).reindex(D["dates"]).to_numpy(float))
    else:
        X["btc5"] = np.full(T, np.nan)
    first = np.argmax(D["valid"], axis=0)
    X["first_row"] = np.where(D["valid"].any(axis=0), first, T)
    X["fri"] = (D["dates"].dayofweek == 4)
    X["thu"] = (D["dates"].dayofweek == 3)
    X["E_V"] = np.asarray(E["V"], float) if "V" in E else None
    ev = X.get("events", {})
    earn = np.zeros(C.shape, bool)
    if "earn" in ev and len(ev["earn"]):
        t, j = ev["earn"]["t"].to_numpy(int), ev["earn"]["j"].to_numpy(int)
        earn[t, j] = True
    X["earn_any"] = earn | np.vstack([np.zeros((1, C.shape[1]), bool), earn[:-1]])
    squeeze_model(D)


# ---------------------------------------------------------------- the squeeze-risk model

def _cands(D: dict) -> np.ndarray:
    """Name-days the model scores: small caps ($1-$20, $500k of dollar volume) with a gap of 10% or more, a prior day of
    +20% or more, or a close 50% over the 20-session low the day before."""
    O, C = np.asarray(D["O"], float), np.asarray(D["C"], float)
    pc = _shift(C)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = O / pc - 1
        r1 = pc / _shift(C, 2) - 1
        low20 = pd.DataFrame(C).rolling(20, min_periods=10).min().shift(2).to_numpy()
        rise = pc / low20 - 1
        P1, DV1 = np.asarray(D["P1"], float), np.asarray(D["DV1"], float)
        ok = D["valid"] & D["valid1"] & (P1 >= 1) & (P1 <= 20) & (DV1 >= 5e5)
        X["low20s2"] = low20
        return ok & ((np.abs(gap) >= 0.10) | (r1 >= 0.2) | (rise >= 0.5))


def features(D: dict, t: np.ndarray, j: np.ndarray) -> np.ndarray:
    """The model's inputs at the open of session t, all known by then."""
    O, H, C = (np.asarray(D[k], float) for k in ("O", "H", "C"))
    T, N = C.shape
    tm1, tm2 = np.maximum(t - 1, 0), np.maximum(t - 2, 0)
    pc = C[tm1, j]
    with np.errstate(invalid="ignore", divide="ignore"):
        lo20 = X["low20s2"][t, j]
        so = np.asarray(D["SO"], float)[t, j]
        vol = X["E_V"][tm1, j] if X.get("E_V") is not None else np.full(len(t), np.nan)
        f = {"gap": np.log(np.clip(O[t, j] / pc, 1e-3, None)), "r1": np.clip(pc / C[tm2, j] - 1, -1, 10),
             "rise20": np.clip(pc / lo20 - 1, -1, 50), "logp": np.log(np.clip(np.asarray(D["P1"], float)[t, j], 0.01, None)),
             "logdv": np.log1p(np.asarray(D["DV1"], float)[t, j]), "logso": np.log1p(so),
             "rot1": np.clip(vol / so, 0, 50), "ftd": np.clip(X["ftd_so"][t, j], 0, 1),
             "thr": X["thr"][t, j].astype(float),
             "si": np.clip(X["si_so"][t, j], 0, 2) if "si_so" in X else np.zeros(len(t)),
             "si_known": X["si_known"][t, j].astype(float) if "si_known" in X else np.zeros(len(t)),
             "dtc": np.clip(X["dtc"][t, j], 0, 50) if "dtc" in X else np.zeros(len(t)),
             "runway": np.clip(X["runway"][t, j], 0, 60), "gc": X["gc"][t, j].astype(float),
             "offer": sh.FACTS["offer"][t, j].astype(float), "dil": np.clip(X["so_g250"][t, j], -1, 20),
             "mania": np.log1p(X["mania"][tm1]), "vix": X["vix"][t], "fri": X["fri"][t].astype(float),
             "age": np.log1p(np.maximum(t - X["first_row"][j], 0)), "sq60": sh.FACTS["squeeze"][t, j].astype(float),
             "earn": X["earn_any"][t, j].astype(float)}
    M = np.column_stack([np.asarray(f[k], float) for k in ML_FEATURES])
    return np.where(np.isfinite(M), M, np.nan)


def logistic(Xm: np.ndarray, y: np.ndarray, lam: float = 1.0, iters: int = 30) -> np.ndarray:
    """L2 logistic regression by Newton steps; Xm already has its intercept column."""
    w = np.zeros(Xm.shape[1])
    reg = lam * np.eye(Xm.shape[1])
    reg[0, 0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Xm @ w, -30, 30)))
        g = Xm.T @ (p - y) + reg @ w
        Hs = (Xm * (p * (1 - p))[:, None]).T @ Xm + reg
        step = np.linalg.solve(Hs, g)
        w -= step
        if np.max(np.abs(step)) < 1e-6:
            break
    return w


def squeeze_model(D: dict) -> None:
    """Each year from 2017, a logistic model fit on the earlier years' candidate name-days (label: the high of the
    session or the two after reaches 50% over its open) scores that year's candidates; ``sq_p`` holds the scores and
    ``sq_cut`` each year's cut-offs (the 70th, 80th and 90th percentile of the training scores)."""
    cand = _cands(D)
    t, j = np.nonzero(cand)
    T = cand.shape[0]
    H, O = np.asarray(D["H"], float), np.asarray(D["O"], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        hi3 = np.fmax(H[t, j], np.fmax(H[np.minimum(t + 1, T - 1), j], H[np.minimum(t + 2, T - 1), j]))
        y = (hi3 / O[t, j] - 1 >= 0.5).astype(float)
    Fm = features(D, t, j)
    years = D["dates"][t].year
    P = np.full(cand.shape, np.nan, np.float32)
    cuts: dict = {}
    for yr in range(2017, int(D["dates"][-1].year) + 1):
        start = int(np.searchsorted(D["dates"], pd.Timestamp(f"{yr}-01-01")))
        tr = (t <= start - 3) & np.isfinite(y)
        te = years == yr
        if tr.sum() < 500 or not te.any():
            continue
        mu = np.nanmean(Fm[tr], axis=0)
        sd = np.nanstd(Fm[tr], axis=0)
        sd = np.where(sd > 0, sd, 1.0)

        def z(M: np.ndarray, mu: np.ndarray = mu, sd: np.ndarray = sd) -> np.ndarray:
            Z = (M - mu) / sd
            return np.column_stack([np.ones(len(Z)), np.nan_to_num(Z, nan=0.0)])
        w = logistic(z(Fm[tr]), y[tr])
        ptr = 1 / (1 + np.exp(-np.clip(z(Fm[tr]) @ w, -30, 30)))
        P[t[te], j[te]] = 1 / (1 + np.exp(-np.clip(z(Fm[te]) @ w, -30, 30)))
        cuts[yr] = {q: float(np.quantile(ptr, 1 - q / 100)) for q in (10, 20, 30)}
    X["sq_p"], X["sq_cut"] = P, cuts


# ---------------------------------------------------------------- the name and regime filters

def keep28(D: dict, t: np.ndarray, j: np.ndarray, rule: str) -> np.ndarray:
    """The trades a v28 filter keeps (entry session t, column j). Unknown values keep the trade, except the 'keep
    only' rules (thronly, run6, run12, gc, dil20, dil50), which need the value."""
    t, j = np.asarray(t, int), np.asarray(j, int)
    n = len(t)
    if rule == "none" or n == 0:
        return np.ones(n, bool)
    with np.errstate(invalid="ignore"):
        if rule.startswith("ftd"):
            lim = {"ftd05": 0.005, "ftd1": 0.01, "ftd2": 0.02}[rule]
            return ~(X["ftd_so"][t, j] >= lim)
        if rule == "thr":
            return ~X["thr"][t, j]
        if rule == "thronly":
            return X["thr"][t, j]
        if rule in ("si10", "si20"):
            return np.ones(n, bool) if "si_so" not in X else ~(X["si_so"][t, j] >= int(rule[2:]) / 100)
        if rule in ("dtc3", "dtc5"):
            return np.ones(n, bool) if "dtc" not in X else ~(X["dtc"][t, j] >= int(rule[3:]))
        if rule in ("run6", "run12"):
            return X["runway"][t, j] < int(rule[3:])
        if rule == "runok":
            return ~(X["runway"][t, j] < 12)
        if rule == "gc":
            return X["gc"][t, j]
        if rule == "nogc":
            return ~X["gc"][t, j]
        if rule in ("dil20", "dil50"):
            return X["so_g250"][t, j] >= int(rule[3:]) / 100
        if rule in ("mania80", "mania90"):
            tm1 = np.maximum(t - 1, 0)
            return ~(X["mania"][tm1] >= X[f"mania_q{rule[5:]}"][t])
        if rule == "btc10":
            return ~(X["btc5"][t] >= 0.10)
        if rule == "iwm4":
            return ~(X["iwm5"][t] >= 0.04)
        if rule == "arkk":
            return ~X["arkk_up"][t]
        if rule == "hyg":
            return ~X["hyg_up"][t]
        if rule == "vix15":
            return ~(X["vix"][t] < 15)
        if rule == "nofri":
            return ~X["fri"][t]
        if rule == "nothu":
            return ~(X["fri"][t] | X["thu"][t])
        if rule == "noearn":
            return ~X["earn_any"][t, j]
        if rule.startswith("ml"):
            q = int(rule[2:])
            p = X["sq_p"][t, j]
            cut = np.array([X["sq_cut"].get(int(y), {}).get(q, np.inf) for y in D["dates"][t].year])
            return ~(p >= cut)
    raise KeyError(rule)


def install() -> None:
    """v26's shield reads v28's filters and the ten-session hold; v26's own rules are unchanged."""
    if getattr(sh, "_v28", False):
        return
    base_keep = sh.keep

    def keep(D: dict, t: np.ndarray, j: np.ndarray, rule: str) -> np.ndarray:
        if rule in sh.FILTERS:
            return base_keep(D, t, j, rule)
        return keep28(D, t, j, rule)

    sh.keep = keep
    sh.HOLD.update(HOLD_EXTRA)
    sh._v28 = True
    sh._v28_base_keep = base_keep


def uninstall() -> None:
    """Back to v26's shield (tests)."""
    if getattr(sh, "_v28", False):
        sh.keep = sh._v28_base_keep
        for k in HOLD_EXTRA:
            sh.HOLD.pop(k, None)
        sh._v28 = False


# ---------------------------------------------------------------- event entries (daily specs)

def event_mask(D: dict, rows: pd.DataFrame, when: str = "pre") -> np.ndarray:
    """A setup mask from event rows (t = the first session after the filing): 'pre' marks the session before, so a
    trade can enter at the event session's open."""
    S = np.zeros(D["C"].shape, bool)
    if rows is None or not len(rows):
        return S
    t, j = rows["t"].to_numpy(int), rows["j"].to_numpy(int)
    if when == "pre":
        ok = t >= 1
        S[t[ok] - 1, j[ok]] = True
    else:
        S[t, j] = True
    return S


def run_ok(D: dict, run: str) -> np.ndarray:
    C = np.asarray(D["C"], float)
    if run == "any":
        return np.ones(C.shape, bool)
    w, x = (5, 0.30) if run == "up30_5" else (20, 1.0)
    low = pd.DataFrame(C).rolling(w, min_periods=max(2, w // 2)).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return C / low - 1 >= x


def _base(D: dict) -> np.ndarray:
    return D["valid"] & (np.nan_to_num(np.asarray(D["DV"], float)) >= 5e5)


def ipo_rows(D: dict) -> np.ndarray:
    """First session of each column listed after 2016-02 with a 424B4 prospectus in the 20 sessions up to it."""
    ev = X.get("events", {}).get("ipo")
    first = X["first_row"]
    start = int(np.searchsorted(D["dates"], pd.Timestamp("2016-02-01")))
    out = np.full(len(first), -1)
    if ev is None or not len(ev):
        return out
    by_j: dict[int, list[int]] = {}
    for t, j in zip(ev["t"].to_numpy(int), ev["j"].to_numpy(int)):
        by_j.setdefault(j, []).append(t)
    for j, ts in by_j.items():
        f = int(first[j])
        if f >= start and any(f - 20 <= x <= f + 1 for x in ts):
            out[j] = f
    return out


def ipo_panel(D: dict) -> dict:
    """The panel for the IPO family: where a new listing has no 20-day dollar volume yet (its first ten sessions),
    the mean dollar volume of its sessions so far (DV) and before (DV1)."""
    if "ipo_D" not in X:
        V = X.get("E_V")
        P = np.asarray(D["P"], float)
        dollar = P * V if V is not None else np.full(P.shape, np.nan)
        fin = np.isfinite(dollar)
        mean = np.nancumsum(np.where(fin, dollar, 0.0), axis=0) / np.maximum(np.cumsum(fin, axis=0), 1)
        mean = np.where(np.cumsum(fin, axis=0) > 0, mean, np.nan)
        dv = np.asarray(D["DV"], float)
        dv_f = np.where(np.isfinite(dv), dv, mean)
        dv1_f = np.where(np.isfinite(np.asarray(D["DV1"], float)), D["DV1"], _shift(dv_f))
        X["ipo_D"] = {**D, "DV": dv_f.astype(np.float32), "DV1": dv1_f.astype(np.float32)}
    return X["ipo_D"]


def sympathy_mask(D: dict, x: float) -> np.ndarray:
    """Session t: a company of the same four-digit SIC code (a leader) closed +50% (prior close $1-$20) and this one
    closed +x without an 8-K that session or the one before."""
    C = np.asarray(D["C"], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r1 = C / _shift(C) - 1
    P1 = np.asarray(D["P1"], float)
    lead = (r1 >= 0.5) & (P1 >= 1) & (P1 <= 20)
    sic = np.asarray(X.get("sic", np.array([""] * C.shape[1])))
    codes, inv = np.unique(sic, return_inverse=True)
    S = np.zeros(C.shape, bool)
    news = np.zeros(C.shape, bool)
    for k in ("news", "earn", "pipe"):
        rows = X.get("events", {}).get(k)
        if rows is not None and len(rows):
            news[rows["t"].to_numpy(int), rows["j"].to_numpy(int)] = True
    news |= np.vstack([np.zeros((1, C.shape[1]), bool), news[:-1]])
    for g in range(len(codes)):
        if codes[g] in ("", "None", "nan"):
            continue
        cols = np.flatnonzero(inv == g)
        if len(cols) < 2:
            continue
        nl = lead[:, cols].sum(axis=1)
        sub = (r1[:, cols] >= x) & ~lead[:, cols] & (nl[:, None] >= 1) & ~news[:, cols]
        S[:, cols] |= sub
    return S


EVENT_FAMS = {  # key -> (event, parameter values, setup timing)
    "C:EFFECT_SHORT": ("effect", ("any", "pipe120"), "pre"),
    "C:PIPE_SHORT": ("pipe", ("any",), "pre"),
    "C:NT_SHORT": ("nt", ("any",), "pre"),
    "C:GC_SHORT": ("gc_new", ("any",), "pre"),
    "C:CRYPTO_SHORT": ("crypto", ("any",), "pre"),
    "C:RENAME_SHORT": ("rename", ("any",), "pre"),
    "C:DESPAC_SHORT": ("despac", ("any",), "pre"),
    "C:S4_SHORT": ("s4", ("any",), "pre"),
    "C:EARN_SHORT": ("earn", ("x15", "x30"), "post"),
    "C:IPO_SHORT": ("ipo", ("x50", "x100", "x300"), "ipo"),
    "C:LOCKUP_SHORT": ("ipo", ("d62k5", "d62k1", "d124k5", "d124k1"), "lockup"),
    "C:SYMPATHY_SHORT": ("sympathy", ("x10", "x20"), "sym"),
}


def event_grid(key: str) -> list[dict]:
    _, params, when = EVENT_FAMS[key]
    trigs = ("open",) if when == "lockup" else TRIGS
    return [{"param": p, "run": r, "band": b, "trig": tg, "hold": h, "stop": s, "ext": e}
            for p in params for r in RUNS for b in BANDS for tg in trigs for h in ("d1", "d2", "d3", "d5", "d10")
            for s in ("pct10", "pct20", "pct35", "pct50", "atr2", "atr4") for e in sh.EXT]


def event_specs(D: dict, key: str, g: dict) -> list[v19.Spec]:
    """The short entries of an event family (the shield gives the exit)."""
    ev_name, _, when = EVENT_FAMS[key]
    C, O = np.asarray(D["C"], float), np.asarray(D["O"], float)
    ev = X.get("events", {})
    T = C.shape[0]
    base = _base(D) & v18._band_arr(np.asarray(D["P"], float), g["band"]) & run_ok(D, g["run"])
    p = g["param"]
    if when == "pre":
        S = event_mask(D, ev.get(ev_name), "pre")
        if p == "pipe120":
            pm = event_mask(D, ev.get("pipe"), "post").astype(float)
            S &= pd.DataFrame(pm).rolling(120, min_periods=1).max().to_numpy() > 0
    elif when == "post":
        with np.errstate(invalid="ignore", divide="ignore"):
            S = event_mask(D, ev.get(ev_name), "post") & (C / _shift(C) - 1 >= int(p[1:]) / 100)
    elif when == "ipo":
        S = np.zeros(C.shape, bool)
        x = int(p[1:]) / 100
        for j, f in enumerate(ipo_rows(D)):
            if f < 0:
                continue
            o0 = O[f, j]
            for u in range(f, min(f + 10, T)):
                if np.isfinite(C[u, j]) and o0 > 0 and C[u, j] / o0 - 1 >= x:
                    S[u, j] = True
                    break
    elif when == "lockup":
        S = np.zeros(C.shape, bool)
        d, k = int(p[1:].split("k")[0]), int(p.split("k")[1])
        for j, f in enumerate(ipo_rows(D)):
            u = f + d - k - 1
            if f >= 0 and 0 <= u < T - 1:
                S[u, j] = True
    else:
        S = sympathy_mask(D, int(p[1:]) / 100)
    S &= base
    rows = v19._setup_trigger(D, S, C, g["trig"])
    return v19._once_specs(rows, -1, {"stop": "none", "exit": "time"}, 9)


# ---------------------------------------------------------------- long families (daily specs, own exits)

LONG_FAMS = ("D:PDUFA_LONG", "D:BUYBACK_LONG", "D:JANUARY_LONG", "D:MANIA_LONG")


def long_grid(key: str) -> list[dict]:
    if key == "D:PDUFA_LONG":
        return [{"k": k, "b": b, "stop": s, "band": bd, "prior": pr} for k in (40, 20, 10, 5) for b in (1, 3)
                for s in ("none", "0.15", "0.25") for bd in ("low", "high", "all") for pr in ("any", "notup50")
                if k > b]
    if key == "D:BUYBACK_LONG":
        return [{"trig": tg, "hold": h, "stop": s, "band": bd, "so": so} for tg in ("open", "greenclose")
                for h in (5, 10, 20) for s in ("none", "0.10", "0.20") for bd in ("low", "high", "all")
                for so in ("any", "so50")]
    if key == "D:JANUARY_LONG":
        return [{"fall": f, "entry": e, "exit": x, "band": bd} for f in (0.4, 0.6, 0.8) for e in (1, 5)
                for x in (5, 10, 20) for bd in ("low", "high", "all")]
    return [{"thr": th, "top": n, "hold": h, "stop": s} for th in ("q80", "q90", "always") for n in (3, 5, 10)
            for h in (1, 2, 3) for s in ("none", "0.15")]


def _bandx(D: dict, band: str) -> np.ndarray:
    return v18._band_arr(np.asarray(D["P"], float), None if band == "all" else band)


def long_specs(D: dict, key: str, g: dict) -> list[v19.Spec]:
    C = np.asarray(D["C"], float)
    T = C.shape[0]
    stop = np.nan if g.get("stop", "none") == "none" else float(g["stop"])
    ev = X.get("events", {})
    out: list[v19.Spec] = []
    if key == "D:PDUFA_LONG":
        rows = ev.get("pdufa")
        if rows is None:
            return out
        ok = _base(D) & _bandx(D, g["band"])
        with np.errstate(invalid="ignore", divide="ignore"):
            low20 = pd.DataFrame(C).rolling(20, min_periods=10).min().to_numpy()
            up = C / low20 - 1 >= 0.5
        for t_f, j, tt in zip(rows["t"].to_numpy(int), rows["j"].to_numpy(int), rows["t_target"].to_numpy(int)):
            te = tt - g["k"]
            if te < max(t_f, 1) or te >= T or not ok[te - 1, j]:
                continue
            if g["prior"] == "notup50" and up[te - 1, j]:
                continue
            out.append(v19.Spec(int(j), int(te), "open", 1, int(g["k"] - g["b"]), stop, np.nan, np.nan, "time", 0.0))
        return out
    if key == "D:BUYBACK_LONG":
        S = event_mask(D, ev.get("buyback"), "pre") & _base(D) & _bandx(D, g["band"])
        if g["so"] == "so50":
            S &= np.asarray(D["SO"], float) < 50e6
        rows = v19._setup_trigger(D, S, C, g["trig"])
        return v19._once_specs(rows, 1, {"stop": g["stop"], "exit": "time"}, int(g["hold"]))
    if key == "D:JANUARY_LONG":
        dates = D["dates"]
        ok = _base(D) & _bandx(D, g["band"])
        for y in range(2016, int(dates[-1].year)):
            dec = np.flatnonzero((dates.year == y) & (dates.month == 12))
            jan = np.flatnonzero((dates.year == y + 1) & (dates.month == 1))
            y0 = np.flatnonzero(dates.year == y)
            if len(dec) < 5 or len(jan) < g["exit"] or not len(y0):
                continue
            te = int(dec[-g["entry"]])
            with np.errstate(invalid="ignore", divide="ignore"):
                ytd = C[te] / C[y0[0]] - 1
            cols = np.flatnonzero(ok[te] & (ytd <= -g["fall"]))
            hold = int(jan[g["exit"] - 1]) - te
            out += [v19.Spec(int(j), te, "close", 1, hold, np.nan, np.nan, np.nan, "time", float(-ytd[j])) for j in cols]
        return out
    with np.errstate(invalid="ignore", divide="ignore"):
        r1 = C / _shift(C) - 1
    P = np.asarray(D["P"], float)
    ok = _base(D) & (P >= 1) & (P <= 20)
    for t in range(1, T - 1):
        if g["thr"] != "always":
            q = X[f"mania_q{g['thr'][1:]}"][t + 1]
            if not (np.isfinite(q) and X["mania"][t] >= q):
                continue
        cols = np.flatnonzero(ok[t] & np.isfinite(r1[t]))
        top = cols[np.argsort(-r1[t, cols])[:g["top"]]]
        out += [v19.Spec(int(j), t + 1, "open", 1, int(g["hold"]), stop, np.nan, np.nan, "time", float(r1[t, j]))
                for j in top]
    return out


# ---------------------------------------------------------------- premarket and after-hours entries

PM_GRID = [{"gap": gp, "minute": m, "rule": r, "stop": s, "hold": h, "band": b, "ext": e}
           for gp in (0.2, 0.4, 0.8) for m in (180, 240, 300, 325) for r in ("any", "off10")
           for s in ("pct20", "pct35", "pct50") for h in ("d1", "d2", "d3", "d5") for b in BANDS
           for e in ("none", "both")]
AH_GRID = [{"up": u, "minute": m, "rule": r, "stop": s, "hold": h, "band": b, "ext": e}
           for u in (0.3, 0.6, 1.0) for m in (5, 30, 90, 180) for r in ("any", "below")
           for s in ("pct20", "pct35", "pct50") for h in ("d1", "d2", "d3", "d5") for b in BANDS
           for e in ("none", "pm")]
PM_STORE: "sh.Nights | None" = None


def _first_session(D: dict, t: int, j: int, e: float, stop: float) -> tuple[float, str] | None:
    """A short entered before session t's open (on the adjusted scale): its exit price within session t if the stop
    is hit, else None (held to the close)."""
    o, h = float(D["O"][t, j]), float(D["H"][t, j])
    if not np.isfinite(h):
        return None
    if np.isfinite(o) and o >= stop:
        return o, "open"
    if h >= stop:
        return v19._slip(stop, h), "stop"
    return None


def _row(D: dict, t: int, j: int, e: float, stop: float, rets: list, nights: float, leg_in: int, leg_out: int,
         raw: float, liq: float, prio: float, minute: int) -> dict:
    return {"date": D["dates"][t], "t": t, "symbol": str(D["cols"][j]), "minute": minute, "side": -1, "entry": e,
            "stop": stop, "price": raw, "liq": liq, "prio": prio, "so": float(D["SO"][t, j]),
            "rets": np.array(rets, float), "nights": nights, "rule": "x", "opens": int(leg_out == 0), "xmin": -1,
            "leg_in": leg_in, "leg_out": leg_out}


def _hold_rest(D: dict, t: int, j: int, e: float, stop: float, closes: int, ext: str) -> tuple[list, float, int]:
    """Session t from its open (entry before it), then the shield's walk for the closes after."""
    C = np.asarray(D["C"], float)
    hit = _first_session(D, t, j, e, stop)
    if hit is not None:
        return [(e - hit[0]) / e], 0.0, 2 if hit[1] == "stop" else 0
    c = float(C[t, j])
    rets = [(e - c) / e]
    if closes <= 0:
        return rets, 0.0, 2
    P = {"hold": "d1", "stop": "own", "ext": ext, "rally": "none", "scale": "all"}
    more, nights, leg = sh.walk(D, t, j, e, stop, c, 1.0, [0.0] * closes, P)
    return rets + more, nights, leg


def pm_trades(D: dict, g: dict, rng: np.random.Generator | None = None, real: pd.DataFrame | None = None
              ) -> pd.DataFrame:
    """Shorts entered in the premarket of a gap day at a fixed minute (night minute 240 = 04:00), on the minute
    bar's open, when the price is at least ``gap`` over the prior close (and, for 'off10', 10% under the premarket
    high so far). The stop is live on the premarket bars after the entry, then as in the shield. A placebo moves each
    real trade to a random other gapper of the same night at the same minute."""
    if PM_STORE is None:
        return pd.DataFrame(columns=v19.COLS)
    P_raw, F = np.asarray(D["P"], float), np.asarray(D["F"], float)
    band = v18._band_arr(np.asarray(D["P1"], float), g["band"])
    closes = sh.HOLD[g["hold"]]
    by_u: dict[int, list[int]] = {}
    for u, j in PM_STORE.pos:
        by_u.setdefault(u, []).append(j)
    targets: list[tuple[int, int]]
    if real is not None and rng is not None:
        pos = {str(s): i for i, s in enumerate(D["cols"])}
        targets = []
        for t, sym in zip(real["t"].to_numpy(int), real["symbol"].astype(str)):
            pool = [x for x in by_u.get(t - 1, []) if x != pos.get(sym)]
            if pool:
                targets.append((t - 1, int(rng.choice(pool))))
    else:
        targets = [(u, j) for u, js in sorted(by_u.items()) for j in js]
    rows = []
    for u, j in targets:
        t = u + 1
        if t >= len(D["dates"]) or not band[t, j]:
            continue
        b = PM_STORE.bars(u, j)
        if b is None:
            continue
        m, o, h, c, = b[0], b[1], b[2], b[4]
        k = int(np.searchsorted(m, 240 + g["minute"]))
        if k >= len(m) or m[k] >= 570 or m[k] < 240:
            continue
        pc = float(P_raw[u, j])
        e_raw = float(o[k])
        if real is None and not (pc > 0 and e_raw / pc - 1 >= g["gap"]):
            continue
        pre = m < m[k]
        pmh = float(np.max(h[pre & (m >= 240)])) if np.any(pre & (m >= 240)) else e_raw
        if real is None and g["rule"] == "off10" and not e_raw <= pmh / 1.10:
            continue
        f = float(F[t, j])
        if not (np.isfinite(f) and f > 0):
            continue
        s_raw = e_raw * (1 + int(g["stop"][3:]) / 100)
        rets, nights, leg = None, 0.0, 2
        for q in range(k + 1, len(m)):
            if m[q] < 240:
                continue
            if h[q] >= s_raw:
                px = o[q] if o[q] >= s_raw else v19._slip(s_raw, float(h[q]))
                rets, leg = [(e_raw - px) / e_raw], sh.LEG_PM
                break
        if rets is None:
            rets, nights, leg = _hold_rest(D, t, j, e_raw * f, s_raw * f, closes, g["ext"])
        liq = 0.0
        vol = PM_STORE.a.get("v")
        if vol is not None:
            off, n = PM_STORE.pos[(u, j)]
            vv = vol[off:off + n]
            liq = float(np.sum(c[pre & (m >= 240)] * vv[pre & (m >= 240)]))
        rows.append(_row(D, t, j, e_raw * f, s_raw * f, rets, nights, sh.LEG_PM, leg, e_raw, liq,
                         e_raw / pc - 1 if pc > 0 else 0.0, int(m[k])))
    return pd.DataFrame(rows, columns=v19.COLS) if rows else pd.DataFrame(columns=v19.COLS)


def ah_trades(D: dict, g: dict, rng: np.random.Generator | None = None, real: pd.DataFrame | None = None
              ) -> pd.DataFrame:
    """Shorts entered in the after-hours of a session that closed at least ``up`` over the prior close, at a fixed
    minute after 16:00 on the minute bar's open ('below': only under the regular close). The stop is live on the
    after-hours bars after the entry (and the next premarket with ext 'pm'), then as in the shield. A placebo moves
    each real trade to a random other symbol of v26's night store that night."""
    NS = sh.NIGHTS
    if NS is None:
        return pd.DataFrame(columns=v19.COLS)
    C, P_raw, F = np.asarray(D["C"], float), np.asarray(D["P"], float), np.asarray(D["F"], float)
    band = v18._band_arr(np.asarray(D["P1"], float), g["band"])
    closes = sh.HOLD[g["hold"]]
    with np.errstate(invalid="ignore", divide="ignore"):
        up = C / _shift(C) - 1
    by_u: dict[int, list[int]] = {}
    for u, j in NS.pos:
        by_u.setdefault(u, []).append(j)
    if real is not None and rng is not None:
        pos = {str(s): i for i, s in enumerate(D["cols"])}
        targets = []
        for t, sym in zip(real["t"].to_numpy(int), real["symbol"].astype(str)):
            pool = [x for x in by_u.get(t - 1, []) if x != pos.get(sym)]
            if pool:
                targets.append((t - 1, int(rng.choice(pool))))
    else:
        targets = [(u, j) for u, js in sorted(by_u.items()) for j in js
                   if np.isfinite(up[u, j]) and up[u, j] >= g["up"]]
    rows = []
    T = len(D["dates"])
    for t, j in targets:
        if t + 1 >= T or not band[t, j]:
            continue
        b = NS.bars(t, j)
        if b is None or not len(b[0]):
            continue
        m, o, h, c = b[0], b[1], b[2], b[4]
        k = int(np.searchsorted(m, g["minute"]))
        if k >= len(m) or m[k] >= sh.AH_END:
            continue
        e_raw = float(o[k])
        if real is None and g["rule"] == "below" and not e_raw < float(P_raw[t, j]):
            continue
        f_ah, f_pm = float(F[t, j]), float(F[t + 1, j])
        if not (np.isfinite(f_ah) and f_ah > 0 and np.isfinite(f_pm) and f_pm > 0):
            continue
        s_raw = e_raw * (1 + int(g["stop"][3:]) / 100)
        rets, nights, leg = None, 0.0, 2
        for q in range(k + 1, len(m)):
            pm = m[q] >= sh.AH_END
            if pm and g["ext"] != "pm":
                break
            hq = float(h[q]) * (f_pm / f_ah if pm else 1.0)
            oq = float(o[q]) * (f_pm / f_ah if pm else 1.0)
            if hq >= s_raw:
                px = oq if oq >= s_raw else v19._slip(s_raw, hq)
                rets, leg, nights = [(e_raw - px) / e_raw], (sh.LEG_PM if pm else sh.LEG_AH), (1.0 if pm else 0.0)
                break
        if rets is None:
            e, s = e_raw * f_ah, s_raw * f_ah
            more, nn, leg = _hold_rest(D, t + 1, j, e, s, closes, "both" if g["ext"] == "pm" else "none")
            # the first return is from the entry to session t+1's exit; one night held
            rets, nights = more, nn + 1.0
        liq = float(np.nan_to_num(D["DV1"][t + 1, j]))
        # returns start on session t+1: the night's P&L is booked with the first session after the entry
        rows.append(_row(D, t + 1, j, e_raw * f_ah, s_raw * f_ah, rets, nights, sh.LEG_AH, leg, e_raw, liq,
                         float(up[t, j]), int(m[k])))
    return pd.DataFrame(rows, columns=v19.COLS) if rows else pd.DataFrame(columns=v19.COLS)


# ---------------------------------------------------------------- monthly factor books and leveraged ETF pairs

FACTOR_GRID = [{"sig": s, "side": sd, "q": q, "floor": fl, "dv": dv} for s in ("runway", "roa", "issue", "gc", "combo")
               for sd in ("long", "short", "ls") for q in (0.1, 0.2) for fl in (1.0, 3.0) for dv in (1e6, 5e6)]
PAIRS = (("TNA", "TZA"), ("URTY", "SRTY"), ("TQQQ", "SQQQ"), ("UPRO", "SPXU"), ("SPXL", "SPXS"), ("UDOW", "SDOW"),
         ("SOXL", "SOXS"), ("LABU", "LABD"), ("FAS", "FAZ"), ("NUGT", "DUST"), ("JNUG", "JDST"), ("ERX", "ERY"),
         ("TECL", "TECS"), ("YINN", "YANG"), ("GUSH", "DRIP"))
SETS = {"iwm": ("TNA", "URTY"), "index": ("TNA", "URTY", "TQQQ", "UPRO", "SPXL", "UDOW"), "all": None}
LEV_GRID = [{"set": s, "reb": r, "vix": v} for s in SETS for r in ("week", "month") for v in ("none", "v30")]
LEV_FEE = 0.05  # borrow a year on each leg at the middle costs (x3 high); 5 bps half-spread a rebalance


def _signal(D: dict, sig: str) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        if sig == "runway":
            return np.clip(X["runway"], 0, 60)
        if sig == "roa":
            return X["roa"]
        if sig == "issue":
            return -X["so_g250"]
        if sig == "gc":
            return np.where(np.isfinite(X["runway"]) | X["gc"], (~X["gc"]).astype(float), np.nan)
        z = []
        for a in (np.clip(X["runway"], 0, 60), X["roa"], -X["so_g250"]):
            df = pd.DataFrame(a)
            z.append(((df.sub(df.mean(axis=1), axis=0)).div(df.std(axis=1), axis=0)).to_numpy())
        return np.nanmean(np.stack(z), axis=0)


def factor_book(D: dict, g: dict, table: dict, spread: float, fee_mult: float, gross: bool,
                rng: np.random.Generator | None = None) -> tuple[pd.Series, list, np.ndarray]:
    """Equal-weight monthly book: at each month's last close, the names of the universe ranked by the signal (the
    best ``q`` long, the worst ``q`` short); a placebo ranks them at random."""
    C, P = np.asarray(D["C"], float), np.asarray(D["P"], float)
    dates = D["dates"]
    T = len(dates)
    sig = _signal(D, g["sig"])
    ends = np.flatnonzero(np.r_[dates.month[1:] != dates.month[:-1], True])
    with np.errstate(invalid="ignore", divide="ignore"):
        r = C / _shift(C) - 1
    out = np.zeros(T)
    paths: list = []
    hs = v19.R4_HALF[:, 1] if hasattr(v19, "R4_HALF") else np.full(4, 0.004)
    for a, b in zip(ends[:-1], ends[1:]):
        uni = D["valid"][a] & (P[a] >= g["floor"]) & (np.nan_to_num(np.asarray(D["DV"], float)[a]) >= g["dv"]) \
            & np.isfinite(sig[a])
        cols = np.flatnonzero(uni)
        if len(cols) < 50:
            continue
        s = rng.random(len(cols)) if rng is not None else sig[a, cols]
        order = cols[np.argsort(s, kind="stable")]
        n = max(1, int(len(order) * g["q"]))
        legs = []
        if g["side"] in ("long", "ls"):
            legs.append((order[-n:], 1))
        if g["side"] in ("short", "ls"):
            legs.append((order[:n], -1))
        scale = 1.0 / len(legs)
        for cols_l, side in legs:
            px = np.maximum(P[a, cols_l], 0.01)
            tier = np.select([px < 2, px < 5, px < 10], [0, 1, 2], 3)
            cost = 0.0 if gross else 2 * hs[tier] * spread
            fee = np.zeros(len(cols_l))
            if side < 0 and not gross:
                _, f = v19.v15.lookup(table, px, np.asarray(D["SO"], float)[a, cols_l])
                fee = np.maximum(2 * f, 100.0) * fee_mult / 100 / 360
            rr = np.nan_to_num(r[a + 1:b + 1][:, cols_l]) * side - fee[None, :]
            rr[0] -= cost
            w = scale / len(cols_l)
            out[a + 1:b + 1] += w * rr.sum(axis=1)
            for k in range(len(cols_l)):
                paths.append((a + 1, rr[:, k], 0.0, w))
    return pd.Series(out, index=dates), paths, np.ones(len(paths), bool)


def lev_book(D: dict, g: dict, spread: float, fee_mult: float, gross: bool,
             rng: np.random.Generator | None = None) -> tuple[pd.Series, list, np.ndarray]:
    """Short both legs of leveraged ETF pairs, equal weights reset at each rebalance (weekly or monthly); flat after
    a VIX close over 30 for 'v30'. A placebo shorts the same number of random pairs of liquid stocks ($50M a day)."""
    C = np.asarray(D["C"], float)
    dates = D["dates"]
    T = len(dates)
    names = [s for p in PAIRS for s in p if (SETS[g["set"]] is None or p[0] in SETS[g["set"]])]
    cols = [c for c in (_col(D, s) for s in names) if c is not None]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = C / _shift(C) - 1
    if g["reb"] == "week":
        reb = np.r_[True, dates.isocalendar().week.to_numpy()[1:] != dates.isocalendar().week.to_numpy()[:-1]]
    else:
        reb = np.r_[True, dates.month[1:] != dates.month[:-1]]
    out = np.zeros(T)
    paths: list = []
    w = np.zeros(0)
    live: list[int] = []
    fee = 0.0 if gross else LEV_FEE * fee_mult / 252
    for t in range(1, T):
        if reb[t]:
            if rng is not None:
                liq = np.flatnonzero(D["valid"][t - 1] & (np.nan_to_num(np.asarray(D["DV1"], float)[t]) >= 50e6))
                live = [int(x) for x in rng.choice(liq, min(len(cols), len(liq)), replace=False)] if len(liq) else []
            else:
                live = [c for c in cols if D["valid"][t - 1, c]]
            w = np.full(len(live), 1.0 / max(len(live), 1))
            if live and not gross:
                out[t] -= 0.0005 * spread * 2
            if live:
                paths.append((t, np.zeros(1), 0.0, 1.0))
        if not live:
            continue
        if g["vix"] == "v30" and np.isfinite(X["vix"][t]) and X["vix"][t] > 30:
            continue
        rr = np.nan_to_num(r[t, live])
        out[t] += float(np.sum(w * (-rr))) - fee * float(np.sum(w))
        w = w * (1 + rr)
    return pd.Series(out, index=dates), paths, np.ones(len(paths), bool)
