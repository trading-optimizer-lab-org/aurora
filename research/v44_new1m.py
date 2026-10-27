"""v44 part N: fifteen new one-minute families on small caps (V44_PREREGISTRATION.md section 2): news and filings by
the minute, BTC lead-lag, sympathy, the leveraged-ETF close, z-scores to VWAP, change points, fractal measures, a
Kalman trend, log-periodic power laws, the short-sale rule, rotation, bar flow, squeezes and halts with news.

Stores: event (v14), liquid (v23), mover (v24), filing (v44); scopes as v24 plus ``mover`` (both gap signs),
``filing`` and ``any`` (every store, a symbol-day once). One trade per configuration and symbol-day (the first
signal); entries at the open of the bar after the signal bar. The signals of a family are computed in batches that
share their costly arrays (``feature keys``); a configuration then only adds its stop, exit, context and band.
"""
from __future__ import annotations

import re
from itertools import product

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20
from aurora.research import v22_intra as v22i
from aurora.research import v24_fast as fast
from aurora.research import v24_long1m as v24
from aurora.research import v44_stats as st

B3 = ("1-3", "3-8", "8-20")
CTX5 = ("none", "hot", "cold", "news", "nonews")
CTX3 = ("none", "hot", "cold")
STOP3 = ("pct5", "pct10", "ext")
EX5 = ("t15", "t30", "t60", "close", "d3")
EX7 = ("t5", "t15", "t30", "t60", "close", "next_open", "d3")
NEWS_CLASSES = ("priced", "offering", "rsplit", "fda", "trial", "merger", "contract", "earnings", "buzz", "buyback")
NEWS_RE = {
    "priced": r"\b(priced|prices|pricing)\b.*\boffering",
    "offering": r"offering|private placement|registered direct|at-the-market|\batm\b|warrant (exercise|inducement)"
                r"|\bshelf\b",
    "rsplit": r"reverse (stock )?split",
    "fda": r"\bfda\b|approval|approves|clearance|510\(k\)|breakthrough (therapy )?designation|orphan drug|pdufa",
    "trial": r"phase (1|2|3|i|ii|iii)\b|\btrial\b|topline|data readout|clinical",
    "merger": r"merger|acquire|acquisition|definitive agreement|buyout|takeover|tender offer",
    "contract": r"contract|\border\b|partnership|agreement|collaborat|\baward",
    "earnings": r"earnings|results|revenue|\beps\b|quarter|fiscal",
    "buzz": r"bitcoin|crypto|blockchain|ethereum|\bai\b|artificial intelligence|quantum|treasury reserve",
    "buyback": r"buyback|repurchase|insider (buy|purchas)",
}
FORMS = ("424B", "S1", "S3", "EFFECT", "K101", "K202", "K301", "K302", "K502", "K801", "SC13D", "SC13G", "K6")
SC4 = ("gapup", "runner", "mover", "liquid")

INTRA_DIMS: dict[str, dict] = {
    "NW_NEWS": {"scope": ("any",), "cls": ("any",) + NEWS_CLASSES, "when": ("pre", "intra"), "delay": (0, 2, 5),
                "side": (1, -1), "move": ("none", "with5", "against"), "stop": ("pct5", "pct10", "pct20"),
                "exit": EX7, "ctx": CTX3, "band": B3},
    "ED_EDGAR": {"scope": ("any",), "form": FORMS, "when": ("pre", "intra"), "delay": (0, 2, 5), "side": (1, -1),
                 "move": ("none", "up5", "up20"), "stop": ("pct5", "pct10", "pct20"), "exit": EX7, "ctx": CTX3,
                 "band": B3},
    "BC_BTC": {"scope": ("liquid", "any"), "corr": (0.3, 0.5), "k": (1, 5, 15), "z": (2.0, 3.0, 4.0),
               "lag": ("any", "lag"), "side": ("with", "against"), "window": ("open60", "all"),
               "stop": ("pct3", "pct5", "pct10"), "exit": ("t5", "t15", "t30", "t60", "close"), "ctx": CTX5,
               "band": B3},
    "SY_SYMPATHY": {"scope": ("any",), "group": (4, 3, 2), "lead": (0.2, 0.4), "event": ("hod", "vwaploss"),
                    "peer": ("lag", "run"), "side": ("follow", "fade"), "stop": ("pct5", "pct10", "pct20"),
                    "exit": EX5, "ctx": CTX5, "band": B3},
    "LV_LEVETF": {"scope": ("liquid", "any"), "at": (360, 375, 380), "iwm": (0.005, 0.01, 0.015, 0.02),
                  "side": ("with", "against"), "beta": ("any", "b1"), "same": ("any", "same"),
                  "exit": ("close", "next_open"), "stop": ("pct5", "pct10"), "ctx": CTX5, "band": B3},
    "ZV_ZSCORE": {"scope": ("runner", "mover_up", "mover_dn", "liquid"), "clock": ("time", "vol1"),
                  "sd": ("sess", "roll60"), "z": (2.0, 3.0, 4.0), "confirm": ("none", "rev", "dry"), "side": (-1, 1),
                  "ext": (0.0, 0.2), "stop": STOP3, "exit": ("tovwap", "t15", "t30", "close", "next_open"),
                  "ctx": CTX5, "band": B3},
    "CP_BOCPD": {"scope": SC4, "hazard": (30, 120), "thr": (0.3, 0.6), "run": (0.1, 0.2, 0.4), "side": (-1, 1),
                 "confirm": ("none", "vwap"), "stop": STOP3, "exit": EX5, "ctx": CTX5, "band": B3},
    "HU_FRACTAL": {"scope": SC4, "measure": ("vr30", "vr60", "pe60"), "thr": (0, 1), "run": (0.1, 0.2, 0.4),
                   "side": ("fade", "follow"), "confirm": ("none", "rev"), "stop": STOP3, "exit": EX5, "ctx": CTX5,
                   "band": B3},
    "KF_KALMAN": {"scope": SC4, "qr": (0.001, 0.01, 0.1), "sig": ("flip", "k1", "k2"), "run": (0.1, 0.3),
                  "side": ("fade", "follow"), "filter": ("none", "vwap"), "stop": STOP3, "exit": EX5 + ("kflip",),
                  "ctx": CTX5, "band": B3},
    "LP_LPPL": {"scope": ("runner", "any"), "window": (60, 120, 0), "rise": (0.4, 0.8), "r2": (0.85, 0.95),
                "horizon": (15, 30), "confirm": ("none", "red"), "stop": ("pct10", "pct20", "ext"), "exit": EX5,
                "ctx": CTX5, "band": B3},
    "SS_SSR": {"scope": ("mover_dn", "gapdown", "liquid", "any"), "trig": ("day1", "day2"),
               "setup": ("g5", "vwapre", "lh", "lowbrk"), "window": (60, 0), "stop": STOP3,
               "exit": ("t15", "t30", "t60", "close", "next_open"), "ctx": CTX5, "band": B3},
    "RO_ROTATION": {"scope": ("gapup", "runner", "mover_up", "liquid", "filing"), "rot": (0.5, 1.0, 2.0, 4.0),
                    "state": ("hod", "off10", "under"), "side": (1, -1), "time": (90, 0), "stop": STOP3, "exit": EX5,
                    "ctx": CTX5, "band": B3},
    "FB_FLOWBAR": {"scope": SC4, "win": (5, 15, 30), "imb": (0.3, 0.5), "pattern": ("absorb", "cont"),
                   "side": ("with", "against"), "run": (0.0, 0.1, 0.3), "stop": STOP3, "exit": EX5, "ctx": CTX5,
                   "band": B3},
    "SQ_SQUEEZE": {"scope": ("gapup", "runner", "mover_up", "liquid"), "si": (0.1, 0.2, 0.3), "dtc": (0, 3),
                   "rot": (0.5, 1.0, 2.0), "trig": ("hod", "orb15", "vwapre"), "stop": ("pct5", "pct10", "vwap"),
                   "exit": ("trail10", "t30", "t60", "close", "d3"), "ctx": CTX5, "band": B3},
    "HN_HALTNEWS": {"scope": ("any",), "dir": (1, -1), "drop": (0.10, 0.15), "news": ("yes", "no"), "side": (1, -1),
                    "entry": ("resume", "turn"), "stop": ("pct5", "pct10", "pct20"),
                    "exit": ("t15", "t30", "close", "next_open"), "ctx": CTX3, "band": B3},
}
CONFIG_DIMS = ("stop", "exit", "ctx", "band")  # the rest is the signal key
FEATURE_DIMS = {"ZV_ZSCORE": ("clock", "sd"), "CP_BOCPD": ("hazard",), "HU_FRACTAL": ("measure",),
                "KF_KALMAN": ("qr",), "LP_LPPL": ("window",), "FB_FLOWBAR": ("win",), "SY_SYMPATHY": ("group",)}
HU_THR = {"vr30": (0.8, 0.6), "vr60": (0.8, 0.6), "pe60": (0.95, 0.98)}
NONE = (-1, np.nan, np.nan, 0)
LAST = vi.LAST_ENTRY  # 15:00

X: dict = {}  # the v44 extras (prepare)


def counts() -> dict[str, int]:
    return {k: int(np.prod([len(v) for v in d.values()])) for k, d in INTRA_DIMS.items()}


def sig_key(family: str, g: dict) -> tuple:
    return tuple((k, g[k]) for k in INTRA_DIMS[family] if k not in CONFIG_DIMS)


def feat_key(family: str, g: dict) -> tuple:
    return (family, g["scope"]) + tuple(g[k] for k in FEATURE_DIMS.get(family, ()))


def sig_keys(family: str, fk: tuple) -> list[tuple]:
    dims = {k: v for k, v in INTRA_DIMS[family].items() if k not in CONFIG_DIMS}
    out = []
    for vals in product(*dims.values()):
        g = dict(zip(dims, vals))
        if feat_key(family, g) == fk:
            out.append(tuple(g.items()))
    return out


# ---------------------------------------------------------------- the extras

def news_class(headline: str) -> int:
    h = str(headline).lower()
    for k, name in enumerate(NEWS_CLASSES):
        if re.search(NEWS_RE[name], h):
            return k
    return len(NEWS_CLASSES)


def form_codes(form: str, items: str) -> list[int]:
    f = str(form)
    if f.startswith("424B"):
        return [FORMS.index("424B")]
    if f in ("S-1", "S-1/A", "F-1", "F-1/A"):
        return [FORMS.index("S1")]
    if f in ("S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A"):
        return [FORMS.index("S3")]
    if f == "EFFECT":
        return [FORMS.index("EFFECT")]
    if f == "6-K":
        return [FORMS.index("K6")]
    if "13D" in f:
        return [FORMS.index("SC13D")]
    if "13G" in f:
        return [FORMS.index("SC13G")]
    if f == "8-K":
        its = {x.strip() for x in str(items).split(",")}
        return [FORMS.index(k) for k, i in (("K101", "1.01"), ("K202", "2.02"), ("K301", "3.01"), ("K302", "3.02"),
                                            ("K502", "5.02"), ("K801", "8.01")) if i in its]
    return []


def event_index(ev: pd.DataFrame, code_col: str) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
    """(t, j) -> (minutes, codes), sorted by minute (-1: a pre event)."""
    out: dict = {}
    if ev.empty:
        return out
    ev = ev.sort_values(["t", "j", "minute"], kind="stable")
    for (t, j), g in ev.groupby(["t", "j"], sort=False):
        out[(int(t), int(j))] = (g["minute"].to_numpy(int), g[code_col].to_numpy(int))
    return out


def hot_days(D: dict) -> np.ndarray:
    """+1 hot, -1 cold, 0 between: the day's count of small caps gapping 20% or more at the open against the
    terciles of the 60 sessions before."""
    O, C, P1, DV1, ok = (np.asarray(D[k], float) if k != "valid1" else np.asarray(D[k], bool)
                         for k in ("O", "C", "P1", "DV1", "valid1"))
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = O[1:] / C[:-1] - 1
        small = ok[1:] & (P1[1:] >= 1) & (P1[1:] <= 20) & (DV1[1:] >= 5e5)
    n = np.r_[0.0, ((gap >= 0.2) & small).sum(axis=1)]
    s = pd.Series(n)
    lo = s.shift(1).rolling(60, min_periods=40).quantile(1 / 3).to_numpy()
    hi = s.shift(1).rolling(60, min_periods=40).quantile(2 / 3).to_numpy()
    return np.where(np.isfinite(hi) & (n >= hi), 1, np.where(np.isfinite(lo) & (n <= lo), -1, 0))


def rolling_beta(y: np.ndarray, x: np.ndarray, w: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """(correlation, beta) of each column of y (T x N daily returns) with x (T) over the w sessions before each row."""
    ok = np.isfinite(y) & np.isfinite(x)[:, None]
    Y, Xm = np.where(ok, y, 0.0), np.where(ok, x[:, None], 0.0)

    def roll(a: np.ndarray) -> np.ndarray:
        cs = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0)
        r = np.full_like(a, np.nan, dtype=float)
        r[w:] = cs[w:-1] - cs[:-w - 1]  # rows t: the w rows before t
        return r

    n = roll(ok.astype(float))
    sx, sy, sxx, syy, sxy = roll(Xm), roll(Y), roll(Xm * Xm), roll(Y * Y), roll(Xm * Y)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - sx / n * sy / n
        vx, vy = sxx / n - (sx / n) ** 2, syy / n - (sy / n) ** 2
        corr = np.where(n >= w * 0.8, cov / np.sqrt(vx * vy), np.nan)
        beta = np.where(n >= w * 0.8, cov / vx, np.nan)
    return corr.astype(np.float32), beta.astype(np.float32)


def minute_closes(df: pd.DataFrame, D: dict, offset: int) -> np.ndarray:
    """(session, 390) closes of the regular minutes, forward filled; ``offset``: the frame's minute of 09:30."""
    T = len(D["dates"])
    out = np.full((T, 390), np.nan, np.float32)
    row = {d: t for t, d in enumerate(D["dates"])}
    for d, g in df.groupby("date"):
        t = row.get(pd.Timestamp(d))
        if t is None:
            continue
        m = g["minute"].to_numpy(int) - offset
        ok = (m >= 0) & (m < 390)
        out[t, m[ok]] = g["c"].to_numpy(float)[ok]
    return pd.DataFrame(out.T).ffill().to_numpy(np.float32).T


def prepare(stores: dict, D: dict, extras: dict) -> None:
    """The v44 extras: news and filing events, hot and cold days, BTC and IWM minutes, correlations and betas,
    SIC codes, short interest (``extras`` from run_v44n.load)."""
    v24.prepare(stores, D)
    X.clear()
    X.update(extras)
    X["hot"] = hot_days(D)
    C = np.asarray(D["C"], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = C[1:] / C[:-1] - 1
    r = np.vstack([np.full((1, C.shape[1]), np.nan), r])
    used = sorted({int(j) for s in stores.values() for j in s.cands["j"]})
    X["used"] = np.array(used, int)
    pos = np.full(C.shape[1], -1)
    pos[used] = np.arange(len(used))
    X["upos"] = pos
    for name, key in (("btc_day", "btc"), ("iwm_day", "iwm")):
        if name in extras:
            corr, beta = rolling_beta(r[:, used], np.asarray(extras[name], float))
            X[f"corr_{key}"], X[f"beta_{key}"] = corr, beta
    DV1 = np.asarray(D["DV1"], float)
    for st_ in stores.values():
        c = st_.cands
        with np.errstate(invalid="ignore", divide="ignore"):
            st_.cols["adv"] = DV1[c["t"].to_numpy(int), c["j"].to_numpy(int)] / c["pc"].to_numpy(float)
        if "so" not in st_.cols:
            st_.cols["so"] = c["so"].to_numpy(float) if "so" in c else np.full(len(c), np.nan)


def _px(arr_name: str, t: int, j: int) -> float:
    a = X.get(arr_name)
    p = X["upos"][j] if "upos" in X else -1
    if a is None or p < 0:
        return np.nan
    return float(a[t, p])


def news_before(t: int, j: int, minute: int) -> bool:
    """A news item in the 24 hours before the entry minute (the session before from that minute, the pre events and
    the intra events before it)."""
    nw = X.get("news", {})
    a = nw.get((t, j))
    if a is not None and (a[0] < max(minute, 0)).any():
        return True
    b = nw.get((t - 1, j))
    return b is not None and (b[0] >= minute).any()


def ctx_ok(ctx: str, t: int, j: int, minute: int) -> bool:
    if ctx == "none":
        return True
    if ctx in ("hot", "cold"):
        return int(X["hot"][t]) == (1 if ctx == "hot" else -1)
    has = news_before(t, j, minute)
    return has if ctx == "news" else not has


# ---------------------------------------------------------------- candidates

SCOPE_STORES = {"liquid": ("liquid",), "mover_up": ("mover",), "mover_dn": ("mover",), "mover": ("mover",),
                "filing": ("filing",), "any": ("event", "liquid", "mover", "filing"), "gapup": ("event",),
                "runner": ("event",), "gapdown": ("event",), "day2": ("event",)}
_IDX: dict = {}


def candidates(stores: dict, scope: str) -> list[tuple[str, int]]:
    if scope not in _IDX:
        out, seen = [], set()
        for nm in SCOPE_STORES[scope]:
            if nm not in stores:
                continue
            c = stores[nm].cands
            if scope in v24.EVENT_COL:
                mask = c[v24.EVENT_COL[scope]].to_numpy(bool)
            elif scope == "mover_up":
                mask = c["gap"].to_numpy() > 0
            elif scope == "mover_dn":
                mask = c["gap"].to_numpy() < 0
            else:
                mask = np.ones(len(c), bool)
            for i, t, j in zip(np.flatnonzero(mask), c["t"].to_numpy(int)[mask], c["j"].to_numpy(int)[mask]):
                if scope == "any":
                    if (t, j) in seen:
                        continue
                    seen.add((t, j))
                out.append((nm, int(i)))
        _IDX[scope] = out
    return _IDX[scope]


def _live(b: tuple, cd: dict, scope: str, last: int = LAST) -> np.ndarray:
    live = b[0] <= last
    if scope == "runner":
        live &= v22i.risen(b[2], float(cd["pc"]))
    return live


def _next(k: int, b: tuple, live: np.ndarray, side: int) -> tuple:
    """Entry at the open of the bar after signal bar k."""
    if k < 0 or k + 1 >= len(b[0]) or not live[k]:
        return NONE
    return k + 1, float(b[1][k + 1]), np.nan, side


def _first(mask: np.ndarray) -> int:
    k = np.flatnonzero(mask)
    return int(k[0]) if len(k) else -1


def _run_dir(b: tuple, op: float, run: float) -> np.ndarray:
    """+1 where the high so far is at least ``run`` over the open (and the low not as far under), -1 the reverse."""
    up = np.maximum.accumulate(b[2]) / op - 1
    dn = 1 - np.minimum.accumulate(b[3]) / op
    return np.where((up >= run) & (up >= dn), 1, np.where((dn >= run) & (dn > up), -1, 0))


# ---------------------------------------------------------------- the signals (a batch shares a feature key)

def _events_signal(g: dict, cd: dict, b: tuple, kind: str) -> tuple:
    t, j = int(cd["t"]), int(cd["j"])
    ev = X.get(kind, {}).get((t, j))
    if ev is None:
        return NONE
    mins, codes = ev
    code = g.get("cls", g.get("form"))
    if kind == "news":
        sel = np.ones(len(codes), bool) if code == "any" else codes == NEWS_CLASSES.index(code)
    else:
        sel = codes == FORMS.index(code)
    m, o, c = b[0], b[1], b[4]
    side, d = int(g["side"]), int(g["delay"])
    if g["when"] == "pre":
        if not (sel & (mins < 0)).any():
            return NONE
        k = _first(m >= d)
        ref = float(cd["pc"])
    else:
        ok = sel & (mins >= 0) & (mins <= LAST - d - 1)
        if not ok.any():
            return NONE
        mm = int(mins[ok][0])
        k = _first(m >= mm + 1 + d)
        before = np.flatnonzero(m <= mm)
        ref = float(c[before[-1]]) if len(before) else float(o[0])
    if k < 0 or m[k] > LAST:
        return NONE
    e = float(o[k])
    mv = g["move"]
    if mv == "with5" and not side * (e / ref - 1) >= 0.05:
        return NONE
    if mv == "against" and not side * (e / ref - 1) <= 0:
        return NONE
    if mv in ("up5", "up20") and not e / float(cd["pc"]) - 1 >= (0.05 if mv == "up5" else 0.20):
        return NONE
    return k, e, np.nan, side


def sig_btc(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    t, j = int(cd["t"]), int(cd["j"])
    if not _px("corr_btc", t, j) >= g["corr"]:
        return NONE
    btc, sig = X.get("btc_min"), X.get("btc_sig")
    if btc is None or sig is None:
        return NONE
    k = int(g["k"])
    bt = btc[t]
    s = float(sig[t, (1, 5, 15).index(k)])
    if not np.isfinite(s) or s <= 0:
        return NONE
    m, c = b[0], b[4]
    mm = np.clip(m, 0, 389)
    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.log(bt[mm] / bt[np.maximum(mm - k, 0)])
    trig = (mm >= k) & np.isfinite(R) & (np.abs(R) >= g["z"] * s)
    if g["window"] == "open60":
        trig &= m < 60
    if g["lag"] == "lag":
        beta = _px("beta_btc", t, j)
        if not np.isfinite(beta):
            return NONE
        idx = np.searchsorted(m, m - k, side="right") - 1
        with np.errstate(invalid="ignore", divide="ignore"):
            sk = np.log(c / np.where(idx >= 0, c[np.maximum(idx, 0)], np.nan))
        trig &= np.sign(R) * sk < 0.5 * abs(beta) * np.abs(R)
    kk = _first(trig & (m <= LAST))
    if kk < 0:
        return NONE
    side = int(np.sign(R[kk])) * (1 if g["side"] == "with" else -1)
    return _next(kk, b, m <= LAST, side)


def sig_lev(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    t, j = int(cd["t"]), int(cd["j"])
    iwm, pcs = X.get("iwm_min"), X.get("iwm_pc")
    if iwm is None or pcs is None or not np.isfinite(pcs[t]):
        return NONE
    at = int(g["at"])
    mv = float(iwm[t, at]) / float(pcs[t]) - 1
    if not abs(mv) >= g["iwm"]:
        return NONE
    if g["beta"] == "b1" and not _px("beta_iwm", t, j) >= 1.0:
        return NONE
    m, o, c = b[0], b[1], b[4]
    before = np.flatnonzero(m <= at)
    if not len(before):
        return NONE
    day = float(c[before[-1]]) / float(cd["pc"]) - 1
    if g["same"] == "same" and not np.sign(day) == np.sign(mv):
        return NONE
    k = _first(m >= at + 1)
    if k < 0 or m[k] > 388:
        return NONE
    side = int(np.sign(mv)) * (1 if g["side"] == "with" else -1)
    return k, float(o[k]), np.nan, side


def feat_z(fk: tuple, cd: dict, b: tuple) -> dict:
    _, _, clock, sd = fk
    m, o, h, lo, c, v = b[:6]
    line = vi.vwap(c, v, b[6])
    if clock == "time":
        ends = np.arange(len(c))
        O, C, V = o, c, v
    else:
        size = 0.01 * float(cd.get("adv", np.nan))
        ends = st.volume_bars(b, size)
        if len(ends) < 10:
            return {"none": True}
        starts = np.r_[0, ends[:-1] + 1]
        O, C = o[starts], c[ends]
        V = (m[ends] - np.r_[m[0] - 1, m[ends[:-1]]]).astype(float)  # minutes a volume bar took: long = dry
    z = st.zscore(C, line[ends], sd)
    hi_ = np.maximum.accumulate(h)[ends]
    lo_ = np.minimum.accumulate(lo)[ends]
    return {"ends": ends, "O": O, "C": C, "V": V, "z": z, "hi": hi_, "lo": lo_, "line": line, "clock": clock}


def sig_z(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    if F.get("none"):
        return NONE
    side, op = int(g["side"]), float(cd["open"])
    ends, z = F["ends"], F["z"]
    x = (z >= g["z"]) if side < 0 else (z <= -g["z"])
    if g["ext"] > 0:
        x &= (F["hi"] >= op * (1 + g["ext"])) if side < 0 else (F["lo"] <= op * (1 - g["ext"]))
    if g["confirm"] == "rev":
        x &= (F["C"] < F["O"]) if side < 0 else (F["C"] > F["O"])
    elif g["confirm"] == "dry":
        V = F["V"]
        if F["clock"] == "time":
            x &= V < 0.5 * fast.prev(fast.rmean(V, 10))
        else:
            x &= V > 2 * fast.prev(fast.rmean(V, 10))
    live = _live(b, cd, g["scope"])
    k = _first(x & live[ends])
    return _next(int(ends[k]), b, live, side) if k >= 0 else NONE


def feat_cp(fk: tuple, cd: dict, b: tuple) -> dict:
    if not (_run_dir(b, float(cd["open"]), 0.1) != 0).any():
        return {"none": True}
    cp, mean = st.bocpd(b[4], 1.0 / fk[2])
    return {"cp": cp, "mean": mean, "line": vi.vwap(b[4], b[5], b[6])}


def sig_cp(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    if F.get("none"):
        return NONE
    side = int(g["side"])
    run = _run_dir(b, float(cd["open"]), g["run"])
    x = (run == -side) & (F["cp"] >= g["thr"]) & (np.sign(F["mean"]) == side)
    if g["confirm"] == "vwap":
        x &= side * (b[4] - F["line"]) > 0
    live = _live(b, cd, g["scope"])
    return _next(_first(x & live), b, live, side)


def feat_hu(fk: tuple, cd: dict, b: tuple) -> dict:
    op = float(cd["open"])
    if not (_run_dir(b, op, 0.1) != 0).any():
        return {"none": True}
    meas = fk[2]
    c = b[4]
    val = st.perm_entropy(c, 60) if meas == "pe60" else st.variance_ratio(c, 5, int(meas[2:]))
    return {"val": val}


def sig_hu(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    if F.get("none"):
        return NONE
    thr = HU_THR[g["measure"]][g["thr"]]
    val = F["val"]
    with np.errstate(invalid="ignore"):
        cond = (val > thr) if g["measure"] == "pe60" else (val < thr)
    run = _run_dir(b, float(cd["open"]), g["run"])
    side = np.where(run != 0, -run if g["side"] == "fade" else run, 0)
    x = cond & (side != 0)
    if g["confirm"] == "rev":
        x &= (b[4] - b[1]) * run < 0
    live = _live(b, cd, g["scope"])
    k = _first(x & live)
    return _next(k, b, live, int(side[k])) if k >= 0 else NONE


def feat_kf(fk: tuple, cd: dict, b: tuple) -> dict:
    op = float(cd["open"])
    if not (_run_dir(b, op, 0.1) != 0).any():
        return {"none": True}
    vel = st.alpha_beta(b[4], float(fk[2]))
    return {"vel": vel, "sd": st._expanding_std(vel, 10), "line": vi.vwap(b[4], b[5], b[6])}


def sig_kf(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    if F.get("none"):
        return NONE
    vel, sd = F["vel"], F["sd"]
    run = _run_dir(b, float(cd["open"]), g["run"])
    if g["sig"] == "flip":
        against = (np.sign(vel) == -run) & (np.sign(fast.prev(vel, 0.0)) == run)
    else:
        kk = 1.0 if g["sig"] == "k1" else 2.0
        with np.errstate(invalid="ignore"):
            against = (-run * vel) > kk * sd
    side = np.where(run != 0, -run if g["side"] == "fade" else run, 0)
    x = against & (run != 0)
    if g["filter"] == "vwap":
        x &= side * (b[4] - F["line"]) > 0
    live = _live(b, cd, g["scope"])
    k = _first(x & live)
    return _next(k, b, live, int(side[k])) if k >= 0 else NONE


def feat_lp(fk: tuple, cd: dict, b: tuple) -> dict:
    m, h, c = b[0], b[2], b[4]
    pc = float(cd["pc"])
    risen = np.r_[-np.inf, np.maximum.accumulate(h)[:-1]] / pc - 1
    if not risen.max() >= 0.4:
        return {"none": True}
    window = None if fk[2] == 0 else int(fk[2])
    fits = {}
    for k in np.flatnonzero((m >= 30) & (m % 15 == 0) & (m <= LAST) & (risen >= 0.4)):
        fits[int(k)] = st.lppl(m, c, int(k), window)
    return {"fits": fits, "risen": risen}


def sig_lp(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    if F.get("none"):
        return NONE
    o, c = b[1], b[4]
    live = _live(b, cd, g["scope"])
    for k, (r2, tc) in sorted(F["fits"].items()):
        if not (F["risen"][k] >= g["rise"] and np.isfinite(r2) and r2 >= g["r2"] and tc <= g["horizon"]):
            continue
        if g["confirm"] == "red":
            reds = np.flatnonzero((c[k:k + 11] < o[k:k + 11]))
            if not len(reds):
                continue
            k = k + int(reds[0])
        return _next(k, b, live, -1)
    return NONE


def sig_ssr(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    D = X["D"]
    t, j = int(cd["t"]), int(cd["j"])
    m, o, h, lo, c, v = b[:6]
    pc = float(cd["pc"])
    if g["trig"] == "day1":
        k0 = _first(lo <= 0.9 * pc)
    else:
        L, C = D["L"], D["C"]
        ok = t >= 2 and np.isfinite(L[t - 1, j]) and np.isfinite(C[t - 2, j]) and L[t - 1, j] <= 0.9 * C[t - 2, j]
        k0 = 0 if ok else -1
    if k0 < 0:
        return NONE
    idx = np.arange(len(c))
    win = (idx > k0) & (m <= LAST)
    if g["window"]:
        win &= m <= m[k0] + int(g["window"])
    line = vi.vwap(c, v, b[6])
    s = g["setup"]
    if s == "g5":
        ends, O, _, _, C5, _ = fast.agg(b, 5)
        kk = _first((C5 > O) & win[ends])
        return _next(int(ends[kk]), b, win, 1) if kk >= 0 else NONE
    if s == "vwapre":
        return _next(_first(fast.up_cross(c, line) & win), b, win, 1)
    low_since = np.minimum.accumulate(np.where(idx >= k0, lo, np.inf))
    if s == "lh":
        bounced = np.maximum.accumulate(np.where(idx > k0, h / low_since, 0.0)) >= 1.05
        return _next(_first(bounced & (h < fast.prev(h, np.inf)) & (c < line) & win), b, win, -1)
    prior = fast.prev(low_since, np.inf)
    k = _first((lo < prior) & win & (idx >= k0 + 5))
    if k < 0:
        return NONE
    return k, v19._past(-1, float(o[k]), float(prior[k]), float(lo[k])), np.nan, -1


def sig_rot(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    so = float(cd.get("so", np.nan))
    if not np.isfinite(so) or so <= 0:
        return NONE
    m, o, h, lo, c, v = b[:6]
    pm = float(cd["pmv"]) / max(float(cd["pc"]), 0.01)
    rot = (pm + np.cumsum(v)) / so
    hod = np.maximum.accumulate(h)
    line = vi.vwap(c, v, b[6])
    state = {"hod": c >= 0.98 * hod, "off10": c <= 0.9 * hod, "under": c < line}[g["state"]]
    live = _live(b, cd, g["scope"])
    if g["time"]:
        live &= m < int(g["time"])
    return _next(_first((rot >= g["rot"]) & state & live), b, live, int(g["side"]))


def feat_fb(fk: tuple, cd: dict, b: tuple) -> dict:
    return {"imb": st.bvc_imbalance(b[1], b[4], b[5], int(fk[2]))}


def sig_fb(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    w = int(g["win"])
    imb, c = F["imb"], b[4]
    with np.errstate(invalid="ignore", divide="ignore"):
        chg = c / np.r_[np.full(w, np.nan), c[:-w]] - 1 if len(c) > w else np.full(len(c), np.nan)
    big = np.abs(imb) >= g["imb"]
    if g["pattern"] == "absorb":
        x = big & (np.abs(chg) < 0.01)
    else:
        x = big & (np.sign(imb) * chg >= 0.03)
    if g["run"] > 0:
        x &= _run_dir(b, float(cd["open"]), g["run"]) != 0
    live = _live(b, cd, g["scope"])
    k = _first(x & live)
    if k < 0:
        return NONE
    side = int(np.sign(imb[k])) * (1 if g["side"] == "with" else -1)
    return _next(k, b, live, side) if side else NONE


def sig_sq(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    t, j = int(cd["t"]), int(cd["j"])
    si, dtc = X.get("si_so"), X.get("dtc")
    if si is None or not float(si[t, j]) >= g["si"]:
        return NONE
    if g["dtc"] and not (dtc is not None and float(dtc[t, j]) >= g["dtc"]):
        return NONE
    so = float(cd.get("so", np.nan))
    if not np.isfinite(so) or so <= 0:
        return NONE
    m, o, h, lo, c, v = b[:6]
    rot = (float(cd["pmv"]) / max(float(cd["pc"]), 0.01) + np.cumsum(v)) / so
    live = _live(b, cd, g["scope"])
    line = vi.vwap(c, v, b[6])
    if g["trig"] == "hod":
        x = (h > fast.prev(np.maximum.accumulate(h), np.inf)) & (m >= 30)
    elif g["trig"] == "orb15":
        hi_, _, first = vi.opening_range(m, h, lo, 15)
        if not first or not np.isfinite(hi_):
            return NONE
        x = (h > hi_) & (np.arange(len(m)) >= first)
    else:
        x = fast.up_cross(c, line) & (m >= 5)
    return _next(_first(x & (rot >= g["rot"]) & live), b, live, 1)


def sig_hn(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    m, o, c = b[0], b[1], b[4]
    t, j = int(cd["t"]), int(cd["j"])
    side = int(g["side"])
    for k, d in st.halts(m, c, g["drop"]):
        if d != g["dir"] or k + 1 >= len(m) or m[k + 1] > LAST:
            continue
        if news_before(t, j, int(m[k + 1])) != (g["news"] == "yes"):
            continue
        if g["entry"] == "resume":
            return k + 1, float(o[k + 1]), np.nan, side
        turn = np.flatnonzero(((c[k + 1:] > o[k + 1:]) if side > 0 else (c[k + 1:] < o[k + 1:])))
        if not len(turn):
            return NONE
        kk = k + 1 + int(turn[0])
        return _next(kk, b, m <= LAST, side)
    return NONE


def sympathy_events(stores: dict, digits: int) -> dict[tuple[str, int], list[tuple[int, int, float, int]]]:
    """For every candidate of a day's SIC group (the code's first ``digits``): the leader events of its group as
    (minute, event code 0 hod / 1 vwaploss, the leader's lead at that minute (up from the prior close), the peer's
    state 0 lagging / 1 running). The leader is the group's top gainer at the minute."""
    sic = X.get("sic")
    out: dict = {}
    if sic is None:
        return out
    by_day: dict = {}
    for nm, i in candidates(stores, "any"):
        cols = stores[nm].cols
        code = str(sic[int(cols["j"][i])])[:digits]
        if len(code) == digits and code.isdigit():
            by_day.setdefault((int(cols["t"][i]), code), []).append((nm, i))
    for _, members in by_day.items():
        if len(members) < 2:
            continue
        up = np.full((len(members), 390), np.nan)
        hi = np.full((len(members), 390), np.nan)
        below = np.full((len(members), 390), np.nan)
        for r, (nm, i) in enumerate(members):
            cd, b = v24.row(stores[nm], i), v24.bars(stores[nm], i)
            mm = b[0].astype(int)
            line = vi.vwap(b[4], b[5], b[6])
            pc = float(cd["pc"])
            up[r, mm] = b[4] / pc - 1
            hi[r, mm] = np.maximum.accumulate(b[2]) / pc - 1
            below[r, mm] = (b[4] < line).astype(float)
        up = pd.DataFrame(up.T).ffill().to_numpy().T
        hi = pd.DataFrame(hi.T).ffill().to_numpy().T
        below = pd.DataFrame(below.T).ffill().fillna(0).to_numpy().T > 0
        filled = np.where(np.isnan(up), -np.inf, up)
        lead = np.argmax(filled, axis=0)
        cols = np.arange(390)
        lup = filled[lead, cols]
        prev_hi = np.r_[np.nan, hi[lead[1:], cols[:-1]]]
        new_hi = (hi[lead, cols] > prev_hi) & (lead == np.r_[-1, lead[:-1]])
        was_up = np.r_[False, (lup[:-1] > 0) & ~below[lead[1:], cols[:-1]]]
        lost = below[lead, cols] & was_up & (lead == np.r_[-1, lead[:-1]])
        for ev, mask in ((0, new_hi), (1, lost)):
            for mnt in np.flatnonzero(mask & (cols <= LAST - 1)):
                L = int(lead[mnt])
                for r, key in enumerate(members):
                    if r == L or not np.isfinite(up[r, mnt]):
                        continue
                    out.setdefault(key, []).append((int(mnt), ev, float(lup[mnt]), int(up[r, mnt] >= 0.10)))
    return out


def sig_sy(g: dict, cd: dict, b: tuple, F: dict) -> tuple:
    evs = F.get("events", [])
    code = 0 if g["event"] == "hod" else 1
    peer = 0 if g["peer"] == "lag" else 1
    for mnt, ev, lup, state in evs:
        if ev == code and lup >= g["lead"] and state == peer:
            k = _first(b[0] >= mnt + 1)
            if k < 0 or b[0][k] > LAST:
                return NONE
            side = (1 if code == 0 else -1) * (1 if g["side"] == "follow" else -1)
            return k, float(b[1][k]), np.nan, side
    return NONE


FEATURES = {"ZV_ZSCORE": feat_z, "CP_BOCPD": feat_cp, "HU_FRACTAL": feat_hu, "KF_KALMAN": feat_kf, "LP_LPPL": feat_lp,
            "FB_FLOWBAR": feat_fb}
SIGNALS = {"BC_BTC": sig_btc, "LV_LEVETF": sig_lev, "ZV_ZSCORE": sig_z, "CP_BOCPD": sig_cp, "HU_FRACTAL": sig_hu,
           "KF_KALMAN": sig_kf, "LP_LPPL": sig_lp, "SS_SSR": sig_ssr, "RO_ROTATION": sig_rot, "FB_FLOWBAR": sig_fb,
           "SQ_SQUEEZE": sig_sq, "HN_HALTNEWS": sig_hn, "SY_SYMPATHY": sig_sy}
_BATCH: dict = {}


def batch(stores: dict, family: str, g: dict) -> list[tuple[str, int, int, float, int]]:
    """The signals (store, row, entry bar, entry price, side) of a configuration's signal key, computed for its whole
    feature key at once."""
    fk = feat_key(family, g)
    if fk not in _BATCH:
        if len(_BATCH) >= 2:
            _BATCH.clear()
        sks = sig_keys(family, fk)
        out: dict = {sk: [] for sk in sks}
        sym = sympathy_events(stores, int(g["group"])) if family == "SY_SYMPATHY" else None
        for nm, i in candidates(stores, g["scope"]):
            s_ = stores[nm]
            cd = v24.row(s_, i)
            key = (int(cd["t"]), int(cd["j"]))
            if (family == "NW_NEWS" and key not in X.get("news", {})) or \
                    (family == "ED_EDGAR" and key not in X.get("edgar", {})):
                continue
            b = v24.bars(s_, i)
            if len(b[0]) < 30:
                continue
            if sym is not None:
                F = {"events": sym.get((nm, i), [])}
                if not F["events"]:
                    continue
            elif family in FEATURES:
                F = FEATURES[family](fk, cd, b)
            else:
                F = {}
            for sk in sks:
                gg = dict(sk)
                if family in ("NW_NEWS", "ED_EDGAR"):
                    r = _events_signal(gg, cd, b, "news" if family == "NW_NEWS" else "edgar")
                else:
                    r = SIGNALS[family](gg, cd, b, F)
                if r[0] >= 0 and np.isfinite(r[1]) and r[1] > 0:
                    out[sk].append((nm, i, int(r[0]), float(r[1]), int(r[3])))
        _BATCH[fk] = out
    return _BATCH[fk][sig_key(family, g)]


# ---------------------------------------------------------------- stops, exits, trades

def stop_of(rule: str, b: tuple, k: int, e: float, side: int) -> float:
    if rule.startswith("pct"):
        return e * (1 - side * int(rule[3:]) / 100)
    if rule == "ext":  # the extreme of the bars before the entry bar (and the entry itself)
        if side < 0:
            return max(float(np.max(b[2][:k])) if k > 0 else e, e) * 1.01
        return min(float(np.min(b[3][:k])) if k > 0 else e, e) * 0.99
    if rule == "vwap":  # SQ: 1% under VWAP of the bar before the entry
        if k < 1:
            return np.nan
        s = float(vi.vwap(b[4], b[5], b[6])[k - 1]) * 0.99
        return s if s < e else np.nan
    raise KeyError(rule)


def make_trade(D: dict, family: str, g: dict, cd: dict, b: tuple, k: int, e: float, side: int, prio: float) -> dict:
    stop = stop_of(g["stop"], b, k, e, side)
    line = vi.vwap(b[4], b[5], b[6])
    ex = g["exit"]
    if ex in ("tovwap", "kflip"):
        xm = np.zeros(len(b[0]), bool)
        if ex == "kflip":
            vel = st.alpha_beta(b[4], float(g["qr"]))
            xm = (vel > 0) if side < 0 else (vel < 0)
        return v22i.mask_row(D, cd, b, line, side, k, e, stop, xm, ex, prio)
    return v19.trade_row(D, cd, b, line, side, k, e, stop, ex, prio)


def trades(stores: dict, D: dict, family: str, g: dict) -> pd.DataFrame:
    rows, keep = [], []
    for nm, i, k, e, side in batch(stores, family, g):
        cols = stores[nm].cols
        t, j = int(cols["t"][i]), int(cols["j"][i])
        if not v20.in_band(pd.Series([float(cols["open"][i])]), g["band"]).iloc[0]:
            continue
        b = v24.bars(stores[nm], i)
        if not ctx_ok(g["ctx"], t, j, int(b[0][k])):
            continue
        stop = stop_of(g["stop"], b, k, e, side)
        if not np.isfinite(stop) or (stop - e) * side >= 0:
            continue
        keep.append((pd.Timestamp(cols["date"][i]), int(b[0][k]), -abs(float(cols["gap"][i])), nm, i, k, e, side))
    keep.sort(key=lambda x: (x[0], x[1], x[2]))
    per_day: dict = {}
    for d, _, negp, nm, i, k, e, side in keep:  # the book takes the first five a day by minute and priority
        if per_day.get(d, 0) >= 5:
            continue
        per_day[d] = per_day.get(d, 0) + 1
        cd, b = v24.row(stores[nm], i), v24.bars(stores[nm], i)
        rows.append(make_trade(D, family, g, cd, b, k, e, side, -negp))
    return pd.DataFrame(rows, columns=v19.COLS)


def pool_by_day(stores: dict, g: dict) -> dict:
    out: dict = {}
    for nm, i in candidates(stores, g["scope"]):
        cols = stores[nm].cols
        if v20.in_band(pd.Series([float(cols["open"][i])]), g["band"]).iloc[0]:
            out.setdefault(pd.Timestamp(cols["date"][i]), []).append((nm, i))
    return out


def placebo(stores: dict, by_day: dict, D: dict, family: str, g: dict, real: pd.DataFrame,
            rng: np.random.Generator) -> pd.DataFrame:
    """Each real trade moved to a random candidate of its scope and band that day: the same minute (that bar's
    open), side, stop distance and exit."""
    rows = []
    for r in real.itertuples(index=False):
        ch = by_day.get(pd.Timestamp(r.date), [])
        if not ch:
            continue
        nm, i = ch[int(rng.integers(len(ch)))]
        cd, b = v24.row(stores[nm], i), v24.bars(stores[nm], i)
        if len(b[0]) < 30:
            continue
        k = int(np.searchsorted(b[0], r.minute))
        if k >= len(b[0]) or b[0][k] > 389:
            continue
        e = float(b[1][k])
        side = int(r.side)
        dist = abs(r.entry - r.stop) / r.entry
        stop = e * (1 + dist) if side < 0 else e * (1 - dist)
        line = vi.vwap(b[4], b[5], b[6])
        if g["exit"] in ("tovwap", "kflip"):
            xm = np.zeros(len(b[0]), bool)
            if g["exit"] == "kflip":
                vel = st.alpha_beta(b[4], float(g["qr"]))
                xm = (vel > 0) if side < 0 else (vel < 0)
            rows.append(v22i.mask_row(D, cd, b, line, side, k, e, stop, xm, g["exit"], float(r.prio)))
        else:
            rows.append(v19.trade_row(D, cd, b, line, side, k, e, stop, g["exit"], float(r.prio)))
    return pd.DataFrame(rows, columns=v19.COLS)
