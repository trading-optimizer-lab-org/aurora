"""v23 shards, selection and report: run_v22's procedure on the one-minute families of research/v23_ta1m.py.
Pre-registered in docs/research/V23_PREREGISTRATION.md.

The same stages as run_v22 (real, select, placebo, report; the activity rule, 500 placebos for the selected
configurations, SPA, PBO, deflated Sharpe); the inputs add the v23 minute store of the 100 most liquid small caps of
each session (``--liquid``, default outputs/v23/store).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v23_ta1m as v23


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
LIQUID = Path(os.environ.get("V23_LIQUID", "outputs/v23/store"))
_base_load = R19.load


def registry() -> dict[str, tuple[str, list[dict]]]:
    return {k: ("intra", core.grid(d)) for k, d in v23.INTRA_DIMS.items()}


def load(base: Path) -> None:
    _base_load(base)
    cands = pd.read_parquet(LIQUID / "cands.parquet")
    arr = np.load(LIQUID / "store.npz")
    R14._G["liquid"] = vi.Store(cands, {k: arr[k] for k in vi.FIELDS})


_P: dict = {}


def evaluate(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    g = registry()[key][1][ci]
    D, ev, lq, table = R14._G["D"], R14._G["store"], R14._G["liquid"], R16._W["table"]
    dates = D["dates"]
    v19.set_costs("r4", R22.SLIP, R22.R4)
    tr = v23.trades(ev, lq, D, key, g)
    if placebo_rng is not None:
        pk = (g["scope"], g["band"])
        if pk not in _P:
            _P[pk] = v23.pool_by_day(ev, lq, g)
        st, pool = _P[pk]
        return v19.intra_book(v23.placebo(st, pool, D, key, g, tr, placebo_rng), dates, table, 1.0)[0], None, None
    out, paths, taken = {}, [], np.zeros(0, bool)
    for name, half, spread, fee, gross in R22.SCEN:
        v19.set_costs("r4", R22.SLIP, half)
        s, p_, t_ = v19.intra_book(tr, dates, table, spread, fee, gross)
        out[name] = s
        if name == "mid":
            paths, taken = p_, t_
    v19.set_costs("r4", 0.0, R22.R4)
    try:
        out["gross"] = v19.intra_book(v23.trades(ev, lq, D, key, g), dates, table, 0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", R22.SLIP, R22.R4)
    return out, paths, taken


R22.registry = registry
R22.evaluate = evaluate
R22.R19.load = load
R22.TITLE, R22.COMBO = "v23: technical analysis on one-minute bars of small caps", "COMBO23"


if __name__ == "__main__":
    sys.argv[0] = "run_v23"
    raise SystemExit(R22.main())
