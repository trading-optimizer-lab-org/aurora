"""v44 part N: run_v22's procedure (real shards, walk-forward selection, placebos, report) on the fifteen new
one-minute families of research/v44_new1m.py (V44_PREREGISTRATION.md section 2).

Inputs add the v23 liquid store (``V23_LIQUID``), the v24 mover store (``V24_MOVERS``), v28's extras (``V28_INPUTS``:
short interest, days to cover, SIC codes) and the v44 data (``V44_DATA``: news, filings, the filing store, BTC and IWM
minutes). Costs as run_v22 plus ``strict``: stops filled at the crossing bar's extreme. The configurations are dealt
in blocks that share a feature key, in a seeded order.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v44_new1m as v44


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # so the worker pool pickles run_v22._work as this (patched) module's function
    spec.loader.exec_module(module)
    return module


R22 = _script("run_v22")
R19, R16, R14 = R22.R19, R22.R16, R22.R14
DV = _script("run_v44_data")
LIQUID = Path(os.environ.get("V23_LIQUID", "outputs/v23/store"))
MOVERS = Path(os.environ.get("V24_MOVERS", "outputs/v24/store"))
INPUTS28 = Path(os.environ.get("V28_INPUTS", "outputs/v28/inputs"))
DATA = Path(os.environ.get("V44_DATA", "outputs/v44"))
STRICT_SLIP = 1.0
_base_load = R19.load
_S: dict = {}


def registry() -> dict[str, tuple[str, list[dict]]]:
    if "reg" not in _S:
        _S["reg"] = {k: ("intra", core.grid(d)) for k, d in v44.INTRA_DIMS.items()}
    return _S["reg"]


def configs() -> list[tuple[str, int]]:
    """Blocks of the configurations that share a feature key, in a seeded order (a block computes its costly
    arrays once)."""
    groups: dict = {}
    for k, (_, cfgs) in registry().items():
        for i, g in enumerate(cfgs):
            groups.setdefault(v44.feat_key(k, g), []).append((k, i))
    keys = sorted(groups, key=str)
    order = np.random.default_rng(44).permutation(len(keys))
    return [c for o in order for c in groups[keys[o]]]


def _store(folder: Path) -> vi.Store:
    arr = np.load(folder / "store.npz")
    return vi.Store(pd.read_parquet(folder / "cands.parquet"), {k: arr[k] for k in vi.FIELDS})


def _ny(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)


def news_events(D: dict, news: pd.DataFrame) -> pd.DataFrame:
    """One row per (news item, symbol) on its session with its headline class."""
    x = news.assign(symbol=news["symbols"].astype(str).str.split(",")).explode("symbol")
    x = x[x["symbol"].astype(bool)].reset_index(drop=True)
    ev = DV.session_events(D, x["symbol"], _ny(x["created_at"]))
    ev["code"] = x["headline"].map(v44.news_class).to_numpy()[ev.index]
    return ev


def edgar_rows(D: dict, edgar: pd.DataFrame) -> pd.DataFrame:
    ev = DV.edgar_events(D, edgar)
    ev["code"] = [v44.form_codes(f, i) for f, i in zip(ev["form"], ev["items"])]
    return ev.explode("code").dropna(subset=["code"]).astype({"code": int})


def btc_arrays(D: dict, btc: pd.DataFrame) -> dict:
    """BTC closes at every regular minute of each session (forward filled), the standard deviation of its 1, 5 and
    15-minute log returns over the five sessions before, and its 16:00-to-16:00 daily returns."""
    ts = _ny(btc["ts"])
    df = pd.DataFrame({"date": ts.dt.normalize(), "minute": ((ts - ts.dt.normalize()).dt.total_seconds() // 60
                                                             ).astype(int), "c": btc["c"].to_numpy(float)})
    mins = v44.minute_closes(df, D, 570)
    T = len(D["dates"])
    sig = np.full((T, 3), np.nan)
    lm = np.log(np.where(mins > 0, mins, np.nan))
    for q, k in enumerate((1, 5, 15)):
        r = lm[:, k:] - lm[:, :-k]
        sd = np.nanstd(r, axis=1)
        sig[:, q] = pd.Series(sd).shift(1).rolling(5, min_periods=3).mean().to_numpy()
    close = mins[:, -1].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        day = np.r_[np.nan, close[1:] / close[:-1] - 1]
    return {"btc_min": mins, "btc_sig": sig, "btc_day": day}


def iwm_arrays(D: dict, idx: pd.DataFrame) -> dict:
    x = idx[idx["symbol"] == "IWM"]
    mins = v44.minute_closes(x[["date", "minute", "c"]], D, 330)
    close = mins[:, -1].astype(float)
    pc = np.r_[np.nan, close[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        day = close / pc - 1
    return {"iwm_min": mins, "iwm_pc": pc, "iwm_day": day}


def extras(D: dict) -> dict:
    out: dict = {"D": D}
    ex28 = R14.PREP.load(INPUTS28 / "extras28.pkl")
    for k in ("si_so", "dtc", "sic"):
        if k in ex28:
            out[k] = ex28[k]
    if (DATA / "news.parquet").exists():
        out["news"] = v44.event_index(news_events(D, pd.read_parquet(DATA / "news.parquet")), "code")
    if (DATA / "edgar.parquet").exists():
        out["edgar"] = v44.event_index(edgar_rows(D, pd.read_parquet(DATA / "edgar.parquet")), "code")
    if (DATA / "btc.parquet").exists():
        out.update(btc_arrays(D, pd.read_parquet(DATA / "btc.parquet")))
    if (DATA / "index.parquet").exists():
        out.update(iwm_arrays(D, pd.read_parquet(DATA / "index.parquet")))
    return out


def load(base: Path) -> None:
    _base_load(base)
    D = R14._G["D"]
    stores = {"event": R14._G["store"], "liquid": _store(LIQUID), "mover": _store(MOVERS)}
    if (DATA / "filing" / "store" / "cands.parquet").exists():
        stores["filing"] = _store(DATA / "filing" / "store")
    v44.prepare(stores, D, extras(D))
    R14._G["v44"] = stores
    print(json.dumps({"stores": {k: len(v.cands) for k, v in stores.items()},
                      "news_symbol_days": len(v44.X.get("news", {})), "edgar_symbol_days": len(v44.X.get("edgar", {})),
                      "btc": "btc_min" in v44.X, "iwm": "iwm_min" in v44.X}), flush=True)


_P: dict = {}
SCEN = R22.SCEN + (("strict", R22.R4, 1.0, 1.0, False),)


def evaluate(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    g = registry()[key][1][ci]
    D, stores, table = R14._G["D"], R14._G["v44"], R16._W["table"]
    dates = D["dates"]
    v19.set_costs("r4", R22.SLIP, R22.R4)
    tr = v44.trades(stores, D, key, g)
    if placebo_rng is not None:
        pk = (g["scope"], g["band"])
        if pk not in _P:
            _P[pk] = v44.pool_by_day(stores, g)
        return v19.intra_book(v44.placebo(stores, _P[pk], D, key, g, tr, placebo_rng), dates, table, 1.0)[0], \
            None, None
    out, paths, taken = {}, [], np.zeros(0, bool)
    for name, half, spread, fee, gross in SCEN:
        if name == "strict":
            v19.set_costs("r4", STRICT_SLIP, half)
            s = v19.intra_book(v44.trades(stores, D, key, g), dates, table, spread, fee, gross)[0]
        else:
            v19.set_costs("r4", R22.SLIP, half)
            s, p_, t_ = v19.intra_book(tr, dates, table, spread, fee, gross)
            if name == "mid":
                paths, taken = p_, t_
        out[name] = s
    v19.set_costs("r4", 0.0, R22.R4)
    try:
        out["gross"] = v19.intra_book(v44.trades(stores, D, key, g), dates, table, 0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", R22.SLIP, R22.R4)
    return out, paths, taken


R22.registry = registry
R22.configs = configs
R22.evaluate = evaluate
R22.R19.load = load
R22.TITLE, R22.COMBO = "v44: new one-minute ideas on small caps", "COMBO44"


if __name__ == "__main__":
    sys.argv[0] = "run_v44n"
    raise SystemExit(R22.main())
