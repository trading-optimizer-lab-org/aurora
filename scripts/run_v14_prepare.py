"""v14 prepare: turn the downloads of scripts/run_v14_data.py into the inputs of the shards (sealed at the design end).

Writes outputs/v14/inputs: daily.pkl (wide daily arrays and the stock events), store.npz + cands.parquet (the
minute bars of the intraday candidates), index.pkl (SPY, QQQ, IWM minutes), etf.pkl and crypto.pkl.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core

FIRST = pd.Timestamp("2015-06-01")
INDEX_MINUTES = ("SPY", "QQQ", "IWM")
OFFER_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "S-1", "S-3", "F-1", "F-3", "S-1MEF", "S-3ASR"}


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def load(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------- daily arrays

def duplicates(df: pd.DataFrame, min_days: int = 20) -> set[str]:
    """Symbols whose bars repeat another symbol's (same day, close and volume) on at least ``min_days`` days, e.g.
    the old and new ticker of a renamed company; of each pair the one with fewer bars is dropped."""
    from collections import Counter
    from itertools import combinations
    k = df.loc[df["v"] > 0, ["date", "c", "v", "symbol"]]
    groups = k.groupby(["date", "c", "v"])["symbol"].agg(lambda x: tuple(sorted(set(x))))
    groups = groups[groups.map(len) > 1]
    pairs: Counter = Counter()
    for syms in groups:
        pairs.update(combinations(syms, 2))
    n = df.groupby("symbol").size()
    return {a if n[a] < n[b] else b for (a, b), c in pairs.items() if c >= min_days}


def daily_arrays(alp: Path, end: pd.Timestamp, clean: bool = False) -> dict:
    df = pd.read_parquet(alp / "daily.parquet", columns=["symbol", "date", "o", "h", "l", "c", "v", "c_split"])
    df["symbol"] = df["symbol"].astype(str)
    df = df[(df["date"] >= FIRST) & (df["date"] <= end)].drop_duplicates(["symbol", "date"])
    if clean:  # v18b: no warrants, rights or units (Nasdaq fifth letter W, R, U) and no duplicated series
        wru = df["symbol"].str.len().eq(5) & df["symbol"].str[-1].isin(["W", "R", "U"])
        dup = duplicates(df[~wru])
        print(json.dumps({"dropped_warrants_rights_units": int(df.loc[wru, "symbol"].nunique()),
                          "dropped_duplicates": len(dup)}), flush=True)
        df = df[~wru & ~df["symbol"].isin(dup)]
    cal = pd.DatetimeIndex(sorted(df.loc[df["symbol"] == "SPY", "date"].unique()))
    liquid = df[(df["c"] >= 1) & (df["c"] * df["v"] >= 1e6)].groupby("symbol").size()
    df = df[df["symbol"].isin(liquid.index[liquid >= 5])]
    w = {k: df.pivot(index="date", columns="symbol", values=k).reindex(cal) for k in ("o", "h", "l", "c", "v", "c_split")}
    f = w["c_split"] / w["c"]
    cols = w["c"].columns
    f32 = np.float32  # keeps the inputs small enough for 300 runners
    D = {"dates": cal, "cols": cols, "O": (w["o"] * f).to_numpy(f32), "H": (w["h"] * f).to_numpy(f32),
         "L": (w["l"] * f).to_numpy(f32), "C": w["c_split"].to_numpy(f32), "P": w["c"].to_numpy(f32),
         "F": f.to_numpy(f32)}
    dv = (w["c"] * w["v"]).rolling(20, min_periods=10).mean()
    D["DV"] = dv.to_numpy(f32)
    valid = np.isfinite(D["C"])
    idx = np.where(valid, np.arange(len(cal))[:, None], -1)
    last = np.maximum.accumulate(idx, axis=0)
    prev_last = np.vstack([np.full((1, len(cols)), -1), last[:-1]])
    new = valid & ((prev_last < 0) | (np.arange(len(cal))[:, None] - prev_last >= 6))
    D["valid"], D["new"] = valid, new
    D["valid1"] = np.vstack([np.zeros((1, len(cols)), bool), valid[:-1]]) & ~new
    D["P1"] = np.vstack([np.full((1, len(cols)), np.nan), D["P"][:-1]])
    D["DV1"] = np.vstack([np.full((1, len(cols)), np.nan), D["DV"][:-1]])
    return D


# ---------------------------------------------------------------- SEC mapping

def ticker_history(sec: Path) -> pd.DataFrame:
    parts = [pd.read_parquet(p) for p in sorted((sec / "tickers").glob("*.parquet"))]
    cur = pd.read_parquet(sec / "company_tickers.parquet").assign(filed=pd.Timestamp("2026-10-19"))
    h = pd.concat(parts + [cur[["filed", "cik", "symbol"]]], ignore_index=True).dropna()
    h["cik"] = h["cik"].astype(np.int64)
    h["symbol"] = h["symbol"].astype(str).str.upper().str.replace("-", ".", regex=False)
    return h.sort_values("filed").drop_duplicates(["cik", "filed", "symbol"])


def map_symbols(events: pd.DataFrame, hist: pd.DataFrame) -> pd.Series:
    """The ticker of each (cik, date): the latest one filed on or before the date, else the first one known."""
    ev = events[["cik", "date"]].copy()
    ev["k"] = np.arange(len(ev))
    ev = ev.dropna().astype({"cik": np.int64, "date": "datetime64[ns]"}).sort_values("date")
    h = hist.rename(columns={"filed": "date"}).astype({"date": "datetime64[ns]"}).sort_values("date")
    back = pd.merge_asof(ev, h, on="date", by="cik", direction="backward")
    fwd = pd.merge_asof(ev, h, on="date", by="cik", direction="forward")
    sym = back.set_index("k")["symbol"].combine_first(fwd.set_index("k")["symbol"])
    return sym.reindex(np.arange(len(events))).set_axis(events.index)


def _rows(events: pd.DataFrame, D: dict) -> pd.DataFrame:
    """(t, j) of each event: t = the first session after its date, j = its symbol's column."""
    pos = {s: i for i, s in enumerate(D["cols"])}
    j = events["symbol"].map(pos)
    t = D["dates"].searchsorted(pd.to_datetime(events["date"]).to_numpy(), side="right")
    out = events.assign(t=t, j=j).dropna(subset=["j"])
    out = out[out["t"] < len(D["dates"])]
    return out.astype({"j": np.int64, "t": np.int64})


def shares_out(sec: Path, D: dict, hist: pd.DataFrame) -> np.ndarray:
    fr = pd.read_parquet(sec / "frames.parquet")
    so = fr[fr["tag"] == "EntityCommonStockSharesOutstanding"].copy()
    so["date"] = pd.to_datetime(so["end"], errors="coerce") + pd.Timedelta(days=45)
    so = so.dropna(subset=["date"])
    so["symbol"] = map_symbols(so, hist)
    so = so.dropna(subset=["symbol"]).sort_values("date").drop_duplicates(["symbol", "date"], keep="last")
    wide = so.pivot(index="date", columns="symbol", values="val")
    wide = wide.reindex(wide.index.union(D["dates"])).ffill(limit=None).reindex(D["dates"])
    return wide.reindex(columns=D["cols"]).to_numpy(np.float32)


def insider_events(sec: Path) -> pd.DataFrame:
    parts = [pd.read_parquet(p) for p in sorted((sec / "insider").glob("*.parquet"))]
    if not parts:
        return pd.DataFrame(columns=["date", "symbol", "n", "value"])
    x = pd.concat(parts, ignore_index=True).dropna(subset=["filed", "symbol"])
    x["value"] = (x["shares"] * x["price"]).fillna(0.0)
    x["symbol"] = x["symbol"].str.replace("-", ".", regex=False)
    rows = []
    for sym, g in x.sort_values("filed").groupby("symbol"):
        f, own, val = g["filed"].to_numpy(), g["owner"].to_numpy(), g["value"].to_numpy()
        for i in range(len(g)):
            lo = np.searchsorted(f, f[i] - np.timedelta64(9, "D"))
            hi = np.searchsorted(f, f[i], side="right")
            rows.append((f[i], sym, len(set(own[lo:hi])), float(val[lo:hi].sum())))
    ev = pd.DataFrame(rows, columns=["date", "symbol", "n", "value"])
    return ev.drop_duplicates(["date", "symbol"], keep="last")


def pead_events(sec: Path, D: dict, hist: pd.DataFrame, filings: pd.DataFrame) -> pd.DataFrame:
    fr = pd.read_parquet(sec / "frames.parquet")
    eps = fr[fr["tag"] == "EarningsPerShareBasic"].drop_duplicates(["cik", "year", "quarter"], keep="last")
    prev = eps.assign(year=eps["year"] + 1)[["cik", "year", "quarter", "val"]].rename(columns={"val": "prev"})
    e = eps.merge(prev, on=["cik", "year", "quarter"])
    e["surprise"] = e["val"] - e["prev"]
    e["end"] = pd.to_datetime(e["end"], errors="coerce")
    f = filings.copy()
    f["date"] = pd.to_datetime(f["date"], errors="coerce")
    k8 = f[(f["form"] == "8-K") & f["items"].astype(str).str.contains("2.02", regex=False)][["cik", "date"]]
    q10 = f[f["form"].isin(["10-Q", "10-K"])][["cik", "date"]]
    out = []
    for src, lag in ((k8, 60), (q10, 75)):
        m = e.merge(src, on="cik")
        m = m[(m["date"] > m["end"]) & (m["date"] <= m["end"] + pd.Timedelta(days=lag))]
        out.append(m.sort_values("date").drop_duplicates(["cik", "year", "quarter"]).assign(src=lag))
    ev = pd.concat(out).sort_values(["src", "date"]).drop_duplicates(["cik", "year", "quarter"]).reset_index(drop=True)
    ev["symbol"] = map_symbols(ev[["cik", "date"]].reset_index(drop=True), hist).to_numpy()
    ev = _rows(ev.dropna(subset=["symbol"]), D)
    p1 = D["P"][ev["t"].to_numpy() - 1, ev["j"].to_numpy()]
    ev["sue"] = ev["surprise"].to_numpy() / p1
    ev = ev[np.isfinite(ev["sue"])].sort_values("date").reset_index(drop=True)
    dec = np.full(len(ev), 5)
    d, s = ev["date"].to_numpy(), ev["sue"].to_numpy()
    for i in range(len(ev)):
        lo = np.searchsorted(d, d[i] - np.timedelta64(365, "D"))
        hi = np.searchsorted(d, d[i])
        if hi - lo >= 200:
            p10, p90 = np.percentile(s[lo:hi], [10, 90])
            dec[i] = 9 if s[i] >= p90 else (0 if s[i] <= p10 else 5)
    ev["decile"] = dec
    return ev[["t", "j", "sue", "decile", "date", "symbol"]]


def russell_events(sec: Path, D: dict, hist: pd.DataFrame) -> pd.DataFrame:
    fr = pd.read_parquet(sec / "frames.parquet")
    so = fr[(fr["tag"] == "EntityCommonStockSharesOutstanding") & (fr["quarter"] == 4)].copy()
    dates = D["dates"]
    ranks = {}
    for y in range(dates[0].year, dates[-1].year + 1):
        april = dates[(dates.year == y) & (dates.month == 4)]
        if not len(april):
            continue
        rd = april[-1]
        s = so[so["year"] == y - 1].drop_duplicates("cik", keep="last").assign(date=rd)
        s["symbol"] = map_symbols(s[["cik", "date"]].reset_index(drop=True), hist).to_numpy()
        s = s.dropna(subset=["symbol"])
        pos = {c: i for i, c in enumerate(D["cols"])}
        s = s[s["symbol"].isin(pos)]
        t = int(dates.get_loc(rd))
        px = D["P"][t, s["symbol"].map(pos).to_numpy()]
        s = s.assign(mcap=s["val"].to_numpy() * px, price=px)
        s = s[np.isfinite(s["mcap"]) & (s["price"] >= 1)].drop_duplicates("symbol")
        s["rank"] = s["mcap"].rank(ascending=False, method="first")
        ranks[y] = (t, s.set_index("symbol")["rank"])
    rows = []
    pos = {c: i for i, c in enumerate(D["cols"])}
    for y, (t, r) in ranks.items():
        if y - 1 not in ranks:
            continue
        prior = ranks[y - 1][1]
        now_in = r[(r >= 1001) & (r <= 3000)]
        was_in = prior[(prior >= 1001) & (prior <= 3000)]
        adds = now_in.index.difference(was_in.index)
        june = dates[(dates.year == y) & (dates.month == 6)]
        if not len(june):
            continue
        fridays = june[june.dayofweek == 4]
        recon = fridays[-1] if len(fridays) else june[-1]
        for sym in adds:
            rows.append((t, int(dates.get_loc(june[0])), int(dates.get_loc(recon)), pos[sym],
                         float(prior.get(sym, 4000) - r[sym])))
    return pd.DataFrame(rows, columns=["t_rank", "t_june", "t_recon", "j", "prio"])


def stock_events(sec: Path, D: dict) -> dict:
    hist = ticker_history(sec)
    D["SO"] = shares_out(sec, D, hist)
    forms = pd.concat([pd.read_parquet(p) for p in sorted((sec / "form_index").glob("*.parquet"))], ignore_index=True)
    forms["date"] = pd.to_datetime(forms["date"])
    filings = pd.read_parquet(sec / "filings.parquet")
    out = {}
    for name, sel in (("offering", forms["form"].isin(OFFER_FORMS)), ("activist", forms["form"] == "SC 13D")):
        ev = forms[sel].drop_duplicates(["cik", "date"]).reset_index(drop=True)
        ev["symbol"] = map_symbols(ev, hist)
        out[name] = _rows(ev.dropna(subset=["symbol"]), D)
    f = filings.copy()
    f["date"] = pd.to_datetime(f["date"], errors="coerce")
    dl = f[(f["form"] == "8-K") & f["items"].astype(str).str.contains("3.01", regex=False)]
    dl = dl.drop_duplicates(["cik", "date"]).reset_index(drop=True)
    dl["symbol"] = map_symbols(dl, hist)
    out["delist"] = _rows(dl.dropna(subset=["symbol"]), D)
    out["insider"] = _rows(insider_events(sec), D)
    out["pead"] = pead_events(sec, D, hist, filings)
    out["russell"] = russell_events(sec, D, hist)
    print(json.dumps({k: int(len(v)) for k, v in out.items()}), flush=True)
    return out


# ---------------------------------------------------------------- minute bars

def scopes(D: dict) -> dict[str, np.ndarray]:
    """The download scopes of scripts/run_v14_data.py (event_days), on the kept columns."""
    O, H, C = D["O"], D["H"], D["C"]
    raw_open = O / D["F"]
    prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    prev2 = np.vstack([np.full((2, C.shape[1]), np.nan), C[:-2]])
    gap, run, day1 = O / prev - 1, H / prev - 1, prev / prev2 - 1
    small = (raw_open >= 0.5) & (raw_open <= 50)
    with np.errstate(invalid="ignore"):
        gappers = (gap >= 0.15) & small
        rank = pd.DataFrame(np.where(gappers, gap, np.nan)).rank(axis=1, ascending=False).to_numpy()
        inplay = (np.abs(gap) >= 0.03) & (raw_open >= 5) & (D["DV1"] >= 20e6)
        prank = pd.DataFrame(np.where(inplay, np.abs(gap), np.nan)).rank(axis=1, ascending=False).to_numpy()
        return {"gap_up": gappers & (rank <= 80), "runner": (run >= 0.40) & small, "gap_down": (gap <= -0.20) & small,
                "day2": (day1 >= 0.50) & small, "in_play": inplay & (prank <= 30)}


def minute_store(alp: Path, D: dict, out: Path) -> tuple[pd.DataFrame, dict]:
    sc = scopes(D)
    any_scope = np.zeros_like(D["valid"])
    for m in sc.values():
        any_scope |= m
    any_scope &= D["valid"] & D["valid1"]
    pos = {c: i for i, c in enumerate(D["cols"])}
    tr = np.vstack([np.full((1, D["C"].shape[1]), np.nan), np.fmax(D["H"][1:], D["C"][:-1]) - np.fmin(D["L"][1:],
                                                                                                         D["C"][:-1])])
    atr = pd.DataFrame(tr).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    rows, arrays = [], {k: [] for k in ("m", "o", "h", "l", "c", "v", "vw")}
    idx_bars: dict[str, list] = {s: [] for s in INDEX_MINUTES}
    off = 0
    for t, day in enumerate(D["dates"]):
        if day < core.DESIGN_START - pd.Timedelta(days=40):
            continue
        path = alp / "minutes" / f"{day.date()}.parquet"
        if not path.exists():
            continue
        js = np.flatnonzero(any_scope[t])
        want = {D["cols"][j] for j in js} | set(INDEX_MINUTES)
        bars = pd.read_parquet(path)
        bars = bars[bars["symbol"].isin(want)]
        for sym, b in bars.groupby("symbol", sort=False):
            j = pos.get(sym)
            if j is None:
                continue
            mm = b["minute"].to_numpy()
            pre, reg = b[mm < 330], b[(mm >= 330) & (mm < 720)]
            if len(reg) < 5:
                continue
            f_t = D["F"][t, j]
            pc = D["C"][t - 1, j] / f_t if t > 0 else np.nan
            arr = {"m": (reg["minute"].to_numpy() - 330).astype(np.int16)}
            for k in ("o", "h", "l", "c", "v", "vw"):
                arr[k] = reg[k].to_numpy(np.float32)
            if sym in INDEX_MINUTES:
                idx_bars[sym].append((day, pc, arr))
            if not any_scope[t, j]:
                continue
            pvw = np.where(np.isfinite(pre["vw"]), pre["vw"], pre["c"])
            last30 = pre[pre["minute"] >= 300]
            dv1 = D["DV1"][t, j]
            first5 = float(reg.loc[reg["minute"] < 335, "v"].sum())
            rows.append({"date": day, "symbol": sym, "t": t, "j": j, "off": off, "n": len(reg),
                         "open": float(reg["o"].iloc[0]), "pc": pc, "gap": float(reg["o"].iloc[0]) / pc - 1,
                         "pmv": float((pvw * pre["v"]).sum()), "pmh": float(pre["h"].max()) if len(pre) else np.nan,
                         "pml30": float(last30["l"].min()) if len(last30) else np.nan,
                         "day1": D["C"][t - 1, j] / D["C"][t - 2, j] - 1 if t > 1 else np.nan,
                         "day1_loc": ((D["C"][t - 1, j] - D["L"][t - 1, j]) /
                                      max(D["H"][t - 1, j] - D["L"][t - 1, j], 1e-9)) if t > 0 else np.nan,
                         "so": D["SO"][t, j], "atr14": atr[t, j] / f_t,
                         "rv5": first5 / max(dv1 / pc / 78, 1.0) if np.isfinite(dv1) and pc > 0 else 0.0,
                         **{f"s_{k}": bool(sc[k][t, j]) for k in sc}})
            for k in arrays:
                arrays[k].append(arr[k])
            off += len(reg)
        if t % 200 == 0:
            print(f"minute store: {day.date()}, {len(rows)} candidates, {off} bars", flush=True)
    cands = pd.DataFrame(rows)
    flat = {k: np.concatenate(v) if v else np.zeros(0) for k, v in arrays.items()}
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "store.npz", **flat)
    cands.to_parquet(out / "cands.parquet", index=False)
    return cands, idx_bars


# ---------------------------------------------------------------- ETF, macro and crypto

def etf_inputs(alp: Path, macro: Path, idx_bars: dict, cal: pd.DatetimeIndex, cash_td: pd.Series) -> dict:
    tr = pd.read_parquet(alp / "etf_total_return.parquet")
    tr["symbol"] = tr["symbol"].astype(str)
    close = tr.pivot(index="date", columns="symbol", values="c").reindex(cal)
    opn = tr.pivot(index="date", columns="symbol", values="o").reindex(cal)

    def cboe(name: str) -> pd.Series:
        x = pd.read_csv(macro / f"{name}.csv")
        x.columns = [c.strip().upper() for c in x.columns]
        return pd.Series(x["CLOSE"].to_numpy(float), index=pd.to_datetime(x["DATE"])).sort_index()

    to1400 = {}
    for sym in ("SPY", "QQQ"):
        vals = {}
        for day, pc, a in idx_bars.get(sym, []):
            j = int(np.searchsorted(a["m"], 270, side="right")) - 1
            if j >= 0 and pc > 0:
                vals[day] = float(a["c"][j]) / pc - 1
        to1400[sym] = pd.Series(vals)
    fomc = pd.to_datetime(pd.read_csv(macro / "fomc.csv")["date"])
    return {"dates": cal, "etf_close": close, "etf_open": opn, "etf_ret": close.pct_change(fill_method=None),
            "vix": cboe("VIX"), "vix3m": cboe("VIX3M"), "fomc": pd.DatetimeIndex(fomc),
            "to1400": pd.DataFrame(to1400), "cash": cash_td}


def crypto_inputs(cry: Path, end: pd.Timestamp, cash_td: pd.Series) -> dict:
    d = pd.read_parquet(cry / "crypto_daily.parquet")
    d = d[d["time"] <= end]
    cal = pd.date_range("2017-08-17", end, freq="D")
    close = d.pivot_table(index="time", columns="symbol", values="c").reindex(cal)
    qv = d.pivot_table(index="time", columns="symbol", values="qv").reindex(cal)
    ret = close.pct_change(fill_method=None)
    hourly = {}
    for s in ("BTCUSDT", "ETHUSDT"):
        h = pd.read_parquet(cry / "klines_1h" / f"{s}.parquet")
        h = h[h["time"] <= end + pd.Timedelta(hours=23)]
        hourly[s] = h.set_index("time")["c"].sort_index()
    fund = pd.read_parquet(cry / "funding.parquet")
    tcol = [c for c in fund.columns if "time" in c.lower()][0]
    rcol = [c for c in fund.columns if "rate" in c.lower()][0]
    fund["day"] = pd.to_datetime(fund[tcol], unit="ms").dt.normalize()
    funding = fund.pivot_table(index="day", columns="symbol", values=rcol, aggfunc="mean").reindex(cal)
    cash = cash_td.reindex(cal).fillna(0.0)
    return {"close": close, "qv": qv, "ret": ret, "hourly": pd.DataFrame(hourly), "funding": funding, "cash": cash}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("outputs/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v14/inputs"))
    ap.add_argument("--clean", action="store_true", help="v18b: drop warrants, rights, units and duplicated series")
    args = ap.parse_args()
    end = core.last_day()
    D = daily_arrays(args.data / "alpaca", end, clean=args.clean)
    print(json.dumps({"dates": len(D["dates"]), "symbols": len(D["cols"]), "end": str(end.date())}), flush=True)
    D["events"] = stock_events(args.data / "sec", D)
    cands, idx_bars = minute_store(args.data / "alpaca", D, args.out)
    print(json.dumps({"candidates": len(cands), **{c: int(cands[c].sum()) for c in cands.columns
                                                   if c.startswith("s_")}}), flush=True)
    mab = _script("run_multiasset_baselines")
    cash_index = mab.tbill_index({})
    cash_td = cash_index.reindex(D["dates"]).ffill().pct_change(fill_method=None).fillna(0.0)
    D["cash"] = cash_td
    dump(D, args.out / "daily.pkl")
    dump(idx_bars, args.out / "index.pkl")
    X = etf_inputs(args.data / "alpaca", args.data / "macro", idx_bars, D["dates"], cash_td)
    dump(X, args.out / "etf.pkl")
    cash_cal = cash_index.reindex(pd.date_range("2015-06-01", end, freq="D")).ffill().pct_change(
        fill_method=None).fillna(0.0)
    dump(crypto_inputs(args.data / "crypto", min(end, core.CRYPTO_END), cash_cal), args.out / "crypto.pkl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
