"""v19q: every trade of the v19r walk-forward costed with its own quoted spreads (amendment of
docs/research/V19_PREREGISTRATION.md).

  trades   the trades the middle-cost (R3) book takes for the picks of every COMBO19 member family, kept when their
           holding overlaps a year the configuration was picked; each with its entry and exit leg (date and session
           minute: 0 = the open, 389 = the last minute; an exit inside a later day's daily bar uses that day's last
           minute), its gross path (slippage included) and weight; plus each pick's R3 return series
  quotes   Alpaca SIP quotes in each leg's minute (cached; the median ask-bid spread over the mid in that minute)
  analyze  each trade's cost rebuilt from its two measured half-spreads (the R3 tier value, 1.5x at the open, where no
           quote was found) plus R3's commissions, sale fees and borrow; the families' walk-forward streams and COMBO19
           rebuilt with v19r's members and weights; the same with the R3 tier spreads, which must reproduce v19r
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

from aurora.research import v15_ah as v15
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
SUMMARY = Path("docs/research/data/v19r_summary.json")
CLOSE = 389


def _summary() -> tuple[dict, dict]:
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    members = {int(y): m for y, m in s["members"].items()}
    fams = {f: {int(y): n for y, n in v["picks"].items()} for f, v in s["families"].items()
            if any(f in m for m in members.values())}
    return fams, members


def _overlaps(i0: int, n: int, dates: pd.DatetimeIndex, years: set) -> bool:
    return bool(set(dates[i0:i0 + n].year) & years)


def cmd_trades(args) -> int:
    R19.load(args.inputs)
    v19.set_costs(*R19.COST_MODELS["r3"])
    D, store = R14._G["D"], R14._G["store"]
    table, E = R16._W["table"], R16._W["E"]
    dates, reg = D["dates"], R19.registry()
    fams, _ = _summary()
    rows, series = [], {}
    for fam, picks in fams.items():
        for name in sorted(set(picks.values())):
            key, ci = name.split("|")[0], int(name.split("|")[1])
            g = reg[key][1][ci]
            years = {y for y, n in picks.items() if n == name}
            if reg[key][0] == "intra":
                tr = v19.intraday_trades(store, D, key, g)
                series[name] = v19.intra_book(tr, dates, table, 1.0)[0]
                _, paths, taken = v19.intra_book(tr, dates, table, 1.0, gross=True)
                ordered = tr.sort_values(["date", "minute", "prio"], ascending=[True, True, False])
                ordered = ordered.groupby("date", sort=False).head(5).reset_index(drop=True)
                legs = []
                for i, x in ordered.iterrows():
                    xmin = int(x["xmin"]) if x["xmin"] >= 0 else (0 if x["rule"] == "next_open" else CLOSE)
                    legs.append((x["symbol"], int(x["minute"]), xmin, float(x["price"]), float(x["so"]),
                                 int(x["side"]), int(x["nights"]), int(x["opens"])))
            else:
                specs = v19.daily_specs(D, E, key, g)
                series[name] = v19.daily_book(D, specs, table, 1.0)[0]
                pairs = [(s, p) for s in specs if (p := v19.path19(D, s, table, 1.0, gross=True)) is not None]
                paths = [p for _, p in pairs]
                _, taken = v19.book_paths(paths, dates)
                legs = []
                for s, p in pairs:
                    raw = D["P"][s.t, s.j] if s.kind == "close" else D["P"][s.t - 1, s.j] * (D["O"][s.t, s.j] /
                                                                                            D["C"][s.t - 1, s.j])
                    legs.append((D["cols"][s.j], 0 if s.kind == "open" else CLOSE, 0 if s.rule == "open1" else CLOSE,
                                 float(raw), float(D["SO"][s.t, s.j]), s.side,
                                 max(len(p[1]) - (0 if s.kind == "close" else 1), 0),
                                 int(s.kind == "open") + int(s.rule == "open1")))
            for (i0, r, pr, w), tk, (sym, emin, xmin, price, so, side, nights, opens) in zip(paths, taken, legs):
                if not tk or not _overlaps(i0, len(r), dates, years):
                    continue
                x_i = min(i0 + len(r) - 1, len(dates) - 1)
                e_i = i0 - 1 if reg[key][0] == "daily" and emin == CLOSE else i0  # a close entry's path starts a day later
                rows.append({"family": fam, "config": name, "symbol": sym, "i0": i0,
                             "entry_date": str(dates[e_i].date()), "entry_min": emin,
                             "exit_date": str(dates[x_i].date()), "exit_min": xmin, "price": price, "so": so,
                             "side": side, "nights": nights, "opens": opens, "prio": pr, "w": w,
                             "rets": [float(v) for v in r]})
            print(f"{fam} {name}: {sum(1 for x in rows if x['config'] == name)} trades", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(args.out / "trades.parquet", index=False)
    pd.DataFrame(series).astype(np.float32).to_parquet(args.out / "series.parquet")
    print(json.dumps({"trades": len(rows)}), flush=True)
    return 0


def cmd_quotes(args) -> int:
    Q17 = _script("run_v17_quotes")
    D14 = Q17.D14
    headers = D14._alpaca_headers()
    t = pd.read_parquet(args.out / "trades.parquet")
    legs = pd.concat([t[["entry_date", "symbol", "entry_min"]].set_axis(["date", "symbol", "minute"], axis=1),
                      t[["exit_date", "symbol", "exit_min"]].set_axis(["date", "symbol", "minute"], axis=1)])
    legs = legs.drop_duplicates().reset_index(drop=True)
    path = args.out / "spreads.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["date", "symbol", "minute", "spread", "n"])
    done = set(zip(have["date"], have["symbol"], have["minute"]))
    todo = [r for r in legs.itertuples(index=False) if (r.date, r.symbol, r.minute) not in done]
    print(f"quote windows: {len(todo)} of {len(legs)} to fetch", flush=True)
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(Q17._window, r.symbol, pd.Timestamp(r.date), int(r.minute), headers, limiter): r
                for r in todo}
        for n, f in enumerate(as_completed(futs)):
            r = futs[f]
            s, k = f.result()
            rows.append({"date": r.date, "symbol": r.symbol, "minute": int(r.minute), "spread": s, "n": k})
            if n % 1000 == 0:
                print(f"quotes: {n}/{len(todo)}, {time.time() - t0:.0f}s", flush=True)
    out = pd.concat([have, pd.DataFrame(rows)], ignore_index=True)
    out.to_parquet(path, index=False)
    print(json.dumps({"windows": len(out), "with_quotes": int(out["spread"].notna().sum())}), flush=True)
    return 0


def _tier(price: np.ndarray, at_open: np.ndarray) -> np.ndarray:
    """R3's tier half-spread of a leg (1.5x at the open)."""
    px = np.maximum(price, 0.01)
    hs = np.select([px < a for a, _ in v19.R3_HALF[:-1]], [v for _, v in v19.R3_HALF[:-1]], v19.R3_HALF[-1][1])
    return hs * np.where(at_open, v19.R3_OPEN, 1.0)


def _streams(t: pd.DataFrame, cost: np.ndarray, dates: pd.DatetimeIndex, fams: dict) -> dict[str, pd.Series]:
    """Each family's walk-forward stream from its trades with the given cost per trade."""
    out = {}
    for fam, picks in fams.items():
        pieces = []
        for y, name in sorted(picks.items()):
            sel = (t["config"] == name).to_numpy()
            acc = np.zeros(len(dates))
            for (i0, r, w), c in zip(t.loc[sel, ["i0", "rets", "w"]].itertuples(index=False), cost[sel]):
                rr = np.asarray(r, float).copy()
                rr[0] -= c
                n = min(len(rr), len(dates) - i0)
                acc[i0:i0 + n] += w * rr[:n]
            s = pd.Series(acc, index=dates)
            pieces.append(s.loc[f"{y}-01-01":f"{y}-12-31"])
        out[fam] = pd.concat(pieces)
    return out


def _combo(streams: dict, series: pd.DataFrame, fams: dict, members: dict) -> pd.Series:
    pieces = []
    for y, mem in sorted(members.items()):
        mem = [f for f in mem if f in streams]
        if not mem:
            continue
        M = pd.DataFrame({f: series[fams[f][y]] for f in mem})
        w = R14._ivol(M.loc[:f"{y - 1}-12-31"])
        S = pd.DataFrame({f: streams[f] for f in mem}).loc[f"{y}-01-01":f"{y}-12-31"].fillna(0.0)
        pieces.append((S * w).sum(axis=1))
    return pd.concat(pieces)


def cmd_analyze(args) -> int:
    t = pd.read_parquet(args.out / "trades.parquet")
    sp = pd.read_parquet(args.out / "spreads.parquet").drop_duplicates(["date", "symbol", "minute"])
    sp["half"] = sp["spread"] / 2
    for leg in ("entry", "exit"):
        t = t.merge(sp.rename(columns={"date": f"{leg}_date", "minute": f"{leg}_min", "half": f"h_{leg}"})
                    [[f"{leg}_date", "symbol", f"{leg}_min", f"h_{leg}"]], on=[f"{leg}_date", "symbol", f"{leg}_min"],
                    how="left")
    D = R14.PREP.load(args.inputs / "v14" / "daily.pkl")
    table = R14.PREP.load(args.inputs / "v15" / "avail.pkl")["table"]
    dates, cash = D["dates"], D["cash"]
    fams, members = _summary()
    series = pd.read_parquet(args.out / "series.parquet")
    price = np.maximum(t["price"].to_numpy(float), 0.01)
    _, fee = v15.lookup(table, price, t["so"].to_numpy(float))
    short = t["side"].to_numpy() < 0
    fixed = (2 * np.minimum(v19.R3_COMM / price, 0.01) + v19.R3_SEC + v19.R3_TAF / price
             + np.where(short, np.maximum(2 * fee, 100.0) / 100 / 360 * t["nights"].to_numpy(float), 0.0))
    tier_in, tier_out = _tier(price, t["entry_min"].to_numpy() == 0), _tier(price, t["exit_min"].to_numpy() == 0)
    meas_in = t["h_entry"].fillna(pd.Series(tier_in, index=t.index)).to_numpy(float)
    meas_out = t["h_exit"].fillna(pd.Series(tier_out, index=t.index)).to_numpy(float)
    tier = _tier(price, np.zeros(len(t), bool)) * (2 + (v19.R3_OPEN - 1) * t["opens"].to_numpy(float))  # as in v19r
    costs = {"tier": tier + fixed, "measured": meas_in + meas_out + fixed}
    lines = ["# v19q: the v19r picks with each trade's own quoted spreads", "",
             f"{len(t)} trades; entry quotes found for {int(t['h_entry'].notna().sum())}, exit quotes for "
             f"{int(t['h_exit'].notna().sum())} (missing legs keep the R3 tier value).", "",
             "## Measured half-spreads against the R3 tiers", "",
             "| family | leg | n with quotes | measured median | measured mean | R3 tier mean |", "|---|---|---|---|---|---|"]
    for fam in fams:
        f = (t["family"] == fam).to_numpy()
        for leg, h, tier in (("entry", "h_entry", tier_in), ("exit", "h_exit", tier_out)):
            x = t.loc[f, h]
            ok = x.notna().to_numpy()
            if ok.any():
                lines.append(f"| {fam} | {leg} | {int(ok.sum())} | {x.median():.2%} | "
                             f"{x.clip(upper=x.quantile(0.99)).mean():.2%} | {tier[f][ok].mean():.2%} |")
    out = {}
    lines += ["", "## Walk-forward with each cost (middle scenario)", "",
              "| stream | Sortino tier (R3) | Sortino measured | 2018-20 | 2021-26 | CAGR | max DD | 2023-07+ | "
              "mean cost a trade (tier / measured) |", "|---|---|---|---|---|---|---|---|---|"]
    st = {k: _streams(t, c, dates, fams) for k, c in costs.items()}
    combos = {k: _combo(v, series, fams, members) for k, v in st.items()}
    end = str(dates[-1].date())
    for name in [*fams, "COMBO19"]:
        a = combos["tier"] if name == "COMBO19" else st["tier"][name]
        b = combos["measured"] if name == "COMBO19" else st["measured"][name]
        sa, sb = R14._stats(a, cash, "2018-01-01", end), R14._stats(b, cash, "2018-01-01", end)
        h1, h2 = R14._stats(b, cash, "2018-01-01", "2020-12-31"), R14._stats(b, cash, "2021-01-01", end)
        seg = R14._stats(b, cash, "2023-07-01", end)
        f = (t["family"] == name).to_numpy()
        mc = (f"{costs['tier'][f].mean():.2%} / {costs['measured'][f].mean():.2%}" if f.any() else "")
        out[name] = {"tier": sa, "measured": sb, "h1": h1, "h2": h2, "segment": seg}
        lines.append(f"| {name} | {sa.get('sortino', np.nan):.2f} | {sb.get('sortino', np.nan):.2f} | "
                     f"{h1.get('sortino', np.nan):.2f} | {h2.get('sortino', np.nan):.2f} | {sb.get('cagr', np.nan):.1%} | "
                     f"{sb.get('dd', np.nan):.1%} | {seg.get('sortino', np.nan):.2f} | {mc} |")
    (args.out / "quotes.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    (args.out / "QUOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("trades", "quotes", "analyze"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v19/quotes"))
    args = ap.parse_args()
    return {"trades": cmd_trades, "quotes": cmd_quotes, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
