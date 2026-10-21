"""v24 data: one-minute bars of the small caps that gap 4% or more each day (V24_PREREGISTRATION.md).

  minutes  Alpaca SIP minute bars (04:00-15:59 ET, raw prices) of the 100 small caps of each session with the
           largest absolute opening gap of at least 4% (prior close $1-$20, prior 20-day dollar volume >= $500k),
           leaving out that day's v23 top-100 liquid set (already in the v23 store), 2016-01-04 to 2026-10-16
  store    the v24 mover store in v23's layout (scripts/run_v23_data.py build_store)
The gap is the day's open over the prior close, known at 09:30. Only the store is kept (in the Actions cache);
nothing is published.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from aurora.research import v14_core as core


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D23 = _script("run_v23_data")
D14, P14 = D23.D14, D23.P14
TOP, MIN_GAP, MIN_DV = 100, 0.04, 5e5


def mover_sets(D: dict, top: int = TOP) -> dict[int, list[int]]:
    """Row -> the columns of the ``top`` small caps by absolute gap (>= 4%), outside that day's v23 liquid set."""
    O, C, P1, DV1, ok = D["O"], D["C"], D["P1"], D["DV1"], D["valid1"]
    liquid = D23.liquid_sets(D)
    out = {}
    start = int(np.searchsorted(D["dates"], core.DESIGN_START))
    for t in range(max(start, 1), len(D["dates"])):
        with np.errstate(invalid="ignore", divide="ignore"):
            gap = O[t] / C[t - 1] - 1
            elig = ok[t] & (P1[t] >= 1) & (P1[t] <= 20) & np.isfinite(DV1[t]) & (DV1[t] >= MIN_DV) & \
                np.isfinite(gap) & (np.abs(gap) >= MIN_GAP)
        elig[liquid.get(t, [])] = False
        cols = np.flatnonzero(elig)
        if len(cols):
            out[t] = cols[np.argsort(-np.abs(gap[cols]), kind="stable")[:top]].tolist()
    return out


def cmd_minutes(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    sets = mover_sets(D)
    folder = args.out / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    todo = [(t, cols) for t, cols in sets.items() if not (folder / f"{D['dates'][t].date()}.parquet").exists()]
    print(f"days to fetch: {len(todo)} of {len(sets)}, symbol-days {sum(len(c) for c in sets.values())}", flush=True)

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


def cmd_store(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    cands, arrays = D23.build_store(D, mover_sets(D), args.out / "minutes")
    store = args.out / "store"
    store.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(store / "store.npz", **arrays)
    cands.to_parquet(store / "cands.parquet", index=False)
    print(json.dumps({"symbol_days": len(cands), "bars": int(len(arrays["c"])),
                      "gap_up": int((cands["gap"] > 0).sum()) if len(cands) else 0,
                      "first": str(cands["date"].min().date()) if len(cands) else None,
                      "last": str(cands["date"].max().date()) if len(cands) else None}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("minutes", "store"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v24"))
    ap.add_argument("--budget-min", type=float, default=290.0)
    args = ap.parse_args()
    return {"minutes": cmd_minutes, "store": cmd_store}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
