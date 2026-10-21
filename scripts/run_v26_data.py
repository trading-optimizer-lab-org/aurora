"""v26 data: the nights after the small-cap events, for the squeeze shield (V26_PREREGISTRATION.md).

  nights   Alpaca SIP minute bars (raw prices) from 16:00 ET of a session to 09:29 ET of the next one (the after-hours
           session, then the next premarket) for every small cap with an event on that session or on one of the five
           sessions before it; an event is a gap of 15% or more, a high 40% or more over the prior close, a close
           30% or more over it, a prior day of +50% or more, or a close 50% or more over the lowest close of the 5 or
           20 sessions before (prior close $1-$20, prior 20-day dollar volume >= $500k; at most 150 events a
           session, by the largest of those moves). Nights are fetched in a seeded random order, so a budget cut
           leaves random nights missing, not whole years.
  quotes   Alpaca SIP quotes in 3,000 minutes drawn from those bars (seeded; 375 per price tier and session, the
           after-hours and the premarket): the median quoted spread over the mid in the minute.
  store    the night store: per night row, each symbol's bars as minutes after 16:00 ET (0-239 after hours,
           240-569 the next premarket from 04:00)
Only the store and the measured spreads are kept (in the Actions cache); nothing is published.
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
import pandas as pd

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
QUOTES = "https://data.alpaca.markets/v2/stocks/quotes"
AFTER, NIGHTS, TOP = 5, 6, 150  # an event's session and the five after it; events kept a session
AH_END, PM_START, SPAN = 240, 240, 570
TIERS = (2.0, 5.0, 10.0)
PER_CELL = 375


def events(D: dict) -> dict[int, list[int]]:
    """Row -> the columns with an event on that session (known at its close)."""
    O, H, C, P1, DV1 = D["O"], D["H"], D["C"], D["P1"], D["DV1"]
    ok = D["valid"] & D["valid1"]
    out = {}
    start = int(np.searchsorted(D["dates"], core.DESIGN_START))
    low5 = pd.DataFrame(C).rolling(5, min_periods=3).min().shift(1).to_numpy()
    low20 = pd.DataFrame(C).rolling(20, min_periods=10).min().shift(1).to_numpy()
    for t in range(max(start, 2), len(D["dates"])):
        with np.errstate(invalid="ignore", divide="ignore"):
            prev = C[t - 1]
            moves = np.vstack([O[t] / prev - 1 - 0.15, H[t] / prev - 1 - 0.40, C[t] / prev - 1 - 0.30,
                               prev / C[t - 2] - 1 - 0.50, C[t] / low5[t] - 1 - 0.50, C[t] / low20[t] - 1 - 0.50])
            score = np.nanmax(np.where(np.isfinite(moves), moves, -np.inf), axis=0)
            elig = ok[t] & (P1[t] >= 1) & (P1[t] <= 20) & np.isfinite(DV1[t]) & (DV1[t] >= 5e5) & (score >= 0)
        cols = np.flatnonzero(elig)
        if len(cols):
            out[t] = cols[np.argsort(-score[cols], kind="stable")[:TOP]].tolist()
    return out


def night_sets(D: dict) -> dict[int, list[int]]:
    """Night row u (16:00 of session u to 09:29 of session u + 1) -> the columns held over it by any event on
    sessions u - 5 .. u."""
    ev = events(D)
    out: dict[int, set] = {}
    last = len(D["dates"]) - 1
    for t, cols in ev.items():
        for u in range(t, min(t + NIGHTS, last)):
            out.setdefault(u, set()).update(cols)
    return {u: sorted(c) for u, c in sorted(out.items())}


def _night(D: dict, u: int, cols: list[int], folder: Path, headers: dict, limiter) -> None:
    day, nxt = D["dates"][u], D["dates"][u + 1]
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    syms = [str(D["cols"][j]) for j in cols]
    rows = []
    for i in range(0, len(syms), 200):
        rows += D14._bars(syms[i:i + 200], "1Min", D14._ny(day, 16, 0), D14._ny(nxt, 9, 29), "raw", headers, limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    ts = pd.to_datetime(df.pop("t"), utc=True)
    ah = (ts - D14._ny(day, 16, 0)).dt.total_seconds() // 60
    pm = (ts - D14._ny(nxt, 4, 0)).dt.total_seconds() // 60 + PM_START
    m = np.where((ah >= 0) & (ah < AH_END), ah, np.where((pm >= PM_START) & (pm < SPAN), pm, -1))
    df["minute"] = m.astype(np.int16)
    df = df[df["minute"] >= 0][["symbol", "minute", "o", "h", "l", "c", "v"]]
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(np.float32)
    D14._write(df.sort_values(["symbol", "minute"]), path)


def cmd_nights(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    sets = night_sets(D)
    folder = args.out / "nights"
    folder.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    order = np.random.default_rng(26).permutation(sorted(sets))
    todo = [int(u) for u in order if not (folder / f"{D['dates'][int(u)].date()}.parquet").exists()]
    print(json.dumps({"nights": len(sets), "to_fetch": len(todo),
                      "symbol_nights": sum(len(c) for c in sets.values())}), flush=True)
    t0 = time.time()

    def one(u):
        if time.time() - t0 < args.budget_min * 60:
            _night(D, u, sets[u], folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, u) for u in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 200 == 0:
                print(f"nights: {n}/{len(todo)}, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    left = sum(1 for u in sets if not (folder / f"{D['dates'][u].date()}.parquet").exists())
    print(json.dumps({"nights": len(sets), "nights_missing": left, "alpaca_calls": limiter.calls}), flush=True)
    return 0


def build_store(D: dict, sets: dict, folder: Path) -> tuple[pd.DataFrame, dict]:
    pos = {str(c): i for i, c in enumerate(D["cols"])}
    arrays: dict[str, list] = {k: [] for k in ("m", "o", "h", "l", "c", "v")}
    rows, off = [], 0
    for u, cols in sets.items():
        path = folder / f"{D['dates'][u].date()}.parquet"
        if not path.exists():
            continue
        keep = set(cols)
        for sym, b in pd.read_parquet(path).groupby("symbol", sort=False):
            j = pos.get(str(sym))
            if j is None or j not in keep:
                continue
            rows.append({"u": u, "j": j, "off": off, "n": len(b)})
            arrays["m"].append(b["minute"].to_numpy(np.int16))
            for k in ("o", "h", "l", "c", "v"):
                arrays[k].append(b[k].to_numpy(np.float32))
            off += len(b)
    fetched = [u for u in sets if (folder / f"{D['dates'][u].date()}.parquet").exists()]
    return pd.DataFrame(rows), {**{k: np.concatenate(v) if v else np.zeros(0) for k, v in arrays.items()},
                                "fetched": np.array(sorted(fetched), np.int32)}


def cmd_store(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    sets = night_sets(D)
    index, arrays = build_store(D, sets, args.out / "nights")
    store = args.out / "store"
    store.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(store / "nights.npz", **arrays)
    index.to_parquet(store / "nights.parquet", index=False)
    print(json.dumps({"symbol_nights": len(index), "bars": int(len(arrays["c"])),
                      "nights_fetched": int(len(arrays["fetched"])), "nights": len(sets)}), flush=True)
    return 0


def _tier(px: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.array(TIERS), px, side="right")


def _quote(sym: str, start: pd.Timestamp, headers: dict, limiter) -> tuple[float, int]:
    params = {"symbols": sym, "start": start.isoformat(), "end": (start + pd.Timedelta(minutes=1)).isoformat(),
              "feed": "sip", "limit": 10000}
    body = D14.V9._get(QUOTES, params, headers, limiter) or {}
    q = (body.get("quotes") or {}).get(sym, [])
    rel = [(x["ap"] - x["bp"]) / ((x["ap"] + x["bp"]) / 2) for x in q
           if x.get("ap", 0) > 0 and x.get("bp", 0) > 0 and x["ap"] > x["bp"]]
    return (float(np.median(rel)) if rel else np.nan), len(rel)


def cmd_quotes(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    store = args.out / "store"
    index = pd.read_parquet(store / "nights.parquet")
    z = np.load(store / "nights.npz")
    m, c, v = z["m"], z["c"], z["v"]
    rows = np.repeat(np.arange(len(index)), index["n"].to_numpy())
    traded = v > 0
    session = (m >= AH_END).astype(int)  # 0 after hours, 1 premarket
    tier = _tier(c)
    rng = np.random.default_rng(26)
    picks = []
    for ses in (0, 1):
        for k in range(len(TIERS) + 1):
            cand = np.flatnonzero(traded & (session == ses) & (tier == k))
            if len(cand):
                picks += rng.choice(cand, min(PER_CELL, len(cand)), replace=False).tolist()
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    jobs = []
    for i in picks:
        r = index.iloc[rows[i]]
        u, mm = int(r["u"]), int(m[i])
        day = D["dates"][u] if mm < AH_END else D["dates"][u + 1]
        start = D14._ny(day, 16, 0) + pd.Timedelta(minutes=mm) if mm < AH_END else \
            D14._ny(day, 4, 0) + pd.Timedelta(minutes=mm - PM_START)
        jobs.append((str(D["cols"][int(r["j"])]), start, int(session[i]), int(tier[i]), float(c[i])))
    out, t0 = [], time.time()
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(_quote, s, st, headers, limiter): (s, st, se, ti, px) for s, st, se, ti, px in jobs}
        for n, f in enumerate(as_completed(futs)):
            s, st, se, ti, px = futs[f]
            spread, k = f.result()
            out.append({"symbol": s, "start": st, "session": se, "tier": ti, "price": px, "spread": spread, "n": k})
            if n % 500 == 0:
                print(f"quotes: {n}/{len(jobs)}, {time.time() - t0:.0f}s", flush=True)
    q = pd.DataFrame(out)
    q.to_parquet(store / "spreads.parquet", index=False)
    med = q.dropna(subset=["spread"]).groupby(["session", "tier"])["spread"].agg(["median", "count"]).reset_index()
    cells = {("ah" if int(r["session"]) == 0 else "pm") + str(int(r["tier"])): [round(float(r["median"]), 4),
                                                                                 int(r["count"])]
             for _, r in med.iterrows()}
    print(json.dumps({"minutes": len(q), "with_quotes": int(q["spread"].notna().sum()), "median_spread": cells}),
          flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("nights", "store", "quotes"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v26"))
    ap.add_argument("--budget-min", type=float, default=200.0)
    args = ap.parse_args()
    return {"nights": cmd_nights, "store": cmd_store, "quotes": cmd_quotes}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
