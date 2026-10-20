"""v16 prepare: news, shelf and repeat flags for the v14 intraday candidates, and the daily extras (raw volume,
off-exchange share, short ratio, news days, reverse splits, offerings after spikes), sealed at the design end.
Writes outputs/v16/inputs: flags.parquet and extras.pkl.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


P14 = _script("run_v14_prepare")
OFFER = ("424B1", "424B2", "424B3", "424B4", "424B5")


def _wide(df: pd.DataFrame, col: str, D: dict) -> np.ndarray:
    w = df.pivot_table(index="date", columns="symbol", values=col, aggfunc="sum")
    return w.reindex(index=D["dates"], columns=D["cols"]).to_numpy(np.float32)


def _mask(events: pd.DataFrame, D: dict, lag: int = 0) -> np.ndarray:
    """True on (t, j) where an event dated on or before the session (and within ``lag`` sessions) exists."""
    pos = {c: i for i, c in enumerate(D["cols"])}
    m = np.zeros((len(D["dates"]), len(D["cols"])), bool)
    j = events["symbol"].map(pos)
    t = D["dates"].searchsorted(pd.to_datetime(events["date"]).to_numpy(), side="left")
    ok = j.notna().to_numpy() & (t < len(D["dates"]))
    for tt, jj in zip(t[ok], j[ok].astype(int)):
        m[tt:min(tt + lag + 1, len(D["dates"])), jj] = True
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v14-inputs", type=Path, default=Path("outputs/v14/inputs"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v16/inputs"))
    args = ap.parse_args()
    D = P14.load(args.v14_inputs / "daily.pkl")
    if D["dates"][-1] > core.last_day():
        raise SystemExit("v14 inputs reach past the allowed last day")
    end = D["dates"][-1]
    daily = pd.read_parquet(args.data / "alpaca" / "daily.parquet", columns=["symbol", "date", "v"])
    daily["symbol"] = daily["symbol"].astype(str)
    daily = daily[(daily["date"] >= D["dates"][0]) & (daily["date"] <= end)].drop_duplicates(["symbol", "date"])
    V = _wide(daily, "v", D)
    del daily
    finra = pd.read_parquet(args.data / "finra" / "finra.parquet")
    finra["symbol"] = finra["symbol"].astype(str)
    finra = finra[(finra["date"] >= D["dates"][0]) & (finra["date"] <= end)]
    TRF, SV = _wide(finra, "total_vol", D), _wide(finra, "short_vol", D)
    del finra
    with np.errstate(divide="ignore", invalid="ignore"):
        OFF = np.where(V > 0, np.minimum(TRF / V, 1.0), np.nan).astype(np.float32)
        SR = np.where(TRF > 0, SV / TRF, np.nan)
    SR5 = pd.DataFrame(SR).rolling(5, min_periods=3).mean().to_numpy(np.float32)
    sec = args.data / "sec"
    hist = P14.ticker_history(sec)
    f = pd.read_parquet(sec / "filings.parquet", columns=["cik", "form", "date"])
    k8 = f[f["form"] == "8-K"].copy()
    k8["date"] = pd.to_datetime(k8["date"], errors="coerce")
    k8 = k8.dropna(subset=["date"]).drop_duplicates(["cik", "date"]).reset_index(drop=True)
    k8["symbol"] = P14.map_symbols(k8, hist)
    k8 = k8.dropna(subset=["symbol"])
    NEWS = _mask(k8, D, lag=1)  # an 8-K dated the session before or the session itself
    forms = pd.concat([pd.read_parquet(p) for p in sorted((sec / "form_index").glob("*.parquet"))], ignore_index=True)
    forms["date"] = pd.to_datetime(forms["date"])
    forms = forms.drop_duplicates(["cik", "date", "form"]).reset_index(drop=True)
    forms["symbol"] = P14.map_symbols(forms, hist)
    forms = forms.dropna(subset=["symbol"])
    shelf_ev = forms[forms["form"].isin(["S-3", "F-3", "S-3ASR"])]
    b424 = forms[forms["form"].isin(OFFER)]
    SHELF = _mask(shelf_ev, D, lag=756) | _mask(b424, D, lag=252)
    SHELF = np.vstack([np.zeros((1, SHELF.shape[1]), bool), SHELF[:-1]])  # filed before the session
    C = D["C"]
    r1 = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    big = np.nan_to_num(r1, nan=0.0) >= 0.5
    REPEAT = pd.DataFrame(big).rolling(60, min_periods=1).max().shift(1).fillna(0).to_numpy() > 0
    run5 = C / np.vstack([np.full((5, C.shape[1]), np.nan), C[:-5]]) - 1
    spike5 = pd.DataFrame(np.nan_to_num(run5, nan=0.0) >= 0.5).rolling(6, min_periods=1).max().to_numpy() > 0
    pos = {c: i for i, c in enumerate(D["cols"])}
    offer_spike = []
    for d, s in zip(b424["date"], b424["symbol"]):
        j = pos.get(s)
        tf = int(D["dates"].searchsorted(d, side="right")) - 1  # the last session on or before the filing
        if j is None or tf < 5 or tf + 1 >= len(D["dates"]):
            continue
        if spike5[tf, j]:
            offer_spike.append((tf + 1, j))
    offer_spike = sorted(set(offer_spike))
    F = D["F"]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.vstack([np.full((1, F.shape[1]), np.nan), F[:-1] / F[1:]])
    rs = np.nan_to_num(ratio, nan=0.0) >= 5
    rs &= D["valid"] & np.vstack([np.zeros((1, F.shape[1]), bool), D["valid"][:-1]])
    rsplit = [(int(t), int(j), float(ratio[t, j])) for t, j in zip(*np.nonzero(rs))]
    E = {"V": V, "OFF": OFF, "SR5": SR5, "NEWS": NEWS, "offer_spike": offer_spike, "rsplit": rsplit}
    cands = pd.read_parquet(args.v14_inputs / "cands.parquet", columns=["t", "j"])
    flags = pd.DataFrame({"news": NEWS[cands["t"], cands["j"]], "shelf": SHELF[cands["t"], cands["j"]],
                          "repeat": REPEAT[cands["t"], cands["j"]]}, index=cands.index)
    args.out.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(args.out / "flags.parquet")
    P14.dump(E, args.out / "extras.pkl")
    print(json.dumps({"news_share_of_candidates": float(flags["news"].mean()),
                      "shelf_share": float(flags["shelf"].mean()), "repeat_share": float(flags["repeat"].mean()),
                      "offer_spikes": len(offer_spike), "reverse_splits": len(rsplit),
                      "off_exchange_median": float(np.nanmedian(OFF)), "short_ratio_median": float(np.nanmedian(SR5))}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
