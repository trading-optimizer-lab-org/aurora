"""v13 diagnostic, added after the run (not pre-registered; it does not change the verdict).

The survivorship-free universe made a walk-forward Sortino of 0.61 against 3.45 on the earlier survivors-only panel.
This separates the causes: the 144 configurations on subsets of the full panel (the earlier list's tickers, the
active tickers, everything), with the model's top-N re-ranked inside each subset; the trades of one fixed
configuration split by ticker group; and the earlier list's daily returns compared between the two panels.
Only aggregates are printed and saved.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import stock_catalog as sc
from aurora.research import v10
from aurora.research import v13

FIXED = "V13_MIX3_XQ3_20_M1_R1_C35_M8"  # the v11 robust pick's settings inside the v13 grid


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R13 = _script("run_v13")
LK, R10 = R13.LK, R13.R10


def _groups(cols: pd.Index) -> dict[str, np.ndarray]:
    api = LK.FETCH.Alpaca()
    r = requests.get(R13.ASSETS_URL, params={"asset_class": "us_equity"}, headers=api.headers, timeout=120)
    r.raise_for_status()
    status = {str(a["symbol"]).replace(".", "-"): a["status"] for a in r.json()}
    old = set(pd.read_csv(R13.SYMBOLS)["symbol"].astype(str))
    in_old = np.array([c in old for c in cols])
    inactive = np.array([status.get(c) == "inactive" for c in cols])
    return {"ALL": np.ones(len(cols), bool), "OLD_LIST": in_old, "ACTIVE": ~inactive,
            "OLD_LIST_PLUS_INACTIVE": in_old | inactive}


def _stats_block(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]]) -> dict:
    wf = v13.walk_forward(R, cash, nb)
    out = {"WF_ONE": v13.stats(wf["one"], cash), "WF_ENS5": v13.stats(wf["ens"], cash),
           FIXED: v13.stats(R[FIXED], cash)}
    s = [sc.metrics(R[c].loc["2018-01-01":v13.LAST], cash).get("sortino_monthly") for c in R.columns]
    out["median_config_sortino_2018_26"] = float(np.nanmedian(np.asarray(s, dtype=float)))
    return out


def _trade_split(G: dict, reg: dict, group_of: np.ndarray) -> list[dict]:
    g = dict(zip(v13.DIMS, ("MIX3", "XQ3_20", "M1", 0.01, 0.35, 8)))
    e, s, px, sd = G["sig"]["MIX3"]
    m = e & reg["M1"][:, None]

    def df(a: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(a, index=G["dates"], columns=G["cols"])

    trades: list = []
    sc.simulate(G["panel"], G["ind"], df(m), df(s), g["exit"], G["cash"], G["rank"]["RS63"], start=v13.START,
                entry_px=df(px), same_day_px=df(sd), risk=g["risk"], cap=g["cap"], max_gross=G["gross"][1.0],
                max_pos=g["max_pos"], trades=trades)
    t = pd.DataFrame(trades)
    t["group"] = group_of[t["symbol"].to_numpy()]
    t["year"] = pd.to_datetime(t["entry_date"]).dt.year
    t["w"] = t["return"] * t["fraction"]
    rows = []
    for (grp, period), sub in [((k, "2016-2026"), v) for k, v in t.groupby("group")] + \
            [((k, f"{y}"), v) for (k, y), v in t.groupby(["group", "year"])]:
        win, loss = sub.loc[sub["w"] > 0, "w"].sum(), -sub.loc[sub["w"] < 0, "w"].sum()
        rows.append({"group": grp, "period": period, "pieces": int(len(sub)), "symbols": int(sub["symbol"].nunique()),
                     "mean_return": float(sub["w"].sum() / sub["fraction"].sum()),
                     "pf": float(win / loss) if loss > 0 else np.nan,
                     "worst": float(sub["return"].min()), "share_below_-20%": float((sub["return"] < -0.2).mean())})
    return rows


def _price_check(new_close: pd.DataFrame, inputs: Path) -> dict:
    old = R10._load(inputs / "qb.pkl")
    oc = pd.DataFrame(old["panel"]["close"], index=old["dates"], columns=old["cols"])
    common = [c for c in oc.columns if c in new_close.columns]
    a = oc[common].loc["2016-01-01":v13.LAST].pct_change(fill_method=None)
    b = new_close[common].reindex(a.index).pct_change(fill_method=None)
    both = a.notna() & b.notna()
    bad = ((a - b).abs() > 0.02) & both
    share = bad.sum() / both.sum().replace(0, np.nan)
    missing = (a.notna() & b.isna()).sum() / a.notna().sum().replace(0, np.nan)
    return {"survivor_columns": int(oc.shape[1]), "found_in_full_panel": len(common),
            "median_share_days_return_diff_gt_2pct": float(share.median()),
            "tickers_with_over_1pct_such_days": int((share > 0.01).sum()),
            "median_share_days_missing_in_full": float(missing.median()),
            "tickers_missing_over_5pct_days": int((missing > 0.05).sum())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    ap.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
    ap.add_argument("--cache", type=Path, default=Path("outputs/alpaca_locked"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v13"))
    args = ap.parse_args()
    R13._open()
    model = R13.train_model(args.panel_dir, args.nasdaq)
    panel, nasdaq, ind, ctx, alp_daily = R13._new_universe(args)
    price = _price_check(panel["close"], args.inputs)
    print(json.dumps(price), flush=True)
    groups = _groups(panel["close"].columns)
    print(json.dumps({k: int(v.sum()) for k, v in groups.items()}), flush=True)
    cash_index = LK.MAB.tbill_index({}).loc[:v13.LAST]
    feats = qs.features(panel, ind, nasdaq)
    setup5, _ = q.breakout_setup(panel, ind, ctx, *q.BO_SELECTIONS["SCAN5"])
    tiebreak = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).shift(1)
    score = qs.model_score(feats, model)
    del feats
    kept = {}
    for name, mask in groups.items():
        sub = setup5.fillna(False).astype(bool) & np.broadcast_to(mask, setup5.shape)
        kept[name] = {n: qs.top_n(score, sub, tiebreak, n) for n in (1, 3)}
    del score, setup5, tiebreak
    prep = qi.prepare(panel, ind, ctx, cash_index, LK.FETCH.minute_loader(args.cache), alp_daily)
    full_cols = panel["close"].columns
    del panel, ind, ctx, alp_daily
    R13._mem("intraday table")
    dates, cols = prep["panel"]["close"].index, prep["panel"]["close"].columns
    shape = (len(dates), len(cols))
    base = {"panel": {k: v.astype(np.float32) for k, v in prep["panel"].items()},
            "ind": {k: prep["ind"][k].astype(np.float32) for k in R10.IND_KEYS}, "cash": prep["cash"], "dates": dates,
            "cols": cols, "rank": {"RS63": prep["rank"]}, "gross": {1.0: pd.Series(1.0, index=dates)}}
    reg = R13._regimes(prep["m1"], nasdaq, dates)
    cfgs = v13.grid()
    nb = v13.neighbours(cfgs)
    pos = full_cols.get_indexer(cols)
    _, ie, _ = qs.intraday_signals(prep, None)
    report: dict = {"price_check": price, "group_sizes": {k: int(v.sum()) for k, v in groups.items()},
                    "candidate_columns": len(cols), "by_subset": {}}
    for name, mask in groups.items():
        sigs = {"EP_N1": ie, "MIX1": qs.intraday_signals(prep, kept[name][1])[2],
                "MIX3": qs.intraday_signals(prep, kept[name][3])[2]}
        keep_col = mask[pos]
        sig = {}
        for k, v in sigs.items():
            e, s, px, sd = v10.dense(v10.sparse(v), shape)
            sig[k] = (e & keep_col[None, :], s, px, sd)
        G = {**base, "sig": sig}
        R = pd.DataFrame({v13.cname(g): R13.sim(g, G, reg) for g in cfgs})
        report["by_subset"][name] = _stats_block(R, G["cash"], nb)
        print(name, json.dumps({k: (v.get("wf_sortino") if isinstance(v, dict) else v)
                                for k, v in report["by_subset"][name].items()}), flush=True)
        if name == "ALL":
            G_all = G
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "diag.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    label = np.where(groups["OLD_LIST"], "OLD_LIST", np.where(groups["ACTIVE"], "NEW_ACTIVE", "INACTIVE"))[pos]
    report["trades_fixed_all"] = _trade_split(G_all, reg, label)
    print(pd.DataFrame(report["trades_fixed_all"]).to_string(), flush=True)
    (args.out / "diag.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
