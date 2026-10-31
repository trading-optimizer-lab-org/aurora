"""v51 engine (docs/research/V51_PREREGISTRATION.md): entries, exits, fills and TZC costs on one-minute timelines, the
filter cells and grid sums, the account and the one-year bootstrap. Pure numpy; scripts/run_v51.py feeds it.

A timeline holds the minute bars of the event day and the next K-1 sessions (minute 0 = 04:00 ET, 960 a day) and the
daily bars of days 0..ND-1 (day 0 = the event day). Prices are split-adjusted. Every rule reads only bars before the
minute it acts in.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

NM, ND = 960, 12
OPEN, LAST, AH = 330, 719, 720
M0945, M1030, M1200, M1550, M1555 = 345, 390, 480, 710, 715
PM_END, AH_FIRST = 328, 721

# half-spreads by price tier (<2, 2-5, 5-10, 10-20) and leg: open, session, last minutes (R4, v22), extended (1.5x
# v26's measured), passive (resting limit: none)
R4 = np.array([[0.006633, 0.004728, 0.005763], [0.008026, 0.003602, 0.004782], [0.008188, 0.003977, 0.004642],
               [0.009853, 0.005096, 0.004473]])
EXT = 1.5 * np.array([0.0046, 0.0041, 0.0025, 0.0018])
HALF = np.hstack([R4, EXT[:, None], np.zeros((4, 1))])
L_OPEN, L_SESS, L_CLOSE, L_EXT, L_PASS = range(5)
COMM, COMM_MIN, COMM_MAX = 0.005, 0.49, 7.95
SEC, TAF, REP, REP_MIN = 0.0000206, 0.000249, 0.00005, 0.01
LOC = (0.0, 0.01, 0.03)  # a share, by tier ETB, HTB, HOT
MARGIN, FLOOR, REF = 0.09, 0.50, 1_000.0
UNAVAIL = {1: 0.10, 2: 0.50}

TIMES = ("d0c", "d1o", "d1pm", "d1m", "d1c", "d2c", "d3c", "d5c", "d10c")
TGTS = (0.0, 0.25, 0.50)
STOPS = (0.0, 0.25, 1.00)
EXITS = [(ti, gi, si) for ti in range(len(TIMES)) for gi in range(len(TGTS)) for si in range(len(STOPS))]
NX = len(EXITS)

# entries: name -> (data class, kind, day, parameter); classes 0 FREE, 1 IEX, 2 PAID
CLOSE_ENTRIES = {
    "c_1555": (0, "mkt", 0, M1555), "c_ah0": (0, "lim_ah", 0, 0.0), "c_ah5": (0, "lim_ah", 0, 0.05),
    "c_ah10": (0, "lim_ah", 0, 0.10), "c_pm0": (0, "lim_pm", 1, 0.0), "c_pm5": (0, "lim_pm", 1, 0.05),
    "c_pm10": (0, "lim_pm", 1, 0.10), "c_pm20": (0, "lim_pm", 1, 0.20), "c_open": (0, "auction", 1, 0),
    "c_0945": (0, "mkt", 1, M0945), "c_1030": (0, "mkt", 1, M1030), "c_1200": (0, "mkt", 1, M1200),
    "c_1555b": (0, "mkt", 1, M1555), "c_rl5": (0, "lim_rth", 1, 0.05), "c_rl10": (0, "lim_rth", 1, 0.10),
    "c_rl20": (0, "lim_rth", 1, 0.20), "c_orb": (2, "orb", 1, 0), "c_vwap": (2, "vwap", 1, 0),
    "c_hodf": (2, "hodf", 1, 0)}
OPEN_ENTRIES = {
    "o_0931": (1, "mkt", 0, OPEN + 1), "o_0945": (1, "mkt", 0, M0945), "o_1030": (1, "mkt", 0, M1030),
    "o_1200": (1, "mkt", 0, M1200), "o_1555": (1, "mkt", 0, M1555), "o_orb": (2, "orb", 0, 0),
    "o_vwap": (2, "vwap", 0, 0), "o_hodf": (2, "hodf", 0, 0), "o_ah0": (0, "lim_ah", 0, 0.0),
    "o_ah10": (0, "lim_ah", 0, 0.10), "o_pm0": (0, "lim_pm", 1, 0.0), "o_pm10": (0, "lim_pm", 1, 0.10),
    "o_open1": (0, "auction", 1, 0)}
RUN_ENTRIES = {
    "r_t0": (2, "rt", 0, 1), "r_t15": (2, "rt", 0, 16), "r_t60": (2, "rt", 0, 61), "r_hodf": (2, "rhodf", 0, 0),
    "r_1555": (1, "r1555", 0, M1555), "r_ah0": (0, "lim_ah", 0, 0.0), "r_pm0": (0, "lim_pm", 1, 0.0),
    "r_open1": (0, "auction", 1, 0)}


SETUPS = {  # name -> (when decided, strength thresholds; negative: a fall)
    "RUNUP": ("close", (2.5, 3.0, 4.0, 6.0)), "STRONG": ("close", (0.30, 0.50, 1.00, 2.00)),
    "FADE": ("close", (0.30, 0.50, 1.00, 2.00)), "CRASH": ("close", (-0.20, -0.30, -0.50, -0.70)),
    "GAPUP": ("open", (0.20, 0.30, 0.50, 1.00)), "GAPDN": ("open", (-0.15, -0.25, -0.40, -0.60)),
    "RUN40": ("run", (0.40,)), "RUN60": ("run", (0.60,)), "RUN100": ("run", (1.00,)), "RUN200": ("run", (2.00,))}
ENTRIES = {"close": CLOSE_ENTRIES, "open": OPEN_ENTRIES, "run": RUN_ENTRIES}


def strength(setup: str, x) -> np.ndarray:
    """The highest threshold the setup's value passes (0-3), -1 when none."""
    thr = np.array(SETUPS[setup][1])
    x = np.asarray(x, float)[..., None]
    with np.errstate(invalid="ignore"):
        ok = (x <= thr) if thr[0] < 0 else (x >= thr)
    return ok.sum(-1) - 1


def setup_value(setup: str, O, H, L, C, pc, low5) -> tuple[np.ndarray, np.ndarray]:
    """(value, extra condition) of a setup from a day's bars: RUNUP close / five-session low, STRONG and CRASH the
    close's change, FADE the open's change with the close 10% under the open in the range's low quarter, GAPUP and
    GAPDN the open's change, RUN the high's change (a candidate: the minute trigger decides)."""
    O, H, L, C, pc, low5 = (np.asarray(a, float) for a in (O, H, L, C, pc, low5))
    yes = np.ones(np.broadcast(O, C).shape, bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        if setup == "RUNUP":
            return C / low5, yes
        if setup in ("STRONG", "CRASH"):
            return C / pc - 1, yes
        if setup == "FADE":
            return O / pc - 1, (C <= 0.9 * O) & (C - L <= 0.25 * (H - L))
        if setup in ("GAPUP", "GAPDN"):
            return O / pc - 1, yes
        return H / pc - 1, yes


def candidate(setup: str, O, H, L, pc, low5) -> np.ndarray:
    """A day bound that every minute of the session must pass for a close setup to hold at any minute (so the 15:49
    check never depends on the close); the daily value itself for the others."""
    O, H, L, pc, low5 = (np.asarray(a, float) for a in (O, H, L, pc, low5))
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"RUNUP": H / low5 >= 2.5, "STRONG": H / pc >= 1.3, "FADE": O / pc >= 1.3,
                "CRASH": L / pc <= 0.8}.get(setup, np.zeros(O.shape, bool))


def at_1549(tl: "Timeline", setup: str, low4: float) -> int:
    """A close setup's strength on the regular-session bars to 15:49 (the 15:55 entry's decision), -1 when none."""
    c = tl.c[0, OPEN:M1550]
    ok = np.flatnonzero(np.isfinite(c))
    if not len(ok):
        return -1
    x, hi, lo = c[ok[-1]], np.nanmax(tl.h[0, OPEN:M1550]), np.nanmin(tl.l[0, OPEN:M1550])
    val, cond = setup_value(setup, tl.dO[0], hi, lo, x, tl.pc, np.fmin(low4, lo))
    return int(strength(setup, val)) if bool(cond) else -1


def tier_of(price) -> np.ndarray:
    p = np.asarray(price, float)
    return np.select([p < 2, p < 5, p < 10], [0, 1, 2], 3)


def leg_of(minute: int) -> int:
    if minute < OPEN or minute >= AH:
        return L_EXT
    if minute < OPEN + 5:
        return L_OPEN
    return L_CLOSE if minute >= M1555 else L_SESS


@dataclass
class Timeline:
    """Minute bars (K x 960; NaN without a trade) and daily bars (ND) of one event; pc = the event's prior close."""
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    vw: np.ndarray
    dO: np.ndarray
    dH: np.ndarray
    dL: np.ndarray
    dC: np.ndarray
    pc: float

    @property
    def K(self) -> int:
        return self.o.shape[0]

    def flat(self, name: str) -> np.ndarray:
        return getattr(self, name).reshape(-1)


def _first(mask: np.ndarray) -> int:
    k = int(np.argmax(mask)) if len(mask) else 0
    return k if len(mask) and mask[k] else -1


def first_bar(tl: Timeline, day: int, m0: int, m1: int) -> int:
    """The first minute in [m0, m1] of ``day`` with a trade, or -1."""
    if day >= tl.K or m0 > m1:
        return -1
    ok = np.isfinite(tl.o[day, m0:m1 + 1]) & (np.nan_to_num(tl.v[day, m0:m1 + 1]) > 0)
    k = _first(ok)
    return m0 + k if k >= 0 else -1


def prior_close(tl: Timeline, day: int) -> float:
    return tl.pc if day == 0 else float(tl.dC[day - 1])


# ---------------------------------------------------------------- entries

def _mkt(tl: Timeline, day: int, m: int, side: int):
    s = first_bar(tl, day, m, LAST)
    if s < 0:
        return None
    return day, s, float(tl.o[day, s]), leg_of(s)


def _limit(tl: Timeline, day: int, m0: int, m1: int, limit: float, side: int):
    """A resting limit (a sell for a short at ``limit`` or better): filled when a bar trades through it by 0.1%."""
    if day >= tl.K or not np.isfinite(limit):
        return None
    h, l_, o = tl.h[day, m0:m1 + 1], tl.l[day, m0:m1 + 1], tl.o[day, m0:m1 + 1]
    with np.errstate(invalid="ignore"):
        hit = (h > limit * 1.001) if side < 0 else (l_ < limit * 0.999)
    k = _first(np.nan_to_num(hit, nan=0).astype(bool))
    if k < 0:
        return None
    px = max(limit, float(o[k])) if side < 0 else min(limit, float(o[k]))
    return day, m0 + k, px, L_PASS


def _trigger(tl: Timeline, day: int, kind: str, side: int) -> int:
    """The minute after a one-minute trigger fires in the session of ``day`` (on bars before it), or -1."""
    if day >= tl.K:
        return -1
    h, l_, c, v, vw = (getattr(tl, k)[day] for k in ("h", "l", "c", "v", "vw"))
    s = np.arange(NM)
    with np.errstate(invalid="ignore", divide="ignore"):
        if kind == "orb":
            hi, lo = np.nanmax(h[OPEN:OPEN + 5]) if np.isfinite(h[OPEN:OPEN + 5]).any() else np.nan, \
                np.nanmin(l_[OPEN:OPEN + 5]) if np.isfinite(l_[OPEN:OPEN + 5]).any() else np.nan
            fire = (c < lo) if side < 0 else (c > hi)
            ok = (s >= OPEN + 5) & (s < M1550)
        elif kind == "vwap":
            px = np.where(np.isfinite(vw), vw, (h + l_ + c) / 3)
            vv = np.where(np.isfinite(c), np.nan_to_num(v), 0.0)
            vv[:OPEN] = 0.0
            cum = np.cumsum(np.nan_to_num(px) * vv) / np.maximum(np.cumsum(vv), 1e-12)
            above = np.nan_to_num(c > cum, nan=0).astype(bool) & (s >= OPEN)
            below = np.nan_to_num(c < cum, nan=0).astype(bool) & (s >= OPEN)
            was = np.maximum.accumulate(above if side < 0 else below)
            was = np.r_[False, was[:-1]]
            fire = (below if side < 0 else above) & was
            ok = (s >= M0945) & (s < M1550)
        else:  # hodf: 10% off a high of +30% over the prior close (short); 10% over a low of -20% (long)
            pcd = prior_close(tl, day)
            hh = np.where(s >= OPEN, np.nan_to_num(h, nan=-np.inf), -np.inf)
            ll = np.where(s >= OPEN, np.nan_to_num(l_, nan=np.inf), np.inf)
            run_hi, run_lo = np.maximum.accumulate(hh), np.minimum.accumulate(ll)
            fire = ((run_hi >= 1.3 * pcd) & (c <= 0.9 * run_hi)) if side < 0 else \
                ((run_lo <= 0.8 * pcd) & (c >= 1.1 * run_lo))
            ok = (s >= OPEN + 10) & (s < M1550)
    k = _first(np.nan_to_num(fire, nan=0).astype(bool) & ok)
    return k + 1 if k >= 0 else -1


def runner_minute(tl: Timeline, thr: float) -> int:
    """The first regular-session minute whose high reaches the prior close x (1 + thr), or -1 (the entries that need
    time after it check it themselves)."""
    with np.errstate(invalid="ignore"):
        hit = np.nan_to_num(tl.h[0, OPEN:LAST + 1] >= tl.pc * (1 + thr), nan=0).astype(bool)
    k = _first(hit)
    return OPEN + k if k >= 0 else -1


def entry(tl: Timeline, spec: tuple, side: int, tau: int = -1):
    """(day, minute, price before the half-spread, leg) of an entry, or None. ``tau``: the runner's trigger minute."""
    _, kind, day, par = spec
    close0 = float(tl.dC[0])
    if kind == "mkt":
        return _mkt(tl, day, par, side)
    if kind == "auction":
        px = float(tl.dO[day]) if day < ND else np.nan
        return (day, OPEN, px, L_OPEN) if np.isfinite(px) else None
    if kind in ("lim_ah", "lim_pm", "lim_rth"):
        sign = 1 if side < 0 else -1
        m0, m1 = {"lim_ah": (AH_FIRST, NM - 1), "lim_pm": (0, PM_END), "lim_rth": (OPEN, M1555)}[kind]
        return _limit(tl, day, m0, m1, close0 * (1 + sign * par), side)
    if kind in ("orb", "vwap", "hodf"):
        m = _trigger(tl, day, kind, side)
        return _mkt(tl, day, m, side) if m >= 0 else None
    if tau < 0:
        return None
    if kind == "rt":
        m = tau + par
        return _mkt(tl, 0, m, side) if m < M1555 else None
    if kind == "r1555":
        return _mkt(tl, 0, M1555, side) if tau < M1550 else None
    if kind == "rhodf":
        h, c = tl.h[0], tl.c[0]
        s = np.arange(NM)
        hh = np.where(s >= OPEN, np.nan_to_num(h, nan=-np.inf), -np.inf)
        run_hi = np.maximum.accumulate(hh)
        with np.errstate(invalid="ignore"):
            fire = np.nan_to_num((c <= 0.9 * run_hi) if side < 0 else (c >= 1.1 * np.minimum.accumulate(
                np.where(s >= OPEN, np.nan_to_num(tl.l[0], nan=np.inf), np.inf))), nan=0).astype(bool)
        k = _first(fire & (s > tau) & (s < M1550))
        return _mkt(tl, 0, k + 1, side) if k >= 0 else None
    raise ValueError(kind)


# ---------------------------------------------------------------- exits

def _daily_event(tl: Timeline, d0: int, level: float, side: int, kind: str):
    """The first daily day >= d0 whose bar reaches ``level``: (key, price) or None. Stops fill at the level or the
    open if it gapped past; targets at the level or the open if better."""
    for d in range(d0, ND):
        o, h, l_ = tl.dO[d], tl.dH[d], tl.dL[d]
        if not np.isfinite(h):
            continue
        if kind == "stop":
            hit = h >= level if side < 0 else l_ <= level
            if hit:
                px = max(level, o) if side < 0 else min(level, o)
                gap = (o >= level) if side < 0 else (o <= level)
                return d * NM + (OPEN if gap else 500), float(px), L_SESS
        else:
            hit = l_ < level * 0.999 if side < 0 else h > level * 1.001
            if hit:
                px = min(level, o) if side < 0 else max(level, o)
                gap = (o <= level) if side < 0 else (o >= level)
                return d * NM + (OPEN if gap else 501), float(px), L_PASS
    return None


def _first_after(tl: Timeline, g0: int, mask_flat: np.ndarray) -> int:
    k = _first(mask_flat[g0 + 1:])
    return g0 + 1 + k if k >= 0 else -1


def stop_event(tl: Timeline, g0: int, e: float, frac: float, side: int):
    """A stop-limit at e x (1 + frac) for a short (limit 5% beyond): (key, price before the half-spread, leg) of the
    fill or the fallback (the next open auction if triggered outside the session, else market 5 minutes later)."""
    stop = e * (1 + frac) if side < 0 else e * (1 - frac)
    lim = stop * 1.05 if side < 0 else stop * 0.95
    h, l_, o = tl.flat("h"), tl.flat("l"), tl.flat("o")
    with np.errstate(invalid="ignore"):
        trig = np.nan_to_num(h >= stop if side < 0 else l_ <= stop, nan=0).astype(bool)
    t = _first_after(tl, g0, trig)
    if t < 0:
        return _daily_event(tl, tl.K, stop, side, "stop")
    day, m = divmod(t, NM)
    if OPEN <= m <= LAST:
        dead = t + 5
        nxt = None
    else:
        nd = day + 1 if m > LAST else day
        dead = nd * NM + OPEN
        nxt = nd
    with np.errstate(invalid="ignore"):
        fillable = np.nan_to_num(l_ <= lim if side < 0 else h >= lim, nan=0).astype(bool)
    j = _first(fillable[t:min(dead, len(h))])
    if j >= 0:
        s = t + j
        px = min(lim, max(stop, o[s])) if side < 0 else max(lim, min(stop, o[s]))
        return s, float(px), leg_of(s % NM)
    if nxt is not None:  # outside the session: the next open auction
        if nxt < tl.K or nxt < ND:
            px = tl.dO[nxt] if nxt < ND else np.nan
            if np.isfinite(px):
                return nxt * NM + OPEN, float(px), L_OPEN
        return _daily_event(tl, nxt + 1, stop, side, "stop")
    dd, mm = divmod(dead, NM)
    s = first_bar(tl, dd, mm, LAST) if dd < tl.K else -1
    if s >= 0:
        return dd * NM + s, float(o[dd * NM + s]), leg_of(s)
    nd = dd + 1
    px = tl.dO[nd] if nd < ND else np.nan
    return (nd * NM + OPEN, float(px), L_OPEN) if np.isfinite(px) else None


def target_event(tl: Timeline, g0: int, e: float, frac: float, side: int):
    tgt = e * (1 - frac) if side < 0 else e * (1 + frac)
    h, l_, o = tl.flat("h"), tl.flat("l"), tl.flat("o")
    with np.errstate(invalid="ignore"):
        hit = np.nan_to_num(l_ < tgt * 0.999 if side < 0 else h > tgt * 1.001, nan=0).astype(bool)
    t = _first_after(tl, g0, hit)
    if t < 0:
        return _daily_event(tl, tl.K, tgt, side, "target")
    px = min(tgt, o[t]) if side < 0 else max(tgt, o[t])
    return t, float(px), L_PASS


def _last_close(tl: Timeline, d: int) -> float:
    x = tl.dC[:d + 1]
    ok = np.flatnonzero(np.isfinite(x))
    return float(x[ok[-1]]) if len(ok) else np.nan


def time_event(tl: Timeline, de: int, me: int, ti: int, side: int):
    """(key, price, leg) of the time exit ``TIMES[ti]`` for an entry on day ``de`` at minute ``me``, or None."""
    name = TIMES[ti]
    if name == "d0c":
        if me >= M1550:
            return None
        d, kind, m = de, "mkt", M1555
    elif name in ("d5c", "d10c"):
        d, kind, m = de + int(name[1:-1]), "close", LAST
    else:
        d = de + int(name[1])
        kind, m = {"o": ("auction", OPEN), "pm": ("pm", 0), "m": ("mkt", M0945), "c": ("mkt", M1555)}[name[2:]]
    if d >= ND:
        return None
    if kind == "pm" and d < tl.K:
        ref = float(tl.dC[d - 1])
        lim = ref * 0.97 if side < 0 else ref * 1.03
        got = _limit(tl, d, 0, PM_END, lim, -side)
        if got is not None:
            return d * NM + got[1], got[2], L_PASS
        kind = "auction"
    if kind == "auction" or (kind == "pm" and d >= tl.K):
        px = tl.dO[d]
        if np.isfinite(px):
            return d * NM + OPEN, float(px), L_OPEN
        return d * NM + LAST, _last_close(tl, d), L_CLOSE
    if kind == "mkt" and d < tl.K:
        s = first_bar(tl, d, m, LAST)
        if s >= 0:
            return d * NM + s, float(tl.o[d, s]), leg_of(s)
    if d >= tl.K and kind == "mkt" and m == M0945 and np.isfinite(tl.dO[d]):
        return d * NM + OPEN, float(tl.dO[d]), L_OPEN
    return d * NM + LAST, _last_close(tl, d), L_CLOSE


def exits(tl: Timeline, de: int, me: int, e: float, side: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exit price (before the half-spread), key (day x 960 + minute) and leg of every exit in EXITS (NaN: none)."""
    g0 = de * NM + me
    stops = [None] + [stop_event(tl, g0, e, f, side) for f in STOPS[1:]]
    tgts = [None] + [target_event(tl, g0, e, f, side) for f in TGTS[1:]]
    times = [time_event(tl, de, me, ti, side) for ti in range(len(TIMES))]
    px, key, leg = np.full(NX, np.nan), np.full(NX, -1, np.int64), np.zeros(NX, np.int8)
    for k, (ti, gi, si) in enumerate(EXITS):
        t = times[ti]
        if t is None:
            continue
        best = t
        g, s = tgts[gi], stops[si]
        if g is not None and g[0] < best[0]:
            best = g
        if s is not None and s[0] <= best[0] and (g is None or s[0] <= g[0]):
            best = s
        px[k], key[k], leg[k] = best[1], best[0], best[2]
    return px, key, leg


def marks(tl: Timeline, side: int, de: int, me: int, e: float, dx: int, mx: int, x: float, g: float):
    """Session by session from the entry day ``de`` to the exit day ``dx``, a unit of entry value: the return of the
    session (to the official close, the exit on the last; the half-spreads on the last), the adverse extreme from the
    session's start (the held minutes; daily bars after the minute horizon) and, for a short, its value there."""
    n = dx - de + 1
    mark, adv, hi = np.zeros(n), np.zeros(n), np.zeros(n)
    ref = e
    for i in range(n):
        d = de + i
        end = x if d == dx else (float(tl.dC[d]) if np.isfinite(tl.dC[d]) else ref)
        if d < tl.K:
            m0, m1 = (me if i == 0 else 0), (mx if d == dx else NM - 1)
            sh, sl = tl.h[d, m0:m1 + 1], tl.l[d, m0:m1 + 1]
            eh = np.nanmax(sh) if np.isfinite(sh).any() else end
            el = np.nanmin(sl) if np.isfinite(sl).any() else end
        elif d == dx and mx <= OPEN:
            eh = el = end
        else:
            eh = float(tl.dH[d]) if np.isfinite(tl.dH[d]) else end
            el = float(tl.dL[d]) if np.isfinite(tl.dL[d]) else end
        eh, el = max(eh, end), min(el, end)
        if side < 0:
            mark[i], adv[i], hi[i] = (ref - end) / e, (ref - eh) / e, eh / e
        else:
            mark[i], adv[i] = (end - ref) / e, (el - ref) / e
        ref = end
    mark[-1] += g - mark.sum()
    return mark, np.minimum(adv, mark), hi


# ---------------------------------------------------------------- returns and costs

def gross(side: int, e: float, x: np.ndarray, tier: int, leg_in: int, leg_out: np.ndarray) -> np.ndarray:
    """Return a unit of entry value after the half-spreads of both legs."""
    he, hx = HALF[tier, leg_in], HALF[tier, np.asarray(leg_out, int)]
    if side < 0:
        ein, xout = e * (1 - he), x * (1 + hx)
        return (ein - xout) / ein
    ein, xout = e * (1 + he), x * (1 - hx)
    return (xout - ein) / ein


def fixed_costs(side: int, price: float, tier: int, fee: float, cal: np.ndarray, value: float = REF,
                loc_hot: float = LOC[2], borrow: float = 1.0) -> np.ndarray:
    """Costs a unit of value that do not depend on the exit price: commissions (two legs), reporting fee, SEC and TAF
    on the sale, and for shorts the locate a share and borrow and margin interest by calendar day."""
    shares = max(np.floor(value / max(price, 0.01)), 1.0)
    val = shares * price
    comm = 2 * np.clip(COMM * shares, COMM_MIN, COMM_MAX) / val
    rep = 2 * max(np.ceil(REP * shares * 100) / 100, REP_MIN) / val
    sale = SEC + TAF / max(price, 0.01)
    cal = np.asarray(cal, float)
    if side < 0:
        loc = (LOC[0], LOC[1], loc_hot)[tier] / max(price, 0.01)
        return comm + rep + sale + loc + (fee * borrow / 100 + MARGIN) / 360 * cal
    return comm + rep + sale + MARGIN / 360 * cal


def unit(*key) -> float:
    """A uniform number fixed by the key (v47's)."""
    return int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:8], 16) / 2 ** 32


def located(sym: str, t: int, tier: int, rates: dict = UNAVAIL) -> bool:
    """False when the locate fails (v49's seeded draw)."""
    p = rates.get(int(tier), 0.0)
    return not (p > 0 and unit(sym, int(t), "49loc") < p)


# ---------------------------------------------------------------- cells and the filter grid

PRICE_EDGES = (1.0, 2.0, 5.0, 10.0)
DV_EDGES = (1e6, 3e6, 10e6)
NP_, NS_, NDV, NSO, NT, NA = 5, 4, 4, 4, 3, 3
NCELL = NP_ * NS_ * NDV * NSO * NT * NA


def so_bucket(so) -> np.ndarray:
    s = np.asarray(so, float)
    return np.select([~np.isfinite(s), s < 10e6, s < 50e6], [0, 1, 2], 3)


def age_bucket(days) -> np.ndarray:
    d = np.asarray(days, float)
    return np.select([d < 365, d < 3 * 365], [0, 1], 2)


def cell_of(pb, sb, db, ob, tb, ab) -> np.ndarray:
    return (((((np.asarray(pb) * NS_ + sb) * NDV + db) * NSO + ob) * NT + tb) * NA + ab).astype(np.int64)


def _cell_axes() -> tuple[np.ndarray, ...]:
    ix = np.arange(NCELL)
    ab = ix % NA
    tb = ix // NA % NT
    ob = ix // (NA * NT) % NSO
    db = ix // (NA * NT * NSO) % NDV
    sb = ix // (NA * NT * NSO * NDV) % NS_
    pb = ix // (NA * NT * NSO * NDV * NS_)
    return pb, sb, db, ob, tb, ab


SO_SETS = ("all", "known", "u10", "u50", "o10")
TIER_SETS = ("all", "nohot", "hot")
AGE_SETS = ("all", "young", "old")
FILTERS = [(a, b, s, d, o, t, g) for a in range(NP_) for b in range(a, NP_) for s in range(NS_) for d in range(NDV)
           for o in range(len(SO_SETS)) for t in range(len(TIER_SETS)) for g in range(len(AGE_SETS))]


def filter_matrix() -> np.ndarray:
    """FILTERS x NCELL, 1 where the cell passes the filter set."""
    pb, sb, db, ob, tb, ab = _cell_axes()
    so_ok = {"all": np.ones(NCELL, bool), "known": ob >= 1, "u10": ob == 1, "u50": (ob == 1) | (ob == 2),
             "o10": ob >= 2}
    tier_ok = {"all": np.ones(NCELL, bool), "nohot": tb < 2, "hot": tb == 2}
    age_ok = {"all": np.ones(NCELL, bool), "young": ab == 0, "old": ab >= 1}
    M = np.zeros((len(FILTERS), NCELL), np.float32)
    for k, (a, b, s, d, o, t, g) in enumerate(FILTERS):
        M[k] = (pb >= a) & (pb <= b) & (sb >= s) & (db >= d) & so_ok[SO_SETS[o]] & tier_ok[TIER_SETS[t]] & \
            age_ok[AGE_SETS[g]]
    return M


def cell_sums(cells: np.ndarray, R: np.ndarray, period: np.ndarray, nper: int) -> np.ndarray:
    """(NCELL, nper, NX, 4): count, sum, sum of gains, sum of losses of each exit's net returns (NaN skipped)."""
    out = np.zeros((NCELL, nper, R.shape[1], 4))
    ok = np.isfinite(R)
    Rz = np.where(ok, R, 0.0)
    idx = cells * nper + period
    for k in range(R.shape[1]):
        for q, w in enumerate((ok[:, k].astype(float), Rz[:, k], np.maximum(Rz[:, k], 0), np.maximum(-Rz[:, k], 0))):
            out[:, :, k, q] = np.bincount(idx, weights=w, minlength=NCELL * nper).reshape(NCELL, nper)
    return out


def score(n: np.ndarray, win: np.ndarray, loss: np.ndarray, years: float, min_year: float = 10.0,
          min_pf: float = 1.1) -> np.ndarray:
    """(PF - 1) x trades a year, -inf under the vetoes."""
    with np.errstate(invalid="ignore", divide="ignore"):
        pf = np.where(loss > 0, win / loss, np.where(win > 0, 99.0, 0.0))
        per = n / years
        s = (pf - 1) * per
    return np.where((per >= min_year) & (pf >= min_pf), s, -np.inf)


# ---------------------------------------------------------------- the account and the bootstrap

LEVELS = np.array([2_500.0, 5_000.0, 10_000.0, 25_000.0, 60_000.0])
E0, RUIN = 5_000.0, 0.25
PATHS, BLOCK, DAYS, SEED = 4000, 20, 252, 29
FIXED = {0: 6.0, 1: 6.0, 2: 105.0}
THETA, LEV_NIGHT, LEV_DAY, POS_MAX = 0.15, 2.0, 6.0, 0.5


@dataclass
class Trades:
    """A configuration's trades: absolute sessions in and out, the minute in, side, raw price and prior dollar volume,
    tier, symbol and event session, the return after half-spreads, the costs a unit of value that do not depend on the
    size (sale fees, locate, borrow and margin interest), the session marks (offsets into ``mark``: the return a unit
    of entry value earned in each held session, and the adverse extreme of each session from its start)."""
    t_in: np.ndarray
    t_out: np.ndarray
    m_in: np.ndarray
    side: np.ndarray
    price: np.ndarray
    dv1: np.ndarray
    tier: np.ndarray
    sym: np.ndarray
    t_ev: np.ndarray
    g: np.ndarray
    sale: np.ndarray
    loc: np.ndarray
    borrow: np.ndarray
    margin: np.ndarray
    off: np.ndarray
    mark: np.ndarray
    adv: np.ndarray
    hi: np.ndarray
    member: np.ndarray
    cls: int = 0


def draws(n: int, seed: int = SEED, paths: int = PATHS) -> np.ndarray:
    """v29's stationary block bootstrap: one-year paths of indices into n sessions."""
    rng = np.random.default_rng(seed)
    new = rng.random((paths, DAYS)) < 1 / BLOCK
    new[:, 0] = True
    starts = rng.integers(n, size=(paths, DAYS))
    pos = np.maximum.accumulate(np.where(new, np.arange(DAYS), 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (np.arange(DAYS) - pos)) % n


def paths(R: np.ndarray, idx: np.ndarray, fixed_month: float, e0: float = E0) -> tuple[np.ndarray, np.ndarray]:
    eq = np.full(idx.shape[0], e0)
    low = eq.copy()
    daily = fixed_month * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(LEVELS, eq, side="right") - 1, 0, len(LEVELS) - 1)
        r = R[k, idx[:, s]]
        eq = np.where(eq > 0, np.maximum(eq * (1 + np.maximum(r, -1.0)) - daily, 0.0), 0.0)
        low = np.minimum(low, eq)
    return eq, low


def year_stats(eq: np.ndarray, low: np.ndarray, e0: float = E0) -> dict:
    return {"med": float(np.median(eq)), "p10": float(np.quantile(eq, 0.10)), "p90": float(np.quantile(eq, 0.90)),
            "p_ruin": float((low <= RUIN * e0).mean()), "p_half": float((low <= 0.5 * e0).mean()),
            "p_loss": float((eq < e0).mean())}


def account(tr: Trades, order: np.ndarray, size: np.ndarray, level: float, max_new: int, max_open: int,
            T: int, loc_hot: float = LOC[2], borrow: float = 1.0) -> np.ndarray:
    """Daily returns on a fixed equity ``level`` over sessions 0..T-1: the trades in ``order`` taken while the limits
    hold (size a unit of equity capped at 1% of the prior dollar volume, whole shares, at most ``max_new`` new a session
    and ``max_open`` open, one position a symbol, overnight margin 2:1 with $2.50 a share under $2.50, intraday buying
    power 6:1, one position at most half the buying power), then forced liquidation on a session whose adverse
    extremes take the equity to 15% of the short value (every open position covered at its extreme)."""
    R = np.zeros(T)
    night = np.zeros(T)
    day_use = np.zeros(T)
    n_new = np.zeros(T, int)
    n_open = np.zeros(T, int)
    busy: dict[str, list[tuple[int, int]]] = {}
    taken: list[tuple[int, float]] = []
    for k in order:
        a, b = int(tr.t_in[k]), int(tr.t_out[k])
        if b >= T or n_new[a] >= max_new or (n_open[a:b + 1] >= max_open).any():
            continue
        sym = str(tr.sym[k])
        if any(a <= bb and aa <= b for aa, bb in busy.get(sym, ())):
            continue
        px = float(tr.price[k])
        want = min(float(size[k]) * level, 0.01 * float(tr.dv1[k]))
        shares = np.floor(want / max(px, 0.01))
        if shares < 1:
            continue
        val = shares * px
        if b > a:
            req = max(val / LEV_NIGHT, 2.5 * shares if px < 2.5 else 0.0)
            if val > POS_MAX * LEV_NIGHT * level or (night[a:b] + req > level).any():
                continue
            night[a:b] += req
        else:
            if val > POS_MAX * LEV_DAY * level or day_use[a] + night[a] * LEV_NIGHT + val > LEV_DAY * level:
                continue
            day_use[a] += val
        n_new[a] += 1
        n_open[a:b + 1] += 1
        busy.setdefault(sym, []).append((a, b))
        w = val / level
        o = int(tr.off[k])
        R[a:b + 1] += w * tr.mark[o:o + b - a + 1]
        side = int(tr.side[k])
        cal_cost = (tr.borrow[k] * borrow + tr.margin[k]) if side < 0 else tr.margin[k]
        loc = tr.loc[k] * (loc_hot / LOC[2] if int(tr.tier[k]) == 2 else 1.0)
        comm = 2 * np.clip(COMM * shares, COMM_MIN, COMM_MAX) + 2 * max(np.ceil(REP * shares * 100) / 100, REP_MIN)
        R[a] -= w * (tr.sale[k] + loc + cal_cost) + comm / level
        taken.append((k, w))
    if not taken:
        return R
    # forced liquidation, sessions in order
    alive = np.ones(len(taken), bool)
    by_u: dict[int, list[int]] = {}
    for p, (k, _) in enumerate(taken):
        for u in range(int(tr.t_in[k]), int(tr.t_out[k]) + 1):
            by_u.setdefault(u, []).append(p)
    for u in sorted(by_u):
        live = [p for p in by_u[u] if alive[p]]
        if not live:
            continue
        E, M = 1.0, 0.0
        for p in live:
            k, w = taken[p]
            o = int(tr.off[k])
            i = u - int(tr.t_in[k]) + o
            E += w * (tr.mark[o:i].sum() + tr.adv[i])  # the open loss so far, then the session's extreme
            M += w * tr.hi[i] if int(tr.side[k]) < 0 else 0.0
        if M > 0 and E <= THETA * M:
            for p in live:
                k, w = taken[p]
                o, a, b = int(tr.off[k]), int(tr.t_in[k]), int(tr.t_out[k])
                i = u - a + o
                R[u] += w * (tr.adv[i] - tr.mark[i])
                R[u + 1:b + 1] -= w * tr.mark[i + 1:o + b - a + 1]
                alive[p] = False
    return R
