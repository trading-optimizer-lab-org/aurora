"""v23 data: one-minute bars of the most liquid small caps of every day, event or not (V23_PREREGISTRATION.md).

  minutes  Alpaca SIP minute bars (04:00-15:59 ET, raw prices) of the top 100 small caps of each session by the
           prior 20-day dollar volume, among those whose prior close is $1-$20, 2016-01-04 to 2026-10-16
  store    the v23 minute store in v14's Store layout: each symbol-day's regular-session bars and its facts (prior
           close, open, gap, premarket high, low and dollar volume, the prior day's high and low, the high and low of
           the five sessions before, shares outstanding, the liquidity rank), all on that day's raw scale
Only the store is kept (in the Actions cache); nothing is published.
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

from aurora.research import v14_core as core


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D14 = _script("run_v14_data")
P14 = _script("run_v14_prepare")
TOP = 100
FIELDS = ("m", "o", "h", "l", "c", "v", "vw")


def liquid_sets(D: dict, top: int = TOP) -> dict[int, list[int]]:
    """Row -> the columns of the ``top`` small caps by the prior 20-day dollar volume (prior close $1-$20)."""
    P1, DV1, ok = D["P1"], D["DV1"], D["valid1"]
    out = {}
    start = int(np.searchsorted(D["dates"], core.DESIGN_START))
    for t in range(start, len(D["dates"])):
        with np.errstate(invalid="ignore"):
            elig = ok[t] & (P1[t] >= 1) & (P1[t] <= 20) & np.isfinite(DV1[t]) & (DV1[t] >= 1e6)
        cols = np.flatnonzero(elig)
        if len(cols):
            out[t] = cols[np.argsort(-DV1[t, cols], kind="stable")[:top]].tolist()
    return out


def cmd_minutes(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    sets = liquid_sets(D)
    folder = args.out / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    todo = [(t, cols) for t, cols in sets.items() if not (folder / f"{D['dates'][t].date()}.parquet").exists()]
    print(f"days to fetch: {len(todo)} of {len(sets)}", flush=True)

    def one(t, cols):
        if time.time() - t0 < args.budget_min * 60:
            D14._minute_day(D["dates"][t], [str(D["cols"][j]) for j in cols], folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, t, c) for t, c in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 200 == 0:
                print(f"minute bars: {n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    left = sum(1 for t in sets if not (folder / f"{D['dates'][t].date()}.parquet").exists())
    print(json.dumps({"days": len(sets), "days_missing": left, "alpaca_calls": limiter.calls}), flush=True)
    return 0


def build_store(D: dict, sets: dict, folder: Path) -> tuple[pd.DataFrame, dict]:
    C, H, L, F, SO = D["C"], D["H"], D["L"], D["F"], D["SO"]
    pos = {str(c): i for i, c in enumerate(D["cols"])}
    rows, arrays, off = [], {k: [] for k in FIELDS}, 0
    for t, cols in sorted(sets.items()):
        day = D["dates"][t]
        path = folder / f"{day.date()}.parquet"
        if not path.exists() or t < 6:
            continue
        rank = {j: r for r, j in enumerate(cols)}
        bars = pd.read_parquet(path)
        for sym, b in bars.groupby("symbol", sort=False):
            j = pos.get(str(sym))
            if j is None or j not in rank:
                continue
            mm = b["minute"].to_numpy()
            pre, reg = b[mm < 330], b[(mm >= 330) & (mm < 720)]
            if len(reg) < 30:
                continue
            f = F[t, j]
            if not np.isfinite(f) or f <= 0:
                continue
            pc = C[t - 1, j] / f
            pv = np.where(np.isfinite(pre["vw"]), pre["vw"], pre["c"])
            op = float(reg["o"].iloc[0])
            rows.append({"date": day, "symbol": str(sym), "t": t, "j": j, "off": off, "n": len(reg), "open": op,
                         "pc": pc, "gap": op / pc - 1 if pc > 0 else np.nan,
                         "pmv": float((pv * pre["v"]).sum()), "pmh": float(pre["h"].max()) if len(pre) else np.nan,
                         "pml": float(pre["l"].min()) if len(pre) else np.nan,
                         "pdh": H[t - 1, j] / f, "pdl": L[t - 1, j] / f,
                         "h5": float(np.nanmax(H[t - 5:t, j])) / f, "l5": float(np.nanmin(L[t - 5:t, j])) / f,
                         "so": SO[t, j], "rank": rank[j]})
            arrays["m"].append((reg["minute"].to_numpy() - 330).astype(np.int16))
            for k in ("o", "h", "l", "c", "v", "vw"):
                arrays[k].append(reg[k].to_numpy(np.float32))
            off += len(reg)
        if t % 250 == 0:
            print(f"store: {day.date()}, {len(rows)} symbol-days", flush=True)
    return pd.DataFrame(rows), {k: np.concatenate(v) if v else np.zeros(0) for k, v in arrays.items()}


def cmd_store(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    cands, arrays = build_store(D, liquid_sets(D), args.out / "minutes")
    store = args.out / "store"
    store.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(store / "store.npz", **arrays)
    cands.to_parquet(store / "cands.parquet", index=False)
    print(json.dumps({"symbol_days": len(cands), "bars": int(len(arrays["c"])),
                      "first": str(cands["date"].min().date()) if len(cands) else None,
                      "last": str(cands["date"].max().date()) if len(cands) else None}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("minutes", "store"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v23"))
    ap.add_argument("--budget-min", type=float, default=290.0)
    args = ap.parse_args()
    return {"minutes": cmd_minutes, "store": cmd_store}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
