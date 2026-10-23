"""v29 IEX data (V29_PREREGISTRATION.md section 6): Alpaca's IEX one-minute bars (04:00-15:59 ET, raw prices) of every
symbol of the v18 event store, the v23 liquid store and the v24 mover store, on a seeded random order of days within
a time budget. Only the bars are kept (in the Actions cache); nothing is published.

  minutes  fetch the days
  coverage the days and symbol-days fetched
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


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D14 = _script("run_v14_data")
STORES = {"event": Path("outputs/v18/v14/cands.parquet"), "liquid": Path("outputs/v23/store/cands.parquet"),
          "mover": Path("outputs/v24/store/cands.parquet")}
SEED = 29


def need() -> dict[pd.Timestamp, list[str]]:
    """Day -> the symbols of the three stores' candidates that day."""
    out: dict[pd.Timestamp, set] = {}
    for path in STORES.values():
        c = pd.read_parquet(path, columns=["date", "symbol"])
        for d, grp in c.groupby("date"):
            out.setdefault(pd.Timestamp(d), set()).update(grp["symbol"].astype(str))
    return {d: sorted(v) for d, v in out.items()}


def order(days: list[pd.Timestamp]) -> list[pd.Timestamp]:
    rng = np.random.default_rng(SEED)
    days = sorted(days)
    return [days[i] for i in rng.permutation(len(days))]


def _bars_iex(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp, headers: dict, limiter) -> list[tuple]:
    params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start.isoformat(), "end": end.isoformat(),
              "feed": "iex", "adjustment": "raw", "limit": 10000}
    rows = []
    while True:
        body = D14.V9._get(D14.BARS, params, headers, limiter) or {}
        for sym, bars in (body.get("bars") or {}).items():
            rows += [(sym, x["t"], x["o"], x["h"], x["l"], x["c"], x["v"], x.get("vw", np.nan), x.get("n", 0))
                     for x in bars]
        token = body.get("next_page_token")
        if not token:
            return rows
        params = {**params, "page_token": token}


def _day(day: pd.Timestamp, symbols: list[str], folder: Path, headers: dict, limiter) -> None:
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    rows = []
    for k in range(0, len(symbols), 200):
        rows += _bars_iex(symbols[k:k + 200], D14._ny(day, 4, 0), D14._ny(day, 15, 59), headers, limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    start = D14._ny(day, 4, 0)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[(df["minute"] >= 0) & (df["minute"] < 720)][D14.MINUTE_COLS]
    for col in ("o", "h", "l", "c", "vw", "v"):
        df[col] = df[col].astype(np.float32)
    D14._write(df.sort_values(["symbol", "minute"]), path)


def cmd_minutes(args) -> int:
    todo_all = need()
    folder = args.out / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    todo = [d for d in order(list(todo_all)) if not (folder / f"{d.date()}.parquet").exists()]
    print(f"days to fetch: {len(todo)} of {len(todo_all)}", flush=True)

    def one(d):
        if time.time() - t0 < args.budget_min * 60:
            _day(d, todo_all[d], folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, d) for d in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"iex bars: {n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    return cmd_coverage(args)


def cmd_coverage(args) -> int:
    todo_all = need()
    folder = args.out / "minutes"
    got = [d for d in todo_all if (folder / f"{d.date()}.parquet").exists()]
    out = {"days": len(todo_all), "days_fetched": len(got),
           "symbol_days": int(sum(len(v) for v in todo_all.values())),
           "symbol_days_fetched": int(sum(len(todo_all[d]) for d in got)),
           "first": str(min(got).date()) if got else None, "last": str(max(got).date()) if got else None}
    (args.out / "coverage.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("minutes", "coverage"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v29/iex"))
    ap.add_argument("--budget-min", type=float, default=300.0)
    args = ap.parse_args()
    return {"minutes": cmd_minutes, "coverage": cmd_coverage}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
