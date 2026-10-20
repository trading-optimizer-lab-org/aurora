"""v17 cost study: the real quoted spreads of the S1 and B8R1 trades (design period, the walk-forward's picks).
Pre-registered in docs/research/V17_PREREGISTRATION.md, section 1.

  trades   the trades of every configuration the walk-forward picked, with their entry and exit minutes
  quotes   Alpaca SIP quotes in the entry minute and the exit minute of each trade (cached)
  analyze  measured half-spreads against the price-tier table, and the walk-forward with each trade's own cost
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v15_ah as v15
from aurora.research import v16_small as v16


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R16 = _script("run_v16")
R14 = R16.R14
D14 = _script("run_v14_data")
QUOTES = "https://data.alpaca.markets/v2/stocks/quotes"


def _picks() -> dict[str, dict[int, str]]:
    s16 = json.loads(Path("docs/research/data/v16_summary.json").read_text(encoding="utf-8"))["families"]
    s15 = json.loads(Path("docs/research/data/v15_summary.json").read_text(encoding="utf-8"))["families"]
    return {"S1": {int(y): v for y, v in s16["S1"]["picks"].items()},
            "B8R1": {int(y): v for y, v in s15["B8R1"]["picks"].items()}}


def _trades(store: vi.Store, key: str, g: dict) -> pd.DataFrame:
    family = "S1_B8NEWS" if key.startswith("S1") else None
    rows = []
    cands = v16.candidates(store, family, g) if family else vi.candidates(store, "B8_GAPFADE", g)
    for k in cands:
        cd = store.cands.loc[k]
        b = store.bars(k)
        if len(b[0]) < 10:
            continue
        line = vi.vwap(b[4], b[5], b[6])
        if g.get("entry", "orl5") == "vwaploss":
            j, entry, stop = vi.entry_vwap_loss(b, line)
        else:
            j, entry, _ = vi.entry_orb(b, 15 if g.get("entry") == "orl15" else 5, -1)
            stop = float(b[2][:j].max()) if j > 0 else np.nan
        if j <= 0 or not stop > entry:
            continue
        j, entry = vi._ssr_fill(j, b, float(cd["pc"]), entry)
        if j < 0 or stop <= entry:
            continue
        ex, jx = vi.run_exit(-1, j, entry, stop, g.get("exit", "close"), b, line)
        r = vi._row(cd, -1, j, entry, stop, ex, b, float(cd["gap"]))
        r["exit_minute"] = int(b[0][jx])
        rows.append(r)
    return pd.DataFrame(rows)


def cmd_trades(args) -> int:
    R16.load(args.v14_inputs, args.v15_inputs, args.v16_inputs)
    store = R14._G["store"]
    reg = R16.combined()
    out = []
    for fam, picks in _picks().items():
        for name in sorted(set(picks.values())):
            key, ci = name.split("|")
            t = _trades(store, key, dict(reg[key][1][int(ci)]))
            t["config"] = name
            out.append(t)
            print(f"{name}: {len(t)} trades", flush=True)
    t = pd.concat(out, ignore_index=True)
    args.out.mkdir(parents=True, exist_ok=True)
    t.to_parquet(args.out / "trades.parquet", index=False)
    return 0


def _window(sym: str, day: pd.Timestamp, minute: int, headers: dict, limiter) -> tuple[float, int]:
    start = D14._ny(day, 9, 30) + pd.Timedelta(minutes=int(minute))
    params = {"symbols": sym, "start": start.isoformat(), "end": (start + pd.Timedelta(minutes=1)).isoformat(),
              "feed": "sip", "limit": 10000}
    body = D14.V9._get(QUOTES, params, headers, limiter) or {}
    q = (body.get("quotes") or {}).get(sym, [])
    rel = [(x["ap"] - x["bp"]) / ((x["ap"] + x["bp"]) / 2) for x in q
           if x.get("ap", 0) > 0 and x.get("bp", 0) > 0 and x["ap"] > x["bp"]]
    return (float(np.median(rel)) if rel else np.nan), len(rel)


def cmd_quotes(args) -> int:
    headers = D14._alpaca_headers()
    t = pd.read_parquet(args.out / "trades.parquet")
    legs = pd.concat([t[["date", "symbol", "minute"]], t[["date", "symbol", "exit_minute"]].rename(
        columns={"exit_minute": "minute"})]).drop_duplicates().reset_index(drop=True)
    path = args.out / "spreads.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["date", "symbol", "minute", "spread", "n"])
    done = set(zip(have["date"], have["symbol"], have["minute"]))
    todo = [r for r in legs.itertuples(index=False) if (r.date, r.symbol, r.minute) not in done]
    print(f"quote windows: {len(todo)} of {len(legs)} to fetch", flush=True)
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(_window, r.symbol, pd.Timestamp(r.date), r.minute, headers, limiter): r for r in todo}
        for n, f in enumerate(as_completed(futs)):
            r = futs[f]
            s, k = f.result()
            rows.append({"date": r.date, "symbol": r.symbol, "minute": r.minute, "spread": s, "n": k})
            if n % 500 == 0:
                print(f"quotes: {n}/{len(todo)}, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    out = pd.concat([have, pd.DataFrame(rows)], ignore_index=True)
    out.to_parquet(path, index=False)
    print(json.dumps({"windows": len(out), "with_quotes": int(out["spread"].notna().sum())}), flush=True)
    return 0


def _book(t: pd.DataFrame, dates: pd.DatetimeIndex, table: dict, cost: np.ndarray) -> pd.Series:
    t = t.assign(cost=cost).sort_values(["date", "minute", "prio"], ascending=[True, True, False])
    t = t.groupby("date", sort=False).head(5).copy()
    dist = (t["entry"] - t["stop"]).abs() / t["entry"]
    w = np.minimum(np.minimum(0.20, 0.005 / dist.clip(lower=1e-4)), 0.02 * t["liq"].fillna(0.0) / core.ACCOUNT)
    t["w"] = w / np.maximum(1.0, w.groupby(t["date"]).transform("sum"))
    p_av, _ = v15.lookup(table, t["price"].to_numpy(), t["so"].to_numpy())
    net = -(t["exit"] / t["entry"] - 1) - t["cost"]
    daily = (t["w"] * p_av * net).groupby(t["date"]).sum()
    return daily.reindex(dates).fillna(0.0)


def cmd_analyze(args) -> int:
    D = R14.PREP.load(args.v14_inputs / "daily.pkl")
    dates, cash = D["dates"], D["cash"]
    table = R14.PREP.load(args.v15_inputs / "avail.pkl")["table"]
    t = pd.read_parquet(args.out / "trades.parquet")
    sp = pd.read_parquet(args.out / "spreads.parquet").drop_duplicates(["date", "symbol", "minute"])
    key = ["date", "symbol", "minute"]
    t = t.merge(sp.rename(columns={"spread": "s_in"})[key + ["s_in"]], on=key, how="left")
    t = t.merge(sp.rename(columns={"minute": "exit_minute", "spread": "s_out"})[["date", "symbol", "exit_minute",
                                                                                 "s_out"]],
                on=["date", "symbol", "exit_minute"], how="left")
    price = np.maximum(t["price"].to_numpy(float), 0.01)
    table_hs = core.half_spread(price, "mid")
    hs_in = np.where(np.isfinite(t["s_in"]), t["s_in"] / 2, table_hs)
    hs_out = np.where(np.isfinite(t["s_out"]), t["s_out"] / 2, table_hs)
    measured = hs_in + hs_out + 2 * core.COMMISSION / price
    tabled = 2 * table_hs + 2 * core.COMMISSION / price
    t["band"] = v15.price_band(price)
    lines = ["# v17 cost study: quoted spreads of the gap-fade trades (design period)", "",
             f"{len(t)} trades; entry quotes found for {int(np.isfinite(t['s_in']).sum())}, exit quotes for "
             f"{int(np.isfinite(t['s_out']).sum())}.", "",
             "| raw price | trades | table half-spread | measured at entry (median) | measured at exit (median) |",
             "|---|---|---|---|---|"]
    for b, g in t.groupby("band"):
        th = core.half_spread(np.maximum(g["price"].to_numpy(float), 0.01), "mid")
        lines.append(f"| {b} | {len(g)} | {np.median(th):.2%} | {np.nanmedian(g['s_in'] / 2):.2%} | "
                     f"{np.nanmedian(g['s_out'] / 2):.2%} |")
    lines += ["", "| stream | walk-forward Sortino, table costs | measured costs | CAGR measured | max DD measured |",
              "|---|---|---|---|---|"]
    out = {}
    for fam, picks in _picks().items():
        parts_t, parts_m = [], []
        for y, name in picks.items():
            sel = t["config"] == name
            a = _book(t[sel], dates, table, tabled[sel.to_numpy()])
            b = _book(t[sel], dates, table, measured[sel.to_numpy()])
            parts_t.append(a.loc[f"{y}-01-01":f"{y}-12-31"])
            parts_m.append(b.loc[f"{y}-01-01":f"{y}-12-31"])
        rt, rm = pd.concat(parts_t), pd.concat(parts_m)
        st_t = R14._stats(rt, cash, "2018-01-01", str(core.DESIGN_END.date()))
        st_m = R14._stats(rm, cash, "2018-01-01", str(core.DESIGN_END.date()))
        out[fam] = {"table": st_t, "measured": st_m}
        lines.append(f"| {fam} | {st_t['sortino']:.2f} | {st_m['sortino']:.2f} | {st_m['cagr']:.1%} | {st_m['dd']:.1%} |")
    (args.out / "COSTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out / "costs.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("trades", "quotes", "analyze"))
    for a in ("v14", "v15", "v16"):
        ap.add_argument(f"--{a}-inputs", type=Path, default=Path(f"outputs/{a}/inputs"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v17/quotes"))
    args = ap.parse_args()
    return {"trades": cmd_trades, "quotes": cmd_quotes, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
