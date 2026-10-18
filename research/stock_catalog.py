"""US stock strategy catalog from X traders, as pre-registered in
docs/research/STOCK_CATALOG_PREREGISTRATION.md.

``panel`` is a dict of wide DataFrames (dates x symbols) with adjusted
``open``, ``high``, ``low``, ``close`` and split-adjusted ``volume``.
Every rule below is copied from the pre-registration; change the document
first if anything here has to change.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab

WARMUP_START = pd.Timestamp("1993-01-01")
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
PERIODS = {"train": (TRAIN_START, TRAIN_END), "validation": (VALIDATION_START, VALIDATION_END)}

PPY = 252
COST = 10 / 1e4
RISK = 0.005
CAP = 0.20
BNF_SIZE = 0.10
UNIVERSE_SIZE = 1500
MIN_HISTORY = 260


@dataclass(frozen=True)
class Candidate:
    name: str
    setup: str
    exit: str
    filters: tuple[str, ...]


TREND = [
    ("felipe_5d", "S1", "X5"), ("felipe_s20", "S1", "XS20"), ("qulla_s10", "S2", "XS10"),
    ("qulla_s20", "S2", "XS20"), ("qulla_half3", "S2", "XH3"), ("pullback_s20", "S3", "XS20"),
    ("burst_fast", "S4", "XF"), ("burst_5d", "S4", "X5"), ("ep_s20", "S5", "XS20"),
    ("darvas_s20", "S6", "XS20"), ("weinstein_s20", "S7", "XS20"),
]
CANDIDATES: list[Candidate] = (
    [Candidate(n, s, x, ("MF", "ADR4", "IND50")) for n, s, x in TREND]
    + [Candidate(f"{n}_noind", s, x, ("MF", "ADR4")) for n, s, x in TREND]
    + [Candidate("bnf_reversion", "S8", "BNF", ())]
)
BLEND = ("blend_t", ("felipe_5d", "pullback_s20", "bnf_reversion"))
N_TRIALS = len(CANDIDATES) + 1


def ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n, min_periods=n).mean()


def rsi2(close: pd.DataFrame) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def week_ends(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("W-FRI")).transform("max").eq(s).to_numpy()


def industry_rs(rs_pct: pd.DataFrame, industry: pd.Series) -> pd.DataFrame:
    """Industry RS percentile on each stock, recomputed on the last trading day
    of every week and carried forward (Jacobs)."""
    weekly = rs_pct.loc[week_ends(rs_pct.index)]
    groups = industry.reindex(weekly.columns)
    med = weekly.T.groupby(groups).median().T
    count = weekly.notna().T.groupby(groups).sum().T
    ranked = med.where(count >= 3).rank(axis=1, pct=True) * 100
    per_stock = ranked.reindex(columns=groups.to_numpy())
    per_stock.columns = weekly.columns
    return per_stock.reindex(rs_pct.index).ffill()


def ever_in_universe(panel: dict[str, pd.DataFrame]) -> pd.Index:
    """Symbols that enter the universe at least once; the others can never trade."""
    C, V = panel["close"], panel["volume"]
    dv50 = (C * V).rolling(50, min_periods=50).mean()
    eligible = (C.notna().cumsum() >= MIN_HISTORY) & dv50.notna()
    ranked = dv50.where(eligible).rank(axis=1, ascending=False) <= UNIVERSE_SIZE
    return C.columns[ranked.any()]


def indicators(panel: dict[str, pd.DataFrame], index_close: pd.Series, industry: pd.Series) -> dict:
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    history = C.notna().cumsum()
    dv50 = (C * V).rolling(50, min_periods=50).mean()
    eligible = (history >= MIN_HISTORY) & dv50.notna()
    universe = eligible & (dv50.where(eligible).rank(axis=1, ascending=False) <= UNIVERSE_SIZE)
    adr = (H / L - 1).rolling(20, min_periods=20).mean()
    raw_rs = sum(w * (C / C.shift(n) - 1) for w, n in ((2, 63), (1, 126), (1, 189), (1, 252)))
    rs = raw_rs.where(universe).rank(axis=1, pct=True) * 100
    idx = index_close.reindex(C.index).ffill()
    return {
        "universe": universe, "adr": adr, "rs": rs, "ind_rs": industry_rs(rs, industry),
        "mf": sma(idx.to_frame(), 10).iloc[:, 0] > sma(idx.to_frame(), 20).iloc[:, 0],
        "index_above_200": idx > idx.rolling(200, min_periods=200).mean(),
        "vol50_prior": V.shift(1).rolling(50, min_periods=50).mean(),
        "sma5": sma(C, 5), "sma10": sma(C, 10), "sma20": sma(C, 20), "sma50": sma(C, 50), "ema21": ema(C, 21),
    }


def _setup_s1(O, H, L, C, V, ind):
    e8, e20, e50 = ema(C, 8), ema(C, 20), ema(C, 50)
    stack = (e8 > e20) & (e20 > e50) & (e8 > e8.shift(5)) & (e20 > e20.shift(5)) & (e50 > e50.shift(5))
    first_leg = (C < e50).astype(float).rolling(60, min_periods=60).max() > 0
    above20 = (C >= e20).astype(float).shift(1).rolling(7, min_periods=7).min() == 1
    hi7, lo7 = H.shift(1).rolling(7, min_periods=7).max(), L.shift(1).rolling(7, min_periods=7).min()
    tight = (hi7 - lo7) / C.shift(1) <= 2.5 * ind["adr"].shift(1)
    body = C - O
    candle = (C > hi7) & (body > 0) & (body > (C.shift(1) - O.shift(1)).abs()) & (C >= L + 0.786 * (H - L))
    stop = L
    near = (C - stop) / C <= 2.5 * ind["adr"]
    return stack & first_leg & above20 & tight & candle & near, stop


def _setup_s2(O, H, L, C, V, ind):
    s10, s20 = ind["sma10"], ind["sma20"]
    runup = C.shift(1) >= 1.3 * L.shift(1).rolling(63, min_periods=63).min()
    trend = (C.shift(1) > s10.shift(1)) & (C.shift(1) > s20.shift(1)) & (s10 > s20) & (s20 > s20.shift(5))
    hi10, lo10 = H.shift(1).rolling(10, min_periods=10).max(), L.shift(1).rolling(10, min_periods=10).min()
    tight = (hi10 - lo10) / C.shift(1) <= 3 * ind["adr"].shift(1)
    stop = np.maximum(L, C * (1 - ind["adr"]))
    return runup & trend & tight & (C > hi10), stop


def _setup_s3(O, H, L, C, V, ind):
    e9, e21 = ema(C, 9), ema(C, 21)
    trend = (e9 > e21) & (e9 > e9.shift(5)) & (e21 > e21.shift(5))
    touch = ((L <= e21 * 1.01) | (L <= e9)) & (V < ind["vol50_prior"])
    recent = touch.astype(float).shift(1).rolling(3, min_periods=3).max() > 0
    curl = (C > H.shift(1)) & (C > e9)
    return trend & recent & curl, L.rolling(4, min_periods=4).min()


def _setup_s4(O, H, L, C, V, ind):
    narrow = (H.shift(1) - L.shift(1)) / C.shift(1) < ind["adr"].shift(1)
    sig = (C / C.shift(1) >= 1.04) & (V > V.shift(1)) & narrow & (C > ema(C, 21))
    return sig, L


def _setup_s5(O, H, L, C, V, ind):
    gap = O / C.shift(1) >= 1.10
    quiet = C.shift(1) < 1.3 * C.shift(127)
    no_prior_gap = gap.astype(float).shift(1).rolling(63, min_periods=63).max() == 0
    sig = gap & (V >= 3 * ind["vol50_prior"]) & (C > O) & quiet & no_prior_gap
    return sig, L


def _setup_s6(O, H, L, C, V, ind):
    sig = (C > H.shift(1).rolling(252, min_periods=252).max()) & (V >= 1.5 * ind["vol50_prior"])
    return sig, L.rolling(10, min_periods=10).min()


def _setup_s7(O, H, L, C, V, ind):
    s150 = sma(C, 150)
    sig = ((C > s150) & (s150 > s150.shift(20)) & (C > H.shift(1).rolling(50, min_periods=50).max())
           & (V >= 1.5 * ind["vol50_prior"]))
    return sig, L.rolling(10, min_periods=10).min()


SETUPS = {"S1": _setup_s1, "S2": _setup_s2, "S3": _setup_s3, "S4": _setup_s4,
          "S5": _setup_s5, "S6": _setup_s6, "S7": _setup_s7}


def bnf_signals(panel: dict[str, pd.DataFrame], ind: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """S8: signal at the close of t, limit price for t+1, and the deviation (rank)."""
    C, L = panel["close"], panel["low"]
    dev = C / ind["sma10"] - 1
    q10 = dev.rolling(250, min_periods=250).quantile(0.10)
    q01 = dev.rolling(250, min_periods=250).quantile(0.01)
    strong = (C > sma(C, 200)).mul(ind["index_above_200"], axis=0).astype(bool)
    sig = ind["universe"] & ((strong & (dev <= q10)) | (~strong & (dev <= q01)))
    k = pd.DataFrame(np.where(strong, 0.5, 1.5), index=C.index, columns=C.columns)
    limit = L - k * ind["adr"] * C
    return sig, limit, dev


def entry_mask(sig: pd.DataFrame, ind: dict, filters: tuple[str, ...]) -> pd.DataFrame:
    m = sig & ind["universe"]
    if "MF" in filters:
        m = m.mul(ind["mf"], axis=0).astype(bool)
    if "ADR4" in filters:
        m = m & (ind["adr"] >= 0.04)
    if "IND50" in filters:
        m = m & (ind["ind_rs"] >= 50)
    return m.fillna(False).astype(bool)


def simulate(panel: dict[str, pd.DataFrame], ind: dict, entries: pd.DataFrame, stops: pd.DataFrame | None,
             exit_rule: str, cash_r: pd.Series, rank: pd.DataFrame, start: pd.Timestamp = TRAIN_START,
             limits: pd.DataFrame | None = None, rsi: pd.DataFrame | None = None,
             trades: list | None = None, risk: float = RISK, side: int = 1,
             entry_px: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily net return and invested fraction from ``start``.

    Entries fill at the close of the signal day (S8: limit order the next day,
    with ``stops`` as its optional stop). Stops are checked from the day after
    entry: against the low for longs, the high for shorts (``side=-1``). A
    short is held as collateral worth ``shares * (2 * entry - close)``.
    """
    dates = panel["close"].index
    f32 = np.float32
    O, H, L = (panel[k].to_numpy(dtype=f32) for k in ("open", "high", "low"))
    Craw = panel["close"].to_numpy(dtype=f32)
    C = panel["close"].ffill().to_numpy(dtype=f32)
    S10, S20 = ind["sma10"].to_numpy(dtype=f32), ind["sma20"].to_numpy(dtype=f32)
    S50 = ind["sma50"].to_numpy(dtype=f32) if "sma50" in ind else None
    S5 = ind["sma5"].to_numpy(dtype=f32) if "sma5" in ind else None
    AD = ind["adr"].to_numpy(dtype=f32)
    E21 = ind["ema21"].to_numpy(dtype=f32) if "ema21" in ind else None
    LO10 = ind["low10"].to_numpy(dtype=f32) if "low10" in ind else None
    LO20 = ind["low20"].to_numpy(dtype=f32) if "low20" in ind else None
    R14 = ind["rsi14"].to_numpy(dtype=f32) if "rsi14" in ind else None
    WK = ind["week_end"].to_numpy() if "week_end" in ind else None
    XC = ind[exit_rule].to_numpy() if exit_rule.startswith("XC_") else None
    S100 = ind["sma100"].to_numpy(dtype=f32) if "sma100" in ind else None
    LO50 = ind["low50"].to_numpy(dtype=f32) if "low50" in ind else None
    E10 = ind["ema10"].to_numpy(dtype=f32) if "ema10" in ind else None
    EPX = entry_px.to_numpy(dtype=f32) if entry_px is not None else None
    QD = QMA = 0
    if exit_rule.startswith("XQ") and not exit_rule.startswith("XQC"):
        QD, QMA = (int(x) for x in exit_rule[2:].split("_"))
    E = entries.to_numpy()
    ST = stops.to_numpy(dtype=f32) if stops is not None else None
    LIM = limits.to_numpy(dtype=f32) if limits is not None else None
    R2 = rsi.to_numpy(dtype=f32) if rsi is not None else None
    RK = rank.to_numpy(dtype=f32)
    cr = cash_r.reindex(dates).fillna(0.0).to_numpy()
    first = int(dates.searchsorted(start))
    cash, eq_prev = 1.0, 1.0
    pos: dict[int, dict] = {}
    pending: list[tuple[int, float, float | None]] = []
    rets, inv = [], []

    def mark(p: dict, c: float) -> float:
        return p["shares"] * (c if side > 0 else 2 * p["entry"] - c)

    def sell(i: int, px: float, frac: float = 1.0) -> None:
        nonlocal cash
        p = pos[i]
        q = p["shares"] * frac
        if side > 0:
            cash += q * px * (1 - COST)
        else:
            cash += q * (2 * p["entry"] - px) - q * px * COST
        if trades is not None:
            trades.append({"symbol": int(i), "entry_date": dates[p["t"]], "exit_date": dates[t],
                           "entry": float(p["entry"]), "exit": float(px), "fraction": frac,
                           "return": float(side * (px / p["entry"] - 1))})
        p["shares"] -= q
        if frac >= 1.0:
            del pos[i]

    for t in range(first, len(dates)):
        cash *= 1 + cr[t]
        for i, lim, pstop in pending:
            if i in pos or not np.isfinite(L[t, i]) or L[t, i] > lim:
                continue
            px = min(O[t, i], lim) if np.isfinite(O[t, i]) else lim
            amount = min(BNF_SIZE * eq_prev, cash / (1 + COST))
            if amount <= 0:
                break
            cash -= amount * (1 + COST)
            pos[i] = {"shares": amount / px, "entry": px, "stop": pstop, "t": t, "half": False}
        pending = []
        for i in list(pos):
            p = pos[i]
            if p["t"] >= t or p["stop"] is None:
                continue
            if side > 0 and np.isfinite(L[t, i]) and L[t, i] <= p["stop"]:
                sell(i, min(O[t, i], p["stop"]) if np.isfinite(O[t, i]) else p["stop"])
            elif side < 0 and np.isfinite(H[t, i]) and H[t, i] >= p["stop"]:
                sell(i, max(O[t, i], p["stop"]) if np.isfinite(O[t, i]) else p["stop"])
        for i in list(pos):
            p = pos[i]
            c = Craw[t, i]
            if p["t"] >= t or not np.isfinite(c):
                continue
            days = t - p["t"]
            if exit_rule == "X5":
                if days >= 5:
                    sell(i, c)
            elif exit_rule in ("XS10", "XS20"):
                if c < (S10 if exit_rule == "XS10" else S20)[t, i]:
                    sell(i, c)
            elif exit_rule == "XS50":
                assert S50 is not None
                if c < S50[t, i]:
                    sell(i, c)
            elif exit_rule == "XH3":
                if days == 3 and not p["half"]:
                    sell(i, c, 0.5)
                    p["half"], p["stop"] = True, p["entry"]
                if i in pos and c < S10[t, i]:
                    sell(i, c)
            elif exit_rule == "XF":
                if (days == 3 and c <= p["entry"]) or c < S10[t, i]:
                    sell(i, c)
            elif exit_rule == "XPS":
                if c <= S10[t, i] or days >= 10:
                    sell(i, c)
            elif exit_rule == "XC20":
                if c > S20[t, i]:
                    sell(i, c)
            elif exit_rule == "XRSI":
                assert S5 is not None
                if c > S5[t, i]:
                    sell(i, c)
            elif exit_rule in ("XT2", "XT3", "XT5", "XT8"):
                p["hc"] = max(p["hc"], float(c))
                p["stop"] = max(p["stop"], p["hc"] * (1 - int(exit_rule[2:]) * p["adr"]))
            elif exit_rule == "XBE":
                if c >= p["entry"] + p["r0"]:
                    p["stop"] = max(p["stop"], p["entry"])
                if c < S20[t, i]:
                    sell(i, c)
            elif exit_rule == "XR3":
                target = p["entry"] + 3 * p["r0"]
                if np.isfinite(H[t, i]) and H[t, i] >= target:
                    sell(i, max(O[t, i], target) if np.isfinite(O[t, i]) else target)
                elif days >= 60:
                    sell(i, c)
            elif exit_rule in ("XTIME20", "XTIME60"):
                if days >= int(exit_rule[5:]):
                    sell(i, c)
            elif exit_rule in ("XLOW10", "XLOW20"):
                lows = LO10 if exit_rule == "XLOW10" else LO20
                assert lows is not None
                if c < lows[t, i]:
                    sell(i, c)
            elif exit_rule == "XRSI80":
                assert R14 is not None
                if R14[t, i] > 80:
                    sell(i, c)
            elif exit_rule == "XEXT":
                assert S50 is not None
                if c >= 1.25 * S50[t, i] or c < S50[t, i]:
                    sell(i, c)
            elif exit_rule in ("XCH", "XSAR"):
                hi = float(H[t, i]) if np.isfinite(H[t, i]) else float(c)
                if exit_rule == "XCH":
                    p["hh"] = max(p["hh"], hi)
                    p["stop"] = max(p["stop"], p["hh"] * (1 - 3 * p["adr"]))
                else:
                    if hi > p["hh"]:
                        p["hh"], p["af"] = hi, min(p["af"] + 0.02, 0.2)
                    p["stop"] = p["stop"] + p["af"] * (p["hh"] - p["stop"])
            elif exit_rule == "XDEC":
                p["hc"] = max(p["hc"], float(c))
                k = max(2.0, 8.0 - 0.25 * (days // 5))
                p["stop"] = max(p["stop"], p["hc"] * (1 - k * p["adr"]))
            elif exit_rule == "XS100":
                assert S100 is not None
                if c < S100[t, i]:
                    sell(i, c)
            elif exit_rule == "XLOW50":
                assert LO50 is not None
                if c < LO50[t, i]:
                    sell(i, c)
            elif exit_rule == "XKELL":
                assert E10 is not None and S50 is not None
                if c >= 1.2 * p["entry"]:
                    p["kell"] = True
                if c < (E10 if p["kell"] else S50)[t, i]:
                    sell(i, c)
            elif exit_rule == "XT8H":
                target = p["entry"] * 1.5
                if not p["half"] and np.isfinite(H[t, i]) and H[t, i] >= target:
                    sell(i, max(O[t, i], target) if np.isfinite(O[t, i]) else target, 0.5)
                    p["half"] = True
                p["hc"] = max(p["hc"], float(c))
                p["stop"] = max(p["stop"], p["hc"] * (1 - 8 * p["adr"]))
            elif QD:
                if days == QD and not p["half"]:
                    sell(i, c, 0.5 if QD == 3 else 1 / 3)
                    p["half"], p["stop"] = True, max(p["stop"], p["entry"])
                if i in pos and days >= QD and c < (S10 if QMA == 10 else S20)[t, i]:
                    sell(i, c)
            elif exit_rule in ("XQC10", "XQC20"):
                if c <= (S10 if exit_rule == "XQC10" else S20)[t, i]:
                    sell(i, c)
            elif exit_rule.startswith("XC_"):
                assert XC is not None
                if XC[t, i]:
                    sell(i, c)
            elif exit_rule == "XWK":
                assert S50 is not None and WK is not None
                if WK[t] and c < S50[t, i]:
                    sell(i, c)
            elif exit_rule == "XE21":
                assert E21 is not None
                if c < E21[t, i]:
                    sell(i, c)
            elif exit_rule == "XS50T60":
                assert S50 is not None
                if c < S50[t, i] or days >= 60:
                    sell(i, c)
            elif exit_rule == "XO25":
                assert S50 is not None
                target = p["entry"] * 1.25
                if not p["half"] and np.isfinite(H[t, i]) and H[t, i] >= target:
                    sell(i, max(O[t, i], target) if np.isfinite(O[t, i]) else target, 0.5)
                    p["half"] = True
                if i in pos and c < S50[t, i]:
                    sell(i, c)
            elif exit_rule == "BNF":
                assert R2 is not None
                if R2[t, i] >= 85 or (days >= 3 and c < p["entry"]) or days >= 5:
                    sell(i, c)
        equity = cash + sum(mark(p, C[t, i]) for i, p in pos.items())
        hits = np.flatnonzero(E[t])
        if hits.size:
            order = [int(i) for i in hits[np.argsort(-RK[t, hits], kind="stable")] if int(i) not in pos]
            if exit_rule == "BNF":
                assert LIM is not None
                pending = [(i, float(LIM[t, i]), float(ST[t, i]) if ST is not None and np.isfinite(ST[t, i])
                            else None) for i in order if np.isfinite(LIM[t, i])]
            else:
                assert ST is not None
                for i in order:
                    c, st = Craw[t, i], ST[t, i]
                    intraday = EPX is not None and np.isfinite(EPX[t, i])
                    px = EPX[t, i] if EPX is not None and intraday else c
                    if not (np.isfinite(c) and np.isfinite(px) and np.isfinite(st)) or side * (px - st) <= 0:
                        continue
                    value = min(risk * equity / (abs(px - st) / px), CAP * equity, cash / (1 + COST))
                    if value <= 1e-6 * equity:
                        break
                    cash -= value * (1 + COST)
                    pos[i] = {"shares": value / px, "entry": px, "stop": st, "t": t, "half": False,
                              "hc": float(px), "adr": float(AD[t, i]) if np.isfinite(AD[t, i]) else 0.0,
                              "r0": abs(float(px) - float(st)), "hh": float(px), "af": 0.02, "kell": False}
                    if intraday:  # bought on a level during the day: the stop is live the same day
                        lo, hi = L[t, i], H[t, i]
                        if (side > 0 and lo <= st) or (side < 0 and hi >= st):
                            sell(i, float(st))
                        elif side > 0 and np.isfinite(lo):
                            pos[i]["stop"] = max(float(st), float(lo))
                        elif side < 0 and np.isfinite(hi):
                            pos[i]["stop"] = min(float(st), float(hi))
        equity = cash + sum(mark(p, C[t, i]) for i, p in pos.items())
        rets.append(equity / eq_prev - 1)
        inv.append(1 - cash / equity if equity > 0 else 0.0)
        eq_prev = equity
    return pd.DataFrame({"return": rets, "invested": inv}, index=dates[first:])


def blend(daily: dict[str, pd.Series], names: tuple[str, ...]) -> pd.Series:
    """Equal capital in each sleeve at the start of every month, drifting within it."""
    r = pd.concat([daily[n] for n in names], axis=1).fillna(0.0)
    out = []
    for _, month in r.groupby(r.index.to_period("M")):
        value = (1 + month).cumprod().mean(axis=1)
        out.append(value.pct_change().fillna(value.iloc[0] - 1))
    return pd.concat(out).rename("return")


def equal_weight_universe(panel: dict[str, pd.DataFrame], universe: pd.DataFrame,
                          start: pd.Timestamp = TRAIN_START) -> pd.Series:
    daily = panel["close"].pct_change(fill_method=None)
    me = pd.Series(universe.index, index=universe.index)
    me = me.groupby(universe.index.to_period("M")).transform("max").eq(me).to_numpy()
    members = universe.astype(float)
    members.loc[~me] = np.nan
    members = members.ffill().shift(1).fillna(0.0).astype(bool)
    return daily.where(members).mean(axis=1).loc[start:].fillna(0.0).rename("return")


def metrics(returns: pd.Series, cash: pd.Series) -> dict:
    m = mab.metrics(returns, cash)
    excess = returns - cash.reindex(returns.index).fillna(0.0)
    m["skew"] = float(excess.skew())
    m["kurtosis"] = float(excess.kurt()) + 3.0
    return m


def criteria(v: dict, spy: dict) -> dict[str, bool]:
    return {
        "monthly Sortino >= 2.0": v["sortino_monthly"] >= 2.0,
        "annualised return above SPY": v["cagr"] > spy["cagr"],
        "max drawdown no deeper than -25%": v["max_drawdown"] >= -0.25,
    }


def annual_returns(r: pd.Series) -> dict[str, float]:
    return {str(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}


def run_study(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series) -> dict:
    if panel["close"].index.max() >= LOCKED_START:
        raise ValueError("locked period data reached the stock catalog")
    keep = ever_in_universe(panel)
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    from aurora.research import stock_trades as st

    daily: dict[str, pd.Series] = {}
    trades: dict[str, pd.DataFrame] = {}
    extra: dict[str, dict] = {}
    for key, fn in SETUPS.items():
        sig, stop = fn(O, H, L, C, V, ind)
        for cand in [c for c in CANDIDATES if c.setup == key]:
            mask = entry_mask(sig, ind, cand.filters)
            d = simulate(panel, ind, mask, stop, cand.exit, cash, ind["rs"])
            daily[cand.name] = d["return"]
            trades[cand.name] = st.trade_list(panel, ind, mask, stop, cand.exit)
            extra[cand.name] = {"invested_mean": float(d["invested"].mean()),
                                "signals": int(mask.loc[TRAIN_START:].to_numpy().sum())}
        del sig, stop
    sig, limit, dev = bnf_signals(panel, ind)
    sig = sig.fillna(False).astype(bool)
    r2 = rsi2(C)
    d = simulate(panel, ind, sig, None, "BNF", cash, -dev, limits=limit, rsi=r2)
    daily["bnf_reversion"] = d["return"]
    trades["bnf_reversion"] = st.trade_list(panel, ind, sig, None, "BNF", limits=limit, rsi=r2)
    extra["bnf_reversion"] = {"invested_mean": float(d["invested"].mean()),
                              "signals": int(sig.loc[TRAIN_START:].to_numpy().sum())}
    daily[BLEND[0]] = blend(daily, BLEND[1])
    extra[BLEND[0]] = {"invested_mean": float("nan"), "signals": 0}

    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[TRAIN_START:].fillna(0.0)
    bench = {"spy": spy, "equal_weight_universe": equal_weight_universe(panel, ind["universe"])}
    results: dict[str, dict] = {}
    for name, r in {**bench, **daily}.items():
        results[name] = {p: metrics(r.loc[a:b], cash) for p, (a, b) in PERIODS.items()}
        results[name]["annual"] = annual_returns(r)
        results[name].update(extra.get(name, {}))
        if name in trades:
            results[name]["trade_level"] = st.summarize(trades[name])
    names = [c.name for c in CANDIDATES] + [BLEND[0]]
    trial = [results[n]["validation"]["sharpe"] for n in names]
    for n in names:
        v = results[n]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(v["sharpe"], trial, n_periods=v["days"], skew=v["skew"],
                                                   kurtosis=v["kurtosis"], ppy=PPY)
        results[n]["checks"] = criteria(v, results["spy"]["validation"])
        results[n]["passed"] = all(results[n]["checks"].values())
    return {"results": results, "daily_returns": {**bench, **daily}, "candidates": names, "trades": trades}
