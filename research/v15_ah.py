"""v15: B8 under IBKR-calibrated shortability (R1, R2) and the after-hours families AH1-AH4.
Pre-registered in docs/research/V15_PREREGISTRATION.md.

The after-hours store holds, per symbol-day, the 16:00-19:59 bars (minute 0 = 16:00, raw) and the facts of the
day: regular close and high, prior close, next open and close (all on the day's raw scale), the next day's
premarket price at 08:00 and 09:25, and flags.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi

PRICE_BANDS = (0, 2, 5, 10, 20)
SO_BANDS = ("unknown", "<10M", "10-50M", ">50M")
FIXED_W, FIXED_MAX = 0.05, 10

V15_DIMS = {
    "B8R1_GAPFADE": vi.A_DIMS["B8_GAPFADE"],
    "B8R2_GAPFADE": vi.A_DIMS["B8_GAPFADE"],
    "AH1_AHFADE": {"up": (0.40, 0.80), "drop": (0.02, 0.05)},
    "AH2_B8LATE": {"gap": (0.30, 0.50, 1.00), "pmv": (250e3, 1e6), "cover": (0, 60, 235)},
    "AH3_EARNAH": {"move": (0.03, 0.06), "mode": ("next_with", "next_against", "night_with")},
    "AH4_NIGHTPM": {"up": (0.40, 0.80), "cover": ("pm08", "pm925")},
}


@dataclass
class AHStore:
    cands: pd.DataFrame
    arrays: dict

    def bars(self, k: int) -> tuple:
        off, n = int(self.cands.at[k, "off"]), int(self.cands.at[k, "n"])
        return tuple(self.arrays[f][off:off + n] for f in vi.FIELDS)


# ---------------------------------------------------------------- availability

def price_band(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    return np.select([p < 2, p < 5, p < 10], ["<2", "2-5", "5-10"], "10-20")


def so_band(so: np.ndarray) -> np.ndarray:
    s = np.asarray(so, dtype=float)
    return np.select([~np.isfinite(s), s < 10e6, s < 50e6], ["unknown", "<10M", "10-50M"], ">50M")


def calibrate(events: pd.DataFrame, min_n: int = 30) -> dict:
    """events: price, so, borrowable (bool), fee (annual %, nan if none). -> {(price band, so band): (p, fee, n)}."""
    e = events.assign(pb=price_band(events["price"]), sb=so_band(events["so"]))
    out = {}
    pooled = {pb: g for pb, g in e.groupby("pb")}
    for pb in ("<2", "2-5", "5-10", "10-20"):
        for sb in SO_BANDS:
            g = e[(e["pb"] == pb) & (e["sb"] == sb)]
            src = g if len(g) >= min_n else pooled.get(pb, g)
            if len(src) == 0:
                out[(pb, sb)] = (0.0, np.nan, 0)
                continue
            fee = src.loc[src["borrowable"], "fee"].median()
            out[(pb, sb)] = (float(src["borrowable"].mean()), float(fee) if np.isfinite(fee) else np.nan, int(len(g)))
    return out


def lookup(table: dict, price: np.ndarray, so: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pb, sb = price_band(price), so_band(so)
    p = np.array([table.get((a, b), (0.0, np.nan, 0))[0] for a, b in zip(pb, sb)])
    fee = np.array([table.get((a, b), (0.0, np.nan, 0))[1] for a, b in zip(pb, sb)])
    return p, np.where(np.isfinite(fee), fee, 100.0)  # unknown fee: 100% a year


# ---------------------------------------------------------------- books

COLS = ["date", "symbol", "pnl_date", "minute", "side", "entry", "exit", "stop", "price", "liq", "prio", "nights", "so",
        "ah_in", "ah_out"]


def book(trades: pd.DataFrame, dates: pd.DatetimeIndex, table: dict, spread: float, fixed: bool) -> pd.Series:
    """R1/R2 book: middle half-spreads x ``spread`` (twice that on an after-hours leg), commission, no locate; a
    short's weight is multiplied by its cell's availability and an overnight short pays the cell's fee / 360."""
    if trades.empty:
        return pd.Series(0.0, index=dates)
    t = trades.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
    if fixed:
        t = t.groupby("date", sort=False).head(FIXED_MAX).copy()
        t["w"] = FIXED_W
    else:
        t = t.groupby("date", sort=False).head(5).copy()
        dist = (t["entry"] - t["stop"]).abs() / t["entry"]
        t["w"] = np.minimum(np.minimum(0.20, 0.005 / dist.clip(lower=1e-4)), 0.02 * t["liq"].fillna(0.0) / core.ACCOUNT)
    t["w"] = t["w"] / np.maximum(1.0, t.groupby("date")["w"].transform("sum"))
    p_av, fee = lookup(table, t["price"].to_numpy(), t["so"].to_numpy())
    short = t["side"].to_numpy() < 0
    t["w"] = t["w"] * np.where(short, p_av, 1.0)
    price = np.maximum(t["price"].to_numpy(float), 0.01)
    hs = core.half_spread(price, "mid") * spread
    legs = hs * np.where(t["ah_in"], 2.0, 1.0) + hs * np.where(t["ah_out"], 2.0, 1.0)
    cost = legs + 2 * core.COMMISSION / price + np.where(short, fee / 100 / 360 * t["nights"].to_numpy(float), 0.0)
    net = t["side"] * (t["exit"] / t["entry"] - 1) - cost
    daily = (t["w"] * net).groupby(t["pnl_date"]).sum()
    return daily.reindex(dates).fillna(0.0)


def b8_trades(store: vi.Store, g: dict, dates: pd.DatetimeIndex) -> pd.DataFrame:
    t = vi.family_trades(store, "B8_GAPFADE", g)
    return _v15_cols(t)


def _v15_cols(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["pnl_date"] = t["date"]
    t["ah_in"] = False
    t["ah_out"] = False
    return t[COLS] if len(t) else pd.DataFrame(columns=COLS)


# ---------------------------------------------------------------- after-hours families

def _price_at(b: tuple, minute: int) -> float:
    j = int(np.searchsorted(b[0], minute, side="right")) - 1
    return float(b[4][j]) if j >= 0 else np.nan


def ah1(ah: AHStore, g: dict) -> pd.DataFrame:
    c = ah.cands
    sel = c.index[(c["day_ret"] >= g["up"]) & (c["c16"] >= 1) & (c["c16"] <= 20) & np.isfinite(c["nxt_open"])]
    rows = []
    for k in sel:
        r = ah1_trade(ah, k, g["drop"], None)
        if r is not None:
            rows.append(r)
    return pd.DataFrame(rows, columns=COLS)


def ah1_trade(ah: AHStore, k: int, drop: float, minute: int | None, dist: float | None = None) -> dict | None:
    cd = ah.cands.loc[k]
    b = ah.bars(k)
    m, o, h, c = b[0], b[1], b[2], b[4]
    if len(m) == 0:
        return None
    if minute is None:
        hit = np.flatnonzero((m < 120) & (c <= cd["c16"] * (1 - drop)))
        if not len(hit):
            return None
        j = int(hit[0])
    else:
        j = int(np.searchsorted(m, minute))
        if j >= len(m) or m[j] >= 120:
            return None
    entry = float(c[j])
    stop = float(cd["hi"]) if dist is None else entry * (1 + dist)
    if not stop > entry:
        return None
    after = np.flatnonzero(h[j + 1:] >= stop)
    if len(after):
        q = j + 1 + int(after[0])
        ex, pnl, nights, ah_out = max(float(o[q]), stop), cd["date"], 0, True
    else:
        ex, pnl, nights, ah_out = float(cd["nxt_open"]), cd["nxt_date"], 1, False
    return {"date": cd["date"], "symbol": cd["symbol"], "pnl_date": pnl, "minute": int(m[j]), "side": -1, "entry": entry, "exit": ex,
            "stop": stop, "price": float(cd["c16"]), "liq": np.inf, "prio": float(cd["day_ret"]), "nights": nights,
            "so": float(cd["so"]), "ah_in": True, "ah_out": ah_out}


def ah4(ah: AHStore, g: dict) -> pd.DataFrame:
    c = ah.cands
    sel = c.index[(c["day_ret"] >= g["up"]) & (c["c16"] >= 1) & (c["c16"] <= 20)]
    return pd.DataFrame([r for k in sel if (r := ah4_trade(ah, k, g["cover"])) is not None], columns=COLS)


def ah4_trade(ah: AHStore, k: int, cover: str) -> dict | None:
    cd = ah.cands.loc[k]
    ex = cd[cover] if np.isfinite(cd[cover]) else cd["nxt_open"]
    if not np.isfinite(ex):
        return None
    return {"date": cd["date"], "symbol": cd["symbol"], "pnl_date": cd["nxt_date"], "minute": 0, "side": -1, "entry": float(cd["c16"]),
            "exit": float(ex), "stop": np.nan, "price": float(cd["c16"]), "liq": np.inf, "prio": float(cd["day_ret"]),
            "nights": 1, "so": float(cd["so"]), "ah_in": False, "ah_out": bool(np.isfinite(cd[cover]))}


def earn_pool(ah: AHStore) -> pd.Index:
    c = ah.cands
    return c.index[c["earn"] & (c["c16"] >= 3) & (c["dv20"] >= 5e6) & (c["ahdv"] >= 500e3) &
                   np.isfinite(c["nxt_open"]) & np.isfinite(c["nxt_close"])]


def ah3(ah: AHStore, g: dict) -> pd.DataFrame:
    rows = []
    for k in earn_pool(ah):
        b = ah.bars(k)
        cd = ah.cands.loc[k]
        p = _price_at(b, 119)
        if not np.isfinite(p):
            continue
        mv = p / cd["c16"] - 1
        if abs(mv) < g["move"]:
            continue
        side = int(np.sign(mv)) * (-1 if g["mode"] == "next_against" else 1)
        r = ah3_trade(ah, k, g["mode"], side)
        if r is not None:
            r["prio"] = abs(mv)
            rows.append(r)
    return pd.DataFrame(rows, columns=COLS)


def ah3_trade(ah: AHStore, k: int, mode: str, side: int) -> dict | None:
    cd = ah.cands.loc[k]
    if mode == "night_with":
        entry = _price_at(ah.bars(k), 120)
        ex, nights, ah_in = cd["nxt_open"], 1, True
    else:
        entry, ex, nights, ah_in = cd["nxt_open"], cd["nxt_close"], 0, False
    if not (np.isfinite(entry) and np.isfinite(ex) and entry > 0):
        return None
    return {"date": cd["date"], "symbol": cd["symbol"], "pnl_date": cd["nxt_date"], "minute": 120, "side": side, "entry": float(entry),
            "exit": float(ex), "stop": np.nan, "price": float(cd["c16"]), "liq": np.inf, "prio": 0.0,
            "nights": nights if side < 0 else 0, "so": float(cd["so"]), "ah_in": ah_in, "ah_out": False}


def ah2(store: vi.Store, ah: AHStore, ah_index: dict, g: dict) -> pd.DataFrame:
    """B8 with the 5-minute-low entry, covered at the close or later in the after-hours bars."""
    b8 = vi.family_trades(store, "B8_GAPFADE", {"gap": g["gap"], "entry": "orl5", "exit": "close", "pmv": g["pmv"]})
    return extend(store, ah, ah_index, b8, g["cover"])


def extend(store: vi.Store, ah: AHStore, ah_index: dict, t: pd.DataFrame, cover: int) -> pd.DataFrame:
    t = _v15_cols(t)
    if cover == 0 or t.empty:
        return t
    out = []
    reg = {(d, s): k for k, d, s in zip(store.cands.index, store.cands["date"], store.cands["symbol"])}
    for _, r in t.iterrows():
        r = r.to_dict()
        kr = reg.get((r["date"], r["symbol"])) if "symbol" in r else None
        ka = ah_index.get((r["date"], r.get("symbol")))
        if kr is not None and ka is not None:
            rc = float(store.bars(kr)[4][-1])
            if abs(r["exit"] - rc) < 1e-9:  # held to the close: carry on into the after-hours bars
                b = ah.bars(ka)
                m, o, h, c = b[0], b[1], b[2], b[4]
                keep = m <= cover
                if keep.any():
                    hit = np.flatnonzero(keep & (h >= r["stop"]))
                    if len(hit):
                        r["exit"], r["ah_out"] = max(float(o[hit[0]]), r["stop"]), True
                    else:
                        r["exit"], r["ah_out"] = float(c[np.flatnonzero(keep)[-1]]), True
        out.append(r)
    return pd.DataFrame(out)[COLS]
