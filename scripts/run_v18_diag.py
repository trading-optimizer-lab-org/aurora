"""v18 diagnostic of the multi-day short families and the overnight short (after the run; it changes nothing).

For the configurations the walk-forward chose for W1, W2 and H2: every trade with its symbol, dates, raw prices,
the rise that triggered it, its return, weight, IBKR availability cell and fee; the biggest winners and losers;
yearly counts; and the data checks a fake move would fail (a gap in the series, a raw price below $1 at entry, a
split factor change inside the holding period). Only these aggregates and the trade list (no price series) are
saved.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_swing as vs
from aurora.research import v15_ah as v15
from aurora.research import v18_rules as v18


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R18 = _script("run_v18")
R14 = R18.R14


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("outputs/v18/diag"))
    args = ap.parse_args()
    base = Path("outputs/v18")
    R18.load(base / "v14", base / "v15", base / "v16", base / "v17", base / "v18")
    D, E, table = R14._G["D"], R18.R16._W["E"], R18.R16._W["table"]
    picks = json.loads(args.summary.read_text(encoding="utf-8"))["families"]
    reg = R18.registry()
    out: dict = {}
    lines = ["# v18 diagnostic of W1, W2 and H2", ""]
    for fam, key in (("W1", "W1_FADEGRID"), ("W2", "W2_SUPERNOVA"), ("H2", "H2_FADEOVERNIGHT")):
        names = sorted(set(picks[fam]["picks"].values()))
        rows = []
        for name in names:
            g = reg[key][1][int(name.split("|")[1])]
            sp, weight, _ = v18.daily_specs(D, E, key, g)
            look = (1.0, lambda px, so: v15.lookup(table, px, so))
            for s in sp:
                p = vs.path(D, s, "mid", w_max=weight, r1=look)
                if p is None:
                    continue
                first, r, prio, w = p
                t, j = s.t, s.j
                last = min(first + len(r) - 1, len(D["dates"]) - 1)
                raw_entry = float(D["P"][t - 1, j]) if s.kind != "close" else float(D["P"][t, j])
                f_change = bool(np.nanmax(np.abs(np.diff(D["F"][max(t - 1, 0):last + 1, j]))) > 1e-6) \
                    if last > t else False
                pav, fee = v15.lookup(table, np.array([raw_entry]), np.array([D["SO"][t, j]]))
                rows.append({"config": name, "symbol": D["cols"][j], "entry_date": str(D["dates"][t].date()),
                             "exit_date": str(D["dates"][last].date()), "side": s.side, "raw_price": raw_entry,
                             "trigger": prio, "return": float(r.sum()), "weight": float(w), "p_avail": float(pav[0]),
                             "fee": float(fee[0]), "days": len(r), "split_inside": f_change,
                             "gap_inside": bool(D["new"][t:last + 1, j].any())})
        t = pd.DataFrame(rows)
        if t.empty:
            continue
        t["pnl"] = t["return"] * t["weight"]
        t["year"] = t["entry_date"].str[:4]
        top = t.sort_values("pnl", ascending=False)
        out[fam] = {"trades": len(t), "mean_return": float(t["return"].mean()),
                    "median_return": float(t["return"].median()), "win_rate": float((t["return"] > 0).mean()),
                    "share_return_over_50pct": float((t["return"] > 0.5).mean()),
                    "share_split_inside": float(t["split_inside"].mean()),
                    "share_gap_inside": float(t["gap_inside"].mean()),
                    "pnl_top10_share": float(top["pnl"].head(10).sum() / t["pnl"].sum()) if t["pnl"].sum() else None,
                    "by_year": t.groupby("year")["return"].agg(["count", "mean"]).round(4).to_dict()}
        lines += [f"## {fam} ({', '.join(names)})", "", json.dumps(out[fam], indent=1), "",
                  "Top 15 by P&L:", "", top.head(15).to_string(index=False), "", "Bottom 10 by P&L:", "",
                  top.tail(10).to_string(index=False), ""]
        args.out.mkdir(parents=True, exist_ok=True)
        t.to_csv(args.out / f"{fam}_trades.csv", index=False)
    (args.out / "DIAG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
