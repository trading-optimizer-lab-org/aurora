"""v19 diagnostic (after the run; it changes nothing).

1. The price scale of the minute bars against the daily bars: for every candidate day, the first minute bar's open
   against the daily open and the last minute bar's close against the daily close, both on that day's raw scale. The
   overnight and multi-day intraday exits join the two, so a scale mismatch would make their returns false.
2. The trades of the walk-forward picks of XS1, XS2, XS4, DS1 and ON1 in the years they were picked: the entry day's
   return and, for intraday entries, what the nights after it added; the biggest winners and losers.
Only aggregates and trade lists (no price series) are saved.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v19_grid as v19


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R19 = _script("run_v19")
R14, R16 = R19.R14, R19.R16


def scale_check(D: dict, store) -> tuple[dict, pd.DataFrame]:
    c = store.cands
    off, n = c["off"].to_numpy(int), c["n"].to_numpy(int)
    t, j = c["t"].to_numpy(int), c["j"].to_numpy(int)
    f = D["F"][t, j].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r_open = store.arrays["o"][off] / (D["O"][t, j] / f) - 1
        r_close = store.arrays["c"][off + n - 1] / (D["C"][t, j] / f) - 1
    out = {}
    for name, r in (("open", r_open), ("close", r_close)):
        a = np.abs(r[np.isfinite(r)])
        out[name] = {"n": int(len(a)), "median_abs": float(np.median(a)), "p99_abs": float(np.percentile(a, 99)),
                     **{f"share_over_{int(x * 100)}pct": float((a > x).mean()) for x in (0.02, 0.10, 0.50)}}
    worst = pd.DataFrame({"date": c["date"].astype(str), "symbol": c["symbol"], "r_open": r_open, "r_close": r_close})
    worst = worst.reindex(worst["r_close"].abs().sort_values(ascending=False).index).head(20)
    return out, worst


def pick_trades(fam: str, picks: dict) -> pd.DataFrame:
    reg = R19.registry()
    D, store = R14._G["D"], R14._G["store"]
    table, E = R16._W["table"], R16._W["E"]
    rows = []
    for name in sorted(set(picks.values())):
        key, ci = name.split("|")[0], int(name.split("|")[1])
        g = reg[key][1][ci]
        years = {int(y) for y, n in picks.items() if n == name}
        if reg[key][0] == "intra":
            tr = v19.intraday_trades(store, D, key, g)
            _, paths, taken = v19.intra_book(tr, D["dates"], table, 1.0)
            ordered = tr.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
            ordered = ordered.groupby("date", sort=False).head(5).reset_index(drop=True)
            for i, (p, tk) in enumerate(zip(paths, taken)):
                r = ordered.iloc[i]
                if tk and pd.Timestamp(r["date"]).year in years:
                    rows.append({"config": name, "symbol": r["symbol"], "date": str(pd.Timestamp(r["date"]).date()),
                                 "minute": int(r["minute"]), "price": float(r["price"]), "day0": float(p[1][0]),
                                 "nights": float(np.sum(p[1][1:])), "total": float(np.sum(p[1])), "weight": p[3]})
        else:
            specs = v19.daily_specs(D, E, key, g)
            for s in specs:
                p = v19.path19(D, s, table, 1.0)
                if p is None or D["dates"][p[0]].year not in years:
                    continue
                rows.append({"config": name, "symbol": D["cols"][s.j], "date": str(D["dates"][s.t].date()),
                             "minute": -1, "price": float(D["P"][s.t, s.j]), "day0": float(p[1][0]),
                             "nights": float(np.sum(p[1][1:])), "total": float(np.sum(p[1])), "weight": p[3]})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v19/diag"))
    args = ap.parse_args()
    R19.load(args.inputs)
    D, store = R14._G["D"], R14._G["store"]
    args.out.mkdir(parents=True, exist_ok=True)
    sc, worst = scale_check(D, store)
    lines = ["# v19 diagnostic", "", "## 1. Minute bars against daily bars (same day, raw scale)", "",
             json.dumps(sc, indent=1), "", "Largest close mismatches:", "", worst.to_string(index=False), ""]
    out = {"scale": sc}
    fams = json.loads(args.summary.read_text(encoding="utf-8"))["families"]
    for fam in ("XS1", "XS2", "XS4", "DS1", "ON1"):
        t = pick_trades(fam, fams[fam]["picks"])
        if t.empty:
            continue
        t["pnl"] = t["total"] * t["weight"]
        t["year"] = t["date"].str[:4]
        top = t.sort_values("pnl", ascending=False)
        out[fam] = {"trades": len(t), "mean_total": float(t["total"].mean()), "median_total": float(t["total"].median()),
                    "mean_day0": float(t["day0"].mean()), "mean_nights": float(t["nights"].mean()),
                    "win_rate": float((t["total"] > 0).mean()),
                    "pnl_share_of_nights": float((t["nights"] * t["weight"]).sum() / t["pnl"].sum())
                    if t["pnl"].sum() else None,
                    "pnl_top10_share": float(top["pnl"].head(10).sum() / t["pnl"].sum()) if t["pnl"].sum() else None,
                    "by_year": t.groupby("year")["total"].agg(["count", "mean"]).round(4).to_dict()}
        lines += [f"## {fam}", "", json.dumps(out[fam], indent=1), "", "Top 12 by P&L:", "",
                  top.head(12).to_string(index=False), "", "Bottom 8 by P&L:", "", top.tail(8).to_string(index=False), ""]
        t.to_csv(args.out / f"{fam}_trades.csv", index=False)
    (args.out / "diag.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (args.out / "DIAG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
