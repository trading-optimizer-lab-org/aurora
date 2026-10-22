"""v28 megarun: run_v22's procedure (real shards, walk-forward selection, placebos, report) on every v28 family.
Pre-registered in docs/research/V28_PREREGISTRATION.md.

  B:*  v26's 103 short entries crossed with the shield (holds up to ten sessions, stops, extended-session stops,
       profit targets) and 30 new name and regime filters, the squeeze-risk model's among them
  C:*  new short entries: filings (EFFECT, 8-K 3.02, NT 10-K/10-Q, first going-concern doubt, crypto treasury, former
       names, de-SPAC, S-4, earnings fades), small IPOs, lock-up ends, sympathy moves, premarket and after-hours
       entries; under the shield
  D:*  longs and diversifiers: PDUFA run-ups, buybacks, January losers, runner baskets on mania days, monthly
       factor books, leveraged ETF pairs
Inputs add v28's extras (``V28_INPUTS``, default outputs/v28/inputs) and the gap-day premarket store (``V28_PM``).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from aurora.research import v28_ideas as v28


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R26 = _script("run_v26")
R22 = R26.R22
R19, R16, R14 = R22.R19, R22.R16, R22.R14
INPUTS28 = Path(os.environ.get("V28_INPUTS", "outputs/v28/inputs"))
PM = Path(os.environ.get("V28_PM", "outputs/v28/pmstore"))
B_HOLDS = ("d1", "d2", "d3", "d5", "d10")
_S: dict = {}
_C: dict = {}


def shield28_grid(kind: str, picks: list[str]) -> list[dict]:
    """An intraday entry held to its own close has no night: no extended-session stop, no target."""
    out = []
    base = {"rally": "none", "scale": "all"}
    for entry in picks:
        for hold in B_HOLDS:
            night = not (kind == "intra" and hold == "d1")
            for stop in sh.STOPS:
                for ext in (sh.EXT if night else ("none",)):
                    for filt in v28.FILTERS28:
                        out.append({"entry": entry, "hold": hold, "stop": stop, "ext": ext, "target": "none",
                                    "filt": filt, **base})
                    if night:
                        for tg in v28.TARGETS[1:]:
                            out.append({"entry": entry, "hold": hold, "stop": stop, "ext": ext, "target": tg,
                                        "filt": "none", **base})
    return out


def registry() -> dict[str, tuple[str, list[dict]]]:
    if "reg" not in _S:
        reg: dict = {}
        for k, (kind, picks) in R26.entries_of().items():
            reg["B:" + k] = ("shield", shield28_grid(kind, picks))
        for k in v28.EVENT_FAMS:
            reg[k] = ("event", v28.event_grid(k))
        reg["C:PM_SHORT"] = ("pm", v28.PM_GRID)
        reg["C:AH_SHORT"] = ("ah", v28.AH_GRID)
        for k in v28.LONG_FAMS:
            reg[k] = ("long", v28.long_grid(k))
        reg["D:FACTOR_BOOK"] = ("factor", v28.FACTOR_GRID)
        reg["D:LEVETF_SHORT"] = ("lev", v28.LEV_GRID)
        _S["reg"] = reg
        R26._S["reg"] = {k[2:]: v for k, v in reg.items() if k.startswith("B:")}  # R26.evaluate reads its configs
    return _S["reg"]


def configs() -> list[tuple[str, int]]:
    return [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]


def load(base: Path) -> None:
    R26.load(base)
    D, E = R14._G["D"], R16._W["E"]
    extras = R14.PREP.load(INPUTS28 / "extras28.pkl")
    Y = R14._G.get("Y") or {}
    close = Y.get("close") if isinstance(Y, dict) else None
    btc = close["BTCUSDT"].dropna() if close is not None and "BTCUSDT" in close else None
    v28.install()
    v28.prepare(D, E, extras, btc)
    if (PM / "nights.parquet").exists():
        arrays = dict(np.load(PM / "nights.npz"))
        v28.PM_STORE = sh.Nights(pd.read_parquet(PM / "nights.parquet"), arrays)
        v28.PM_STORE.a["v"] = arrays["v"]  # the size cap reads the premarket dollar volume before the entry
    registry()


# ---------------------------------------------------------------- evaluation

_TARGET: dict = {"v": "none"}
_base_set = sh.set_params


def _set_params(p: dict | None) -> None:
    _base_set(None if p is None else {**p, "target": _TARGET["v"]})


sh.set_params = _set_params


def _scen_daily(D: dict, specs: list, table: dict, shield: dict | None) -> tuple[dict, list, np.ndarray]:
    out, paths, taken = {}, [], np.zeros(0, bool)
    sh.set_params(shield)
    try:
        for name, half, spread, fee, gross in R22.SCEN:
            v19.set_costs("r4", R22.SLIP, half)
            s, p_, t_ = v19.daily_book(D, specs, table, spread, fee, gross)
            out[name] = s
            if name == "mid":
                paths, taken = p_, t_
        v19.set_costs("r4", 0.0, R22.R4)
        out["gross"] = v19.daily_book(D, specs, table, 0.0, 1.0, True)[0]
    finally:
        sh.set_params(None)
        v19.set_costs("r4", R22.SLIP, R22.R4)
    return out, paths, taken


def _scen_intra(make, table: dict, dates: pd.DatetimeIndex) -> tuple[dict, list, np.ndarray]:
    out, paths, taken = {}, [], np.zeros(0, bool)
    try:
        for name, half, spread, fee, gross in R22.SCEN:
            v19.set_costs("r4", R22.SLIP, half)
            s, p_, t_ = v19.intra_book(make(), dates, table, spread, fee, gross)
            out[name] = s
            if name == "mid":
                paths, taken = p_, t_
        v19.set_costs("r4", 0.0, R22.R4)
        out["gross"] = v19.intra_book(make(), dates, table, 0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", R22.SLIP, R22.R4)
    return out, paths, taken


def _ext_trades(kind: str, D: dict, g: dict) -> pd.DataFrame:
    shield = {"hold": g["hold"], "stop": "own", "ext": "none", "rally": "none", "scale": "all"}
    sh.set_params(shield)
    try:
        return (v28.pm_trades if kind == "pm" else v28.ah_trades)(D, g)
    finally:
        sh.set_params(None)


def evaluate(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, table = R14._G["D"], R16._W["table"]
    dates = D["dates"]
    if kind == "shield":
        _TARGET["v"] = g["target"]
        try:
            return R26.evaluate(key[2:], ci, placebo_rng)
        finally:
            _TARGET["v"] = "none"
    if kind in ("event", "long"):
        ck = (key, *[g[k] for k in g if k not in ("hold", "stop", "ext")]) if kind == "event" else (key, *g.values())
        if ck not in _C:
            _C[ck] = v28.event_specs(D, key, g) if kind == "event" else v28.long_specs(D, key, g)
        specs = _C[ck]
        shield = ({"hold": g["hold"], "stop": g["stop"], "ext": g["ext"], "rally": "none", "scale": "all"}
                  if kind == "event" else None)
        if placebo_rng is not None:
            band = g.get("band")
            pl = v19.daily_placebo(D, specs, placebo_rng, None if band in (None, "all") else band)
            sh.set_params(shield)
            v19.set_costs("r4", R22.SLIP, R22.R4)
            try:
                return v19.daily_book(D, pl, table, 1.0)[0], None, None
            finally:
                sh.set_params(None)
        return _scen_daily(D, specs, table, shield)
    if kind in ("pm", "ah"):
        real = _ext_trades(kind, D, g)
        if placebo_rng is not None:
            sh.set_params({"hold": g["hold"], "stop": "own", "ext": "none", "rally": "none", "scale": "all"})
            v19.set_costs("r4", R22.SLIP, R22.R4)
            try:
                pt = (v28.pm_trades if kind == "pm" else v28.ah_trades)(D, g, placebo_rng, real)
            finally:
                sh.set_params(None)
            return v19.intra_book(pt, dates, table, 1.0)[0], None, None
        return _scen_intra(lambda: real, table, dates)
    if kind == "factor":
        if placebo_rng is not None:
            return v28.factor_book(D, g, table, 1.0, 1.0, False, placebo_rng)[0], None, None
        out = {}
        for name, _, spread, fee, gross in R22.SCEN:
            s, p_, t_ = v28.factor_book(D, g, table, spread, fee, gross)
            out[name] = s
            if name == "mid":
                paths, taken = p_, t_
        out["gross"] = v28.factor_book(D, g, table, 0.0, 0.0, True)[0]
        return out, paths, taken
    if placebo_rng is not None:
        return v28.lev_book(D, g, 1.0, 1.0, False, placebo_rng)[0], None, None
    out = {}
    for name, _, spread, fee, gross in R22.SCEN:
        s, p_, t_ = v28.lev_book(D, g, spread, fee, gross)
        out[name] = s
        if name == "mid":
            paths, taken = p_, t_
    out["gross"] = v28.lev_book(D, g, 0.0, 0.0, True)[0]
    return out, paths, taken


R22.registry = registry
R22.configs = configs
R22.evaluate = evaluate
R22.R19.load = load
R22.TITLE, R22.COMBO = "v28: the small-cap megarun", "COMBO28"


if __name__ == "__main__":
    sys.argv[0] = "run_v28"
    raise SystemExit(R22.main())
