"""v15 data: after-hours minute bars (16:00-20:00 ET) for the v14 event days, the earnings days and the runner days;
next-day premarket bars (04:00-09:30) after runners; and the last year of IBKR borrow data (iBorrowDesk) for the
symbols of the small-cap short pools, used only to calibrate availability and fees. Downloads only.
See docs/research/V15_PREREGISTRATION.md.

  ah       Alpaca minute bars, raw, SIP
  borrow   iBorrowDesk daily history (about one year is all it keeps; delisted symbols return nothing)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D14 = _script("run_v14_data")
P14 = _script("run_v14_prepare")
IBD = "https://www.iborrowdesk.com/api/ticker/{}"
CALIB_START = pd.Timestamp("2025-10-21")


def _wide_daily(alp: Path) -> tuple[pd.DatetimeIndex, dict]:
    df = pd.read_parquet(alp / "daily.parquet", columns=["symbol", "date", "o", "c", "v", "c_split"])
    df["symbol"] = df["symbol"].astype(str)
    df = df.drop_duplicates(["symbol", "date"])
    cal = pd.DatetimeIndex(sorted(df.loc[df["symbol"] == "SPY", "date"].unique()))
    w = {k: df.pivot(index="date", columns="symbol", values=k).reindex(cal) for k in ("o", "c", "v", "c_split")}
    return cal, w


def needs(alp: Path, sec: Path) -> tuple[dict, dict, dict]:
    """(after-hours needs, next-day premarket needs, counts) as {day: [symbols]}."""
    cal, w = _wide_daily(alp)
    c, cs = w["c"], w["c_split"]
    day_ret = cs / cs.shift(1) - 1
    band = (c >= 1) & (c <= 20)
    dv = (c * w["v"]).rolling(20, min_periods=10).mean().shift(1)
    runner = (day_ret >= 0.40) & band
    ev = json.loads((alp / "event_days.json").read_text(encoding="utf-8"))
    ah: dict[pd.Timestamp, set] = {pd.Timestamp(d): set(s) for d, s in ev.items()}
    st = runner.stack()
    st = st[st]
    pm: dict[pd.Timestamp, set] = {}
    pos = {d: i for i, d in enumerate(cal)}
    for d, s in st.index:
        ah.setdefault(d, set()).add(s)
        i = pos[d]
        if i + 1 < len(cal):
            nxt = cal[i + 1]
            if s not in set(ev.get(str(nxt.date()), [])):
                pm.setdefault(nxt, set()).add(s)
    hist = P14.ticker_history(sec)
    f = pd.read_parquet(sec / "filings.parquet")
    f = f[(f["form"] == "8-K") & f["items"].astype(str).str.contains("2.02", regex=False)].copy()
    f["date"] = pd.to_datetime(f["date"], errors="coerce")
    f = f.dropna(subset=["date"]).drop_duplicates(["cik", "date"]).reset_index(drop=True)
    f["symbol"] = P14.map_symbols(f, hist)
    f = f.dropna(subset=["symbol"])
    f = f[f["date"].isin(cal) & f["symbol"].isin(c.columns)]
    liq = dv.stack()
    liq = liq[liq >= 1e6]
    keys = pd.MultiIndex.from_arrays([f["date"], f["symbol"]])
    f = f[keys.isin(liq.index)]
    for d, s in zip(f["date"], f["symbol"]):
        ah.setdefault(d, set()).add(s)
    counts = {"event_days_symbols": int(sum(len(v) for v in ev.values())), "runner_days": int(len(st)),
              "earnings_days": int(len(f)), "ah_symbol_days": int(sum(len(v) for v in ah.values())),
              "premarket_symbol_days": int(sum(len(v) for v in pm.values()))}
    return {d: sorted(v) for d, v in ah.items()}, {d: sorted(v) for d, v in pm.items()}, counts


def _fetch_window(day: pd.Timestamp, symbols: list[str], folder: Path, h0: tuple, h1: tuple, base: tuple,
                  headers: dict, limiter) -> None:
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    rows = D14._bars(symbols, "1Min", D14._ny(day, *h0), D14._ny(day, *h1), "raw", headers, limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    start = D14._ny(day, *base)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[D14.MINUTE_COLS]
    for col in ("o", "h", "l", "c", "vw", "v"):
        df[col] = df[col].astype(np.float32)
    D14._write(df.sort_values(["symbol", "minute"]), path)


def cmd_ah(args) -> int:
    headers = D14._alpaca_headers()
    ah, pm, counts = needs(args.alpaca, args.sec)
    print(json.dumps(counts), flush=True)
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    jobs = [("ah", d, s) for d, s in sorted(ah.items())] + [("pm", d, s) for d, s in sorted(pm.items())]

    def one(kind: str, d: pd.Timestamp, s: list[str]) -> None:
        if time.time() - t0 > args.budget_min * 60:
            return
        if kind == "ah":  # minute 0 = 16:00
            _fetch_window(d, s, args.cache / "ah", (16, 0), (19, 59), (16, 0), headers, limiter)
        else:  # minute 0 = 04:00
            _fetch_window(d, s, args.cache / "pm", (4, 0), (9, 29), (4, 0), headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, *j) for j in jobs]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 250 == 0:
                print(f"windows: {n}/{len(jobs)}, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    left = sum(1 for k, d, _ in jobs if not (args.cache / k / f"{d.date()}.parquet").exists())
    (args.cache / "needs.json").write_text(json.dumps({"ah": {str(d.date()): s for d, s in ah.items()},
                                                       "pm": {str(d.date()): s for d, s in pm.items()}}),
                                           encoding="utf-8")
    print(json.dumps({"windows_missing": left, "alpaca_calls": limiter.calls}), flush=True)
    return 0


def calibration_symbols(alp: Path) -> list[str]:
    """Symbols of the small-cap short pools (gap-ups, runners, the day after) on calibration days."""
    ev = json.loads((alp / "event_days.json").read_text(encoding="utf-8"))
    out = set()
    for d, syms in ev.items():
        if pd.Timestamp(d) >= CALIB_START:
            out.update(s for s in syms if s not in ("SPY", "QQQ", "IWM"))
    return sorted(out)


def _ibd(sym: str, folder: Path) -> str:
    path = folder / f"{sym}.json"
    if path.exists():
        return "cached"
    for attempt in range(5):
        try:
            r = requests.get(IBD.format(sym.replace(".", " ")), headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            path.write_text("null", encoding="utf-8")
            return "missing"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        body = r.json()
        keep = {"symbol": body.get("symbol"), "daily": body.get("daily") or []}
        path.write_text(json.dumps(keep), encoding="utf-8")
        return "ok"
    return "failed"


def cmd_borrow(args) -> int:
    syms = calibration_symbols(args.alpaca)
    folder = args.cache / "iborrowdesk"
    folder.mkdir(parents=True, exist_ok=True)
    status: dict[str, int] = {}
    for n, s in enumerate(syms):
        st = _ibd(s, folder)
        status[st] = status.get(st, 0) + 1
        if st != "cached":
            time.sleep(1.0)  # one request a second
        if n % 250 == 0:
            print(f"iBorrowDesk: {n}/{len(syms)} {status}", flush=True)
    print(json.dumps({"symbols": len(syms), **status}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("ah", "borrow"))
    ap.add_argument("--alpaca", type=Path, default=Path("outputs/v14/alpaca"))
    ap.add_argument("--sec", type=Path, default=Path("outputs/v14/sec"))
    ap.add_argument("--cache", type=Path, default=Path("outputs/v15"))
    ap.add_argument("--budget-min", type=float, default=300.0)
    args = ap.parse_args()
    return {"ah": cmd_ah, "borrow": cmd_borrow}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
