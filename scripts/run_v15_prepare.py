"""v15 prepare: the after-hours store (design period only) and the IBKR availability calibration.

Reads the v14 inputs (sealed at the design end), the v14 downloads (daily bars, minutes, SEC) and the v15
downloads; writes outputs/v15/inputs: ah_cands.parquet, ah_store.npz and avail.pkl.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v15_ah as v15


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P14 = _script("run_v14_prepare")


def earnings_days(sec: Path, cols: pd.Index, dates: pd.DatetimeIndex) -> set:
    hist = P14.ticker_history(sec)
    f = pd.read_parquet(sec / "filings.parquet")
    f = f[(f["form"] == "8-K") & f["items"].astype(str).str.contains("2.02", regex=False)].copy()
    f["date"] = pd.to_datetime(f["date"], errors="coerce")
    f = f.dropna(subset=["date"]).drop_duplicates(["cik", "date"]).reset_index(drop=True)
    f["symbol"] = P14.map_symbols(f, hist)
    f = f.dropna(subset=["symbol"])
    f = f[f["date"].isin(dates) & f["symbol"].isin(cols)]
    return set(zip(f["date"], f["symbol"]))


def _premarket(day: pd.Timestamp, alp: Path, v15dir: Path, cache: dict) -> pd.DataFrame:
    """Premarket bars of a day (minute 0 = 04:00): the v15 download, else the v14 minute file."""
    if day in cache:
        return cache[day]
    parts = []
    for path in (v15dir / "pm" / f"{day.date()}.parquet", alp / "minutes" / f"{day.date()}.parquet"):
        if path.exists():
            b = pd.read_parquet(path, columns=["symbol", "minute", "c"])
            parts.append(b[b["minute"] < 330])
    out = pd.concat(parts).drop_duplicates(["symbol", "minute"]) if parts else pd.DataFrame(
        columns=["symbol", "minute", "c"])
    cache.clear()
    cache[day] = out
    return out


def ah_store(D: dict, alp: Path, sec: Path, v15dir: Path, out: Path) -> pd.DataFrame:
    needs = json.loads((v15dir / "needs.json").read_text(encoding="utf-8"))["ah"]
    earn = earnings_days(sec, D["cols"], D["dates"])
    pos = {c: i for i, c in enumerate(D["cols"])}
    tix = {d: i for i, d in enumerate(D["dates"])}
    O, H, C, P, F = D["O"], D["H"], D["C"], D["P"], D["F"]
    rows, arrays, off = [], {k: [] for k in ("m", "o", "h", "l", "c", "v", "vw")}, 0
    pm_cache: dict = {}
    for d_str in sorted(needs):
        day = pd.Timestamp(d_str)
        t = tix.get(day)
        if t is None or t == 0 or t + 1 >= len(D["dates"]):
            continue
        path = v15dir / "ah" / f"{day.date()}.parquet"
        bars = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["symbol", "minute"])
        groups = {s: g for s, g in bars.groupby("symbol")} if len(bars) else {}
        nxt = D["dates"][t + 1]
        pm = _premarket(nxt, alp, v15dir, pm_cache)
        pm_groups = {s: g for s, g in pm.groupby("symbol")} if len(pm) else {}
        for sym in needs[d_str]:
            j = pos.get(sym)
            if j is None or not (D["valid"][t, j] and D["valid1"][t, j]):
                continue
            f_t = F[t, j]
            g = groups.get(sym)
            arr = {"m": np.zeros(0, np.int16), **{k: np.zeros(0, np.float32) for k in ("o", "h", "l", "c", "v", "vw")}}
            ahdv = 0.0
            if g is not None and len(g):
                g = g[g["minute"] < 240]
                arr = {"m": g["minute"].to_numpy(np.int16), **{k: g[k].to_numpy(np.float32)
                                                               for k in ("o", "h", "l", "c", "v", "vw")}}
                early = g[g["minute"] < 120]
                px = np.where(np.isfinite(early["vw"]), early["vw"], early["c"])
                ahdv = float((px * early["v"]).sum())
            ok_next = D["valid"][t + 1, j] and not D["new"][t + 1, j]
            scale = F[t + 1, j] / f_t if ok_next else np.nan  # next day's raw prices on this day's raw scale
            pmg = pm_groups.get(sym)
            pm08 = pm925 = np.nan
            if pmg is not None and len(pmg) and ok_next:
                mm, cc = pmg["minute"].to_numpy(), pmg["c"].to_numpy(float)
                for name, minute in (("pm08", 240), ("pm925", 325)):
                    k = int(np.searchsorted(mm, minute, side="right")) - 1
                    if k >= 0:
                        val = cc[k] / scale
                        if name == "pm08":
                            pm08 = val
                        else:
                            pm925 = val
            rows.append({"date": day, "symbol": sym, "t": t, "j": j, "off": off, "n": len(arr["m"]),
                         "c16": float(P[t, j]), "hi": float(H[t, j] / f_t), "pc": float(C[t - 1, j] / f_t),
                         "day_ret": float(C[t, j] / C[t - 1, j] - 1), "nxt_date": nxt,
                         "nxt_open": float(O[t + 1, j] / f_t) if ok_next else np.nan,
                         "nxt_close": float(C[t + 1, j] / f_t) if ok_next else np.nan,
                         "pm08": pm08, "pm925": pm925, "earn": (day, sym) in earn, "dv20": float(D["DV1"][t, j]),
                         "so": float(D["SO"][t, j]), "ahdv": ahdv})
            for k in arrays:
                arrays[k].append(arr[k])
            off += len(arr["m"])
        if t % 250 == 0:
            print(f"after-hours store: {day.date()}, {len(rows)} symbol-days, {off} bars", flush=True)
    cands = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "ah_store.npz", **{k: np.concatenate(v) if v else np.zeros(0) for k, v in arrays.items()})
    cands.to_parquet(out / "ah_cands.parquet", index=False)
    return cands


def ibkr_snapshot(out: Path) -> dict[str, tuple[float, float]]:
    """IBKR's public short-stock file: {symbol: (shares available, annual fee %)}."""
    import ftplib
    import io
    buf = io.BytesIO()
    for host in ("ftp2.interactivebrokers.com", "ftp3.interactivebrokers.com"):
        try:
            with ftplib.FTP(host, timeout=120) as ftp:
                ftp.login("shortstock", "")
                ftp.retrbinary("RETR usa.txt", buf.write)
            break
        except (OSError, ftplib.Error) as exc:
            print(f"IBKR FTP {host}: {exc}", flush=True)
    text = buf.getvalue().decode("latin-1")
    if not text:
        raise SystemExit("could not download IBKR's short-stock file")
    out.parent.mkdir(parents=True, exist_ok=True)
    first = text.splitlines()[0] if text else ""
    snap = {}
    for line in text.splitlines():
        p = line.split("|")
        if line.startswith("#") or len(p) < 8:
            continue
        av = p[7].lstrip(">")
        fee = float(p[6]) if p[6] not in ("", "NA") else np.nan
        snap[p[0].replace(" ", ".")] = (float(av) if av.isdigit() else 0.0, fee)
    (out.parent / "ibkr_snapshot_header.txt").write_text(first, encoding="utf-8")
    return snap


def calibration(alp: Path, sec: Path, out: Path) -> tuple[dict, dict]:
    """Availability of the small-cap event days of the 60 sessions before the data end, judged with IBKR's
    snapshot (reads prices, shares outstanding and borrow only; never a return)."""
    snap = ibkr_snapshot(out)
    ev = json.loads((alp / "event_days.json").read_text(encoding="utf-8"))
    days = sorted(pd.Timestamp(d) for d in ev)
    window = set(days[-60:])
    pairs = [(pd.Timestamp(d), s) for d, ss in ev.items() for s in ss
             if pd.Timestamp(d) in window and s not in ("SPY", "QQQ", "IWM")]
    syms = sorted({s for _, s in pairs})
    df = pd.read_parquet(alp / "daily.parquet", columns=["symbol", "date", "o", "h", "c", "c_split"])
    df["symbol"] = df["symbol"].astype(str)
    df = df[df["symbol"].isin(syms) & (df["date"] >= min(window) - pd.Timedelta(days=10))]
    df = df.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"])
    df["f"] = df["c_split"] / df["c"]
    df["prev"] = df.groupby("symbol")["c_split"].shift(1)
    df["prev2"] = df.groupby("symbol")["c_split"].shift(2)
    df["gap"] = df["o"] * df["f"] / df["prev"] - 1
    df["run"] = df["h"] * df["f"] / df["prev"] - 1
    df["day1"] = df["prev"] / df["prev2"] - 1
    df = df.set_index(["date", "symbol"])
    cal = pd.DatetimeIndex(sorted(df.index.get_level_values(0).unique()))
    so = pd.DataFrame(P14.shares_out(sec, {"dates": cal, "cols": pd.Index(syms)}, P14.ticker_history(sec)),
                      index=cal, columns=syms)
    rows = []
    for d, s in pairs:
        if (d, s) not in df.index:
            continue
        x = df.loc[(d, s)]
        if not (1 <= x["o"] <= 20) or not (x["gap"] >= 0.15 or x["run"] >= 0.40 or x["day1"] >= 0.50):
            continue
        avail, fee = snap.get(s, (0.0, np.nan))
        need = max(1000.0, 10000.0 / float(x["o"]))
        rows.append({"price": float(x["o"]), "so": float(so.at[d, s]), "borrowable": bool(avail >= need),
                     "fee": fee})
    events = pd.DataFrame(rows)
    table = v15.calibrate(events) if len(events) else {}
    stats = {"source": "IBKR usa.txt " + (out.parent / "ibkr_snapshot_header.txt").read_text(encoding="utf-8"),
             "window": [str(min(window).date()), str(max(window).date())], "events": len(events),
             "no_borrow_data": int(sum(1 for _, s in pairs if s not in snap)),
             "share_borrowable": float(events["borrowable"].mean()) if len(events) else None,
             "cells": {f"{a}|{b}": {"p": round(v[0], 3), "fee": None if not np.isfinite(v[1]) else round(v[1], 2),
                                    "n": v[2]} for (a, b), v in table.items()}}
    return table, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v14-inputs", type=Path, default=Path("outputs/v14/inputs"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v14"))
    ap.add_argument("--v15", type=Path, default=Path("outputs/v15"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v15/inputs"))
    args = ap.parse_args()
    D = P14.load(args.v14_inputs / "daily.pkl")
    if D["dates"][-1] > core.last_day():
        raise SystemExit("v14 inputs reach past the allowed last day")
    cands = ah_store(D, args.data / "alpaca", args.data / "sec", args.v15 / "ah_cache", args.out)
    print(json.dumps({"ah_symbol_days": len(cands), "with_ah_bars": int((cands["n"] > 0).sum()),
                      "earnings": int(cands["earn"].sum()), "runners_40": int((cands["day_ret"] >= 0.4).sum()),
                      "pm08_known": int(np.isfinite(cands["pm08"]).sum())}), flush=True)
    table, stats = calibration(args.data / "alpaca", args.data / "sec", args.out / "ibkr")
    print(json.dumps(stats, indent=1), flush=True)
    P14.dump({"table": table, "stats": stats}, args.out / "avail.pkl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
