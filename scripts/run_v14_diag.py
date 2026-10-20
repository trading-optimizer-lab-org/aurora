"""v14 diagnostic of the short families, added after the run (not pre-registered; it does not change the verdict).

B8_GAPFADE made a walk-forward Sortino of 4.85 at the middle costs and -1.12 at the high ones. This shows where its
edge sits (raw price, shares outstanding, year) and how it reacts to each cost separately: spreads, the locate fee,
the borrow rate and the "no short below $2 or 10M shares" rule. The walk-forward picks are those of the run.
Only aggregates are printed and saved.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R14 = _script("run_v14")


def book(t: pd.DataFrame, dates: pd.DatetimeIndex, spread: float, locate_lt10: float, locate_ge10: float,
         rule: bool) -> tuple[pd.Series, pd.DataFrame]:
    """The intraday book of v14 with each cost set by hand (spread multiple of the middle tiers)."""
    if rule:
        t = t[(t["side"] > 0) | core.shortable_high(t["price"], t["so"])]
    t = t.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
    t = t.groupby("date", sort=False).head(5).copy()
    dist = (t["entry"] - t["stop"]).abs() / t["entry"]
    w = np.minimum(np.minimum(0.20, 0.005 / dist.clip(lower=1e-4)), 0.02 * t["liq"].fillna(0.0) / core.ACCOUNT)
    t["w"] = w / np.maximum(1.0, w.groupby(t["date"]).transform("sum"))
    p = np.maximum(t["price"].to_numpy(float), 0.01)
    cost = 2 * (core.half_spread(p, "mid") * spread + core.COMMISSION / p)
    cost += np.where(t["side"] < 0, np.where(p < 10, locate_lt10, locate_ge10), 0.0)
    t["net"] = t["side"] * (t["exit"] / t["entry"] - 1) - cost
    daily = (t["w"] * t["net"]).groupby(t["date"]).sum()
    return daily.reindex(dates).fillna(0.0), t


def wf_stream(trades: dict[int, pd.DataFrame], picks: dict, dates: pd.DatetimeIndex, **kw) -> pd.Series:
    parts = []
    for y, name in picks.items():
        ci = int(name.split("|")[1])
        r, _ = book(trades[ci], dates, **kw)
        parts.append(r.loc[f"{y}-01-01":f"{y}-12-31"])
    return pd.concat(parts)


def _s(r: pd.Series, cash: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    years = (r.index[-1] - r.index[0]).days / 365.25
    return {"sortino": round(core.sortino(r, cash), 2), "cagr": round(float(eq.iloc[-1] ** (1 / years) - 1), 3),
            "dd": round(float((eq / eq.cummax() - 1).min()), 3)}


def breakdown(t: pd.DataFrame) -> list[dict]:
    t = t.copy()
    t["price_b"] = pd.cut(t["price"], [0, 2, 5, 10, 20, 1e9], labels=["<2", "2-5", "5-10", "10-20", ">20"])
    t["so_b"] = pd.cut(t["so"].fillna(-1), [-2, 0, 10e6, 50e6, 1e15], labels=["unknown", "<10M", "10-50M", ">50M"])
    t["year"] = pd.to_datetime(t["date"]).dt.year
    rows = []
    for by in ("price_b", "so_b", "year"):
        for v, g in t.groupby(by, observed=True):
            win, loss = g.loc[g["net"] > 0, "net"].sum(), -g.loc[g["net"] < 0, "net"].sum()
            rows.append({"by": by, "value": str(v), "trades": int(len(g)), "mean_net": round(float(g["net"].mean()), 4),
                         "pf": round(float(win / loss), 2) if loss > 0 else None,
                         "gross_mean": round(float((g["side"] * (g["exit"] / g["entry"] - 1)).mean()), 4),
                         "weight_share": round(float(g["w"].sum() / t["w"].sum()), 3)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("outputs/v14/diag"))
    args = ap.parse_args()
    R14.load_inputs(args.inputs)
    D, store = R14._G["D"], R14._G["store"]
    dates, cash = D["dates"], D["cash"]
    fam = json.loads(args.summary.read_text(encoding="utf-8"))["families"]["B8"]
    picks = {int(y): v for y, v in fam["picks"].items()}
    cfgs = core.grid(vi.A_DIMS["B8_GAPFADE"])
    trades = {int(n.split("|")[1]): vi.family_trades(store, "B8_GAPFADE", cfgs[int(n.split("|")[1])])
              for n in set(picks.values())}
    out: dict = {"picks": picks, "configs": {i: cfgs[i] for i in trades}}
    mid = dict(spread=1.0, locate_lt10=0.005, locate_ge10=0.0, rule=False)
    variants = {"middle (as run, no borrow nights)": mid, "spreads x0.5": {**mid, "spread": 0.5},
                "spreads x1.5": {**mid, "spread": 1.5}, "spreads x2": {**mid, "spread": 2.0},
                "locate 0": {**mid, "locate_lt10": 0.0}, "locate 1%": {**mid, "locate_lt10": 0.01},
                "locate 2%": {**mid, "locate_lt10": 0.02}, "locate 3%": {**mid, "locate_lt10": 0.03},
                "locate 1% on all": {**mid, "locate_lt10": 0.01, "locate_ge10": 0.01},
                "only >= $2 and >= 10M shares": {**mid, "rule": True},
                "only >= $2 and >= 10M shares, locate 1.5%": {**mid, "rule": True, "locate_lt10": 0.015,
                                                              "locate_ge10": 0.005},
                "high (spreads x2, locate 1.5%, rule)": {"spread": 2.0, "locate_lt10": 0.015, "locate_ge10": 0.005,
                                                         "rule": True}}
    out["cost_sensitivity"] = {}
    for name, kw in variants.items():
        r = wf_stream(trades, picks, dates, **kw).loc["2018-01-01":]
        out["cost_sensitivity"][name] = _s(r, cash)
        print(name, out["cost_sensitivity"][name], flush=True)
    last = int(picks[max(picks)].split("|")[1])
    _, used = book(trades[last], dates, **mid)
    out["breakdown_last_pick"] = breakdown(used[used["date"] >= pd.Timestamp("2018-01-01")])
    print(pd.DataFrame(out["breakdown_last_pick"]).to_string(), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "diag.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
