"""v17 prepare: earnings (8-K item 2.02) and offering (424B) flags for the v14 intraday candidates, design period.
Writes outputs/v17/inputs/flags.parquet.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import v14_core as core


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P16 = _script("run_v16_prepare")
P14 = P16.P14


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v14-inputs", type=Path, default=Path("outputs/v14/inputs"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v14"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v17/inputs"))
    args = ap.parse_args()
    D = P14.load(args.v14_inputs / "daily.pkl")
    if D["dates"][-1] > core.last_day():
        raise SystemExit("v14 inputs reach past the allowed last day")
    sec = args.data / "sec"
    hist = P14.ticker_history(sec)
    f = pd.read_parquet(sec / "filings.parquet", columns=["cik", "form", "date", "items"])
    k8 = f[(f["form"] == "8-K") & f["items"].astype(str).str.contains("2.02", regex=False)].copy()
    k8["date"] = pd.to_datetime(k8["date"], errors="coerce")
    k8 = k8.dropna(subset=["date"]).drop_duplicates(["cik", "date"]).reset_index(drop=True)
    k8["symbol"] = P14.map_symbols(k8, hist)
    EARN = P16._mask(k8.dropna(subset=["symbol"]), D, lag=1)
    forms = pd.concat([pd.read_parquet(p) for p in sorted((sec / "form_index").glob("*.parquet"))], ignore_index=True)
    forms = forms[forms["form"].isin(P16.OFFER)].copy()
    forms["date"] = pd.to_datetime(forms["date"])
    forms = forms.drop_duplicates(["cik", "date"]).reset_index(drop=True)
    forms["symbol"] = P14.map_symbols(forms, hist)
    OFFER = P16._mask(forms.dropna(subset=["symbol"]), D, lag=1)
    cands = pd.read_parquet(args.v14_inputs / "cands.parquet", columns=["t", "j"])
    flags = pd.DataFrame({"earn": EARN[cands["t"], cands["j"]], "offer": OFFER[cands["t"], cands["j"]]},
                         index=cands.index)
    args.out.mkdir(parents=True, exist_ok=True)
    flags.to_parquet(args.out / "flags.parquet")
    print(json.dumps({"earn_share": float(flags["earn"].mean()), "offer_share": float(flags["offer"].mean())}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
