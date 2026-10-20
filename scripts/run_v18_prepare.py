"""v18 prepare: the per-candidate flags (catalyst type, runs in the last 60 sessions, prior-day short ratio and
off-exchange share, a shelf or offering in the last 30 days) and the daily masks (offering and earnings days) on top
of rebuilt v14, v16 and v17 inputs (run with the unlock: the whole sample through 2026-10-16).
Writes outputs/v18/inputs/flags.parquet and extras.pkl.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


P16 = _script("run_v16_prepare")
P14 = P16.P14
ITEMS = ("1.01", "8.01", "2.02", "7.01")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v14-inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--v16-inputs", type=Path, default=Path("outputs/v18/v16"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v18/inputs"))
    args = ap.parse_args()
    D = P14.load(args.v14_inputs / "daily.pkl")
    E = P14.load(args.v16_inputs / "extras.pkl")
    sec = args.data / "sec"
    hist = P14.ticker_history(sec)
    f = pd.read_parquet(sec / "filings.parquet", columns=["cik", "form", "date", "items"])
    k8 = f[f["form"] == "8-K"].copy()
    k8["date"] = pd.to_datetime(k8["date"], errors="coerce")
    k8 = k8.dropna(subset=["date"]).reset_index(drop=True)
    k8["symbol"] = P14.map_symbols(k8, hist)
    k8 = k8.dropna(subset=["symbol"])
    masks = {it: P16._mask(k8[k8["items"].astype(str).str.contains(it, regex=False)], D, lag=1) for it in ITEMS}
    any8k = P16._mask(k8, D, lag=1)
    forms = pd.concat([pd.read_parquet(p) for p in sorted((sec / "form_index").glob("*.parquet"))], ignore_index=True)
    forms["date"] = pd.to_datetime(forms["date"])
    forms = forms.drop_duplicates(["cik", "date", "form"]).reset_index(drop=True)
    forms["symbol"] = P14.map_symbols(forms, hist)
    forms = forms.dropna(subset=["symbol"])
    offer_ev = forms[forms["form"].isin(P16.OFFER)]
    shelf_ev = forms[forms["form"].isin(["S-3", "F-3", "S-3ASR"]) | forms["form"].isin(P16.OFFER)]
    OFFER = P16._mask(offer_ev, D, lag=1)
    SHELF30 = P16._mask(shelf_ev, D, lag=21)
    SHELF30 = np.vstack([np.zeros((1, SHELF30.shape[1]), bool), SHELF30[:-1]])
    C = D["C"]
    r1 = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    RUNS = pd.DataFrame((np.nan_to_num(r1, nan=0.0) >= 0.5).astype(np.int16)).rolling(60, min_periods=1).sum().shift(
        1).fillna(0).to_numpy()
    SRp = np.vstack([np.full((1, C.shape[1]), np.nan), E["SR5"][:-1]])
    OFFp = np.vstack([np.full((1, C.shape[1]), np.nan), E["OFF"][:-1]])
    cands = pd.read_parquet(args.v14_inputs / "cands.parquet", columns=["t", "j"])
    t, j = cands["t"].to_numpy(), cands["j"].to_numpy()
    cat = np.full(len(cands), "none", dtype=object)
    cat[any8k[t, j]] = "other"
    for it in ITEMS[::-1]:  # the earliest-listed item wins when several are filed
        cat[masks[it][t, j]] = it
    flags = pd.DataFrame({"catalyst": cat, "runs60": RUNS[t, j], "sr_prev": SRp[t, j], "off_prev": OFFp[t, j],
                          "shelf30": SHELF30[t, j]}, index=cands.index)
    args.out.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(args.out / "flags.parquet")
    P14.dump({"OFFER": OFFER, "EARN": masks["2.02"]}, args.out / "extras.pkl")
    print(json.dumps({"catalyst": flags["catalyst"].value_counts().to_dict(), "shelf30": float(flags["shelf30"].mean()),
                      "runs60_ge2": float((flags["runs60"] >= 2).mean())}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
