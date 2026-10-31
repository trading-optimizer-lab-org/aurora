"""v51 data (V51_PREREGISTRATION.md section 2): the event symbol-days of every setup and their one-minute bars.

  census   the event superset from the daily panel (known facts only decide which days are fetched, never a trade),
           the symbol-days to fetch (the event day and the next H sessions, H fixed by the size budget) and counts
  minutes  Alpaca SIP one-minute bars, 04:00-19:59 ET, raw prices, of those symbol-days; a coverage report
Market data stays in the Actions cache; only counts are printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import sys
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
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FIRST = pd.Timestamp("2018-01-02")
P_MIN, P_MAX, DV_MIN = 0.5, 20.0, 5e5
UP, DOWN, RUN = 1.20, 0.85, 2.5
HOLDS = (3, 2, 1)  # sessions after the event day with minute bars, the largest that fits the budget
BUDGET_GB, KB_PER_DAY = 2.3, 4.5  # v24's store held 3.6 KB a symbol-day for 04:00-15:59; 04:00-19:59 assumed 4.5
COLS = ["symbol", "minute", "o", "h", "l", "c", "v", "vw"]


def load_daily(inputs: Path) -> dict:
    with open(inputs / "v14" / "daily.pkl", "rb") as f:
        return pickle.load(f)


def superset(D: dict) -> np.ndarray:
    """Event days (session x column): a rise of 20% over the prior close at the high, a fall of 15% at the low, or a
    high 2.5 times the five-session low; prior raw close $0.50-$20 and $500k prior 20-day dollar volume. Every setup's
    trigger, at any minute, lies inside it (the high and low bound every price of the session)."""
    H, L, C = (np.asarray(D[k], float) for k in ("H", "L", "C"))
    pc = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    low5 = pd.DataFrame(L).rolling(5, min_periods=2).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        ev = (H / pc >= UP) | (L / pc <= DOWN) | (H >= RUN * low5)
    P1, DV1 = np.asarray(D["P1"], float), np.asarray(D["DV1"], float)
    ok = D["valid"] & D["valid1"] & (P1 >= P_MIN) & (P1 <= P_MAX) & (DV1 >= DV_MIN)
    ok &= np.asarray(D["dates"] >= FIRST)[:, None]
    return ev & ok


def need_days(D: dict, ev: np.ndarray, hold: int) -> dict[str, list[str]]:
    dates, cols, valid = D["dates"], D["cols"], D["valid"]
    T = len(dates)
    need: dict[int, set] = {}
    for t, j in zip(*np.nonzero(ev)):
        for u in range(t, min(t + hold + 1, T)):
            if valid[u, j]:
                need.setdefault(u, set()).add(str(cols[j]))
    return {str(dates[u].date()): sorted(s) for u, s in sorted(need.items())}


def cmd_census(args) -> int:
    D = load_daily(args.inputs)
    print(json.dumps({"keys": sorted(D), "sessions": len(D["dates"]), "columns": len(D["cols"]),
                      "first": str(D["dates"][0].date()), "last": str(D["dates"][-1].date())}), flush=True)
    for name in ("v16/extras.pkl", "v18/extras.pkl", "v15/avail.pkl"):
        p = args.inputs / name
        if p.exists():
            with open(p, "rb") as f:
                x = pickle.load(f)
            print(name, json.dumps(sorted(map(str, x)) if isinstance(x, dict) else str(type(x))), flush=True)
    ev = superset(D)
    years = pd.Series(np.asarray(D["dates"].year)[np.nonzero(ev)[0]]).value_counts().sort_index()
    out = {"events": int(ev.sum()), "per_year": {str(k): int(v) for k, v in years.items()}}
    for hold in HOLDS:
        need = need_days(D, ev, hold)
        n = sum(len(s) for s in need.values())
        out[f"symbol_days_h{hold}"] = n
        if n * KB_PER_DAY / 1e6 <= BUDGET_GB or hold == HOLDS[-1]:
            out["hold"] = hold
            break
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "need.json").write_text(json.dumps(need), encoding="utf-8")
    t, j = np.nonzero(ev)
    pd.DataFrame({"t": t.astype(np.int32), "j": j.astype(np.int32)}).to_parquet(args.out / "events.parquet")
    (args.out / "census.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out), flush=True)
    return 0


def _minute_day(D14, day: pd.Timestamp, symbols: list[str], folder: Path, headers: dict, limiter) -> None:
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    rows = []
    for k in range(0, len(symbols), 50):
        rows += D14._bars(symbols[k:k + 50], "1Min", D14._ny(day, 4, 0), D14._ny(day, 19, 59), "raw", headers,
                          limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    start = D14._ny(day, 4, 0)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[(df["minute"] >= 0) & (df["minute"] < 960)][COLS]
    for col in ("o", "h", "l", "c", "vw", "v"):
        df[col] = df[col].astype(np.float32)
    df["symbol"] = df["symbol"].astype("category")
    tmp = path.with_suffix(".tmp")
    df.sort_values(["symbol", "minute"]).to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def cmd_minutes(args) -> int:
    D14 = _script("run_v14_data")
    headers = D14._alpaca_headers()
    need = json.loads((args.out / "need.json").read_text(encoding="utf-8"))
    folder = args.out / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    todo = [(pd.Timestamp(d), s) for d, s in need.items() if not (folder / f"{d}.parquet").exists()]
    print(f"minute days to fetch: {len(todo)} of {len(need)}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(_minute_day, D14, d, s, folder, headers, limiter) for d, s in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"{n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    total = have = 0
    for d, syms in need.items():
        x = pd.read_parquet(folder / f"{d}.parquet", columns=["symbol"])
        got = set(x["symbol"].astype(str))
        total += len(syms)
        have += sum(s in got for s in syms)
    size = sum(p.stat().st_size for p in folder.glob("*.parquet"))
    cov = {"days": len(need), "symbol_days": total, "with_bars": have, "bytes": size, "sec": round(time.time() - t0)}
    (args.out / "coverage.json").write_text(json.dumps(cov, indent=1), encoding="utf-8")
    print(json.dumps(cov), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census")
    c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    sub.add_parser("minutes")
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, default=Path("outputs/v51"))
    args = ap.parse_args()
    return {"census": cmd_census, "minutes": cmd_minutes}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v51_data"
    raise SystemExit(main())
