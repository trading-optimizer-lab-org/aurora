"""v24 shards, selection and report: run_v22's procedure on the long-only one-minute families of
research/v24_long1m.py. Pre-registered in docs/research/V24_PREREGISTRATION.md.

The same stages as run_v22 and run_v23 (real, select, placebo, report; the activity rule, 500 placebos for the
selected configurations, SPA, PBO, deflated Sharpe); the inputs add the v23 liquid store (``V23_LIQUID``, default
outputs/v23/store) and the v24 mover store (``V24_MOVERS``, default outputs/v24/store). The configurations are dealt
to the shards in a fixed shuffled order so that no shard gets a whole slow family.
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
from aurora.research import v24_long1m as v24


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
MOVERS = Path(os.environ.get("V24_MOVERS", "outputs/v24/store"))
_base_load = R19.load
_S: dict = {}


def registry() -> dict[str, tuple[str, list[dict]]]:
    if "reg" not in _S:
        _S["reg"] = {k: ("intra", core.grid(d)) for k, d in v24.INTRA_DIMS.items()}
    return _S["reg"]


def configs() -> list[tuple[str, int]]:
    allc = [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]
    order = np.random.default_rng(24).permutation(len(allc))
    return [allc[i] for i in order]


def _store(folder: Path) -> vi.Store:
    arr = np.load(folder / "store.npz")
    return vi.Store(pd.read_parquet(folder / "cands.parquet"), {k: arr[k] for k in vi.FIELDS})


def load(base: Path) -> None:
    _base_load(base)
    stores = {"event": R14._G["store"], "liquid": _store(LIQUID), "mover": _store(MOVERS)}
    v24.prepare(stores, R14._G["D"])
    R14._G["v24"] = stores


_P: dict = {}


def evaluate(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    g = registry()[key][1][ci]
    D, stores, table = R14._G["D"], R14._G["v24"], R16._W["table"]
    dates = D["dates"]
    v19.set_costs("r4", R22.SLIP, R22.R4)
    tr = v24.trades(stores, D, key, g)
    if placebo_rng is not None:
        pk = (g["scope"], g["band"], g.get("sel"))
        if pk not in _P:
            _P[pk] = v24.pool_by_day(stores, g)
        return v19.intra_book(v24.placebo(stores, _P[pk], D, key, g, tr, placebo_rng), dates, table, 1.0)[0], \
            None, None
    out, paths, taken = {}, [], np.zeros(0, bool)
    for name, half, spread, fee, gross in R22.SCEN:
        v19.set_costs("r4", R22.SLIP, half)
        s, p_, t_ = v19.intra_book(tr, dates, table, spread, fee, gross)
        out[name] = s
        if name == "mid":
            paths, taken = p_, t_
    v19.set_costs("r4", 0.0, R22.R4)
    try:
        out["gross"] = v19.intra_book(v24.trades(stores, D, key, g), dates, table, 0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", R22.SLIP, R22.R4)
    return out, paths, taken


R22.registry = registry
R22.configs = configs
R22.evaluate = evaluate
R22.R19.load = load
R22.TITLE, R22.COMBO = "v24: long-only small caps on one-minute bars", "COMBO24"


if __name__ == "__main__":
    sys.argv[0] = "run_v24"
    raise SystemExit(R22.main())
