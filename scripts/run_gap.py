#!/usr/bin/env python3
"""Gap study against Qullamaggie's self-reported returns (diagnostic, 2016-01-04 to 2026-10-16).
Pre-registered in docs/research/GAP_PREREGISTRATION.md.

    python scripts/run_gap.py run --panel-dir outputs/stock_panel --out outputs/gap --old-cache outputs/alpaca \
        --cache outputs/alpaca_locked --sec-cache outputs/sec_locked --nasdaq outputs/alpaca/ixic.csv --workers 4

Builds the 2016-2026 panel and minute data from the earlier runs' caches, checks that the base book reproduces its
published 2016-2020 result, then runs parts A (monster moves), B (96 lever configurations) and C (foresight bounds).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import shutil
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_trades as st

START, WARMUP, LAST = pd.Timestamp("2016-01-04"), pd.Timestamp("2015-11-02"), pd.Timestamp("2026-10-16")
SPLIT = pd.Timestamp("2020-12-31")
PERIODS = {"p1": (START, SPLIT), "p2": (pd.Timestamp("2021-01-01"), LAST), "all": (START, LAST)}
MONSTER_X, MONSTER_LOOK, MIN_PRICE, MIN_DV = 3.0, 126, 5.0, 5e6
EXITS, RISKS, CAPS, GROSS, PYRAMID = ("XQ3_20", "XQ5_20", "XQC20"), (0.005, 0.01), (0.20, 0.35), (1.0, 2.0), (False, True)
AGGRESSIVE = {"exit": "XQC20", "risk": 0.01, "cap": 0.35, "gross": 2.0, "pyramid": True}
BASE = {"exit": "XQ3_20", "risk": 0.005, "cap": 0.20, "gross": 1.0, "pyramid": False}
HIS = {"2020": 36.0 / 3.5 - 1}


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LK = _script("run_intraday_locked")
RA = _script("run_after_2020")


def merge_caches(old: Path, new: Path) -> None:
    """2016-2020 minute days from the phase 7 cache next to the 2021+ ones; daily bars split at 2020-12-31."""
    (new / "minutes").mkdir(parents=True, exist_ok=True)
    for f in (old / "minutes").glob("*"):
        target = new / "minutes" / f.name
        if not target.exists():
            shutil.copy2(f, target)
    a, b = pd.read_parquet(old / "daily.parquet"), pd.read_parquet(new / "daily.parquet")
    a = a[a["date"].notna() & (a["date"] <= SPLIT)]
    b = b[b["date"].isna() | (b["date"] > SPLIT)]
    pd.concat([a, b], ignore_index=True).to_parquet(new / "daily.parquet", index=False)


def monsters(panel: dict, cols_years: range) -> pd.DataFrame:
    C, V = panel["close"], panel["volume"]
    dv = (C * V).rolling(20, min_periods=20).mean()
    low = C.rolling(MONSTER_LOOK, min_periods=60).min()
    ratio = (C / low).to_numpy()
    Cn, dvn, dates = C.to_numpy(), dv.to_numpy(), C.index
    out = []
    for y in cols_years:
        rows = np.flatnonzero((dates.year == y) & (dates >= START) & (dates <= LAST))
        if not rows.size:
            continue
        sub = np.nan_to_num(ratio[rows], nan=0.0)
        for j in np.flatnonzero(sub.max(axis=0) >= MONSTER_X):
            tp = rows[int(sub[:, j].argmax())]
            w0 = max(0, tp - MONSTER_LOOK + 1)
            seg = Cn[w0:tp + 1, j]
            tl = w0 + len(seg) - 1 - int(np.nanargmin(seg[::-1]))  # the last low before the move
            if not (Cn[tl, j] >= MIN_PRICE and dvn[tl, j] >= MIN_DV):
                continue
            mult = Cn[tp, j] / Cn[tl, j]
            half = Cn[tl, j] * (1 + 0.5 * (mult - 1))
            after = np.flatnonzero(Cn[tl:tp + 1, j] >= half)
            th = tl + int(after[0]) if after.size else tp
            out.append({"year": y, "symbol": C.columns[j], "low_date": dates[tl], "half_date": dates[th],
                        "peak_date": dates[tp], "multiple": float(mult)})
    return pd.DataFrame(out)


_G: dict = {}


def _sim(cfg: dict, sig: tuple | None = None, trades: list | None = None) -> pd.Series:
    g = _G
    e, s, px, sd = sig if sig is not None else g["signals"][cfg["set"]]
    gross = pd.Series(cfg["gross"], index=g["dates"])
    return sc.simulate(g["panel"], g["ind"], e, s, cfg["exit"], g["cash"], g["rank"], start=START, entry_px=px,
                       same_day_px=sd, risk=cfg["risk"], cap=cfg["cap"], max_gross=gross, pyramid=cfg["pyramid"],
                       trades=trades)["return"]


def _row(name: str, cfg: dict, r: pd.Series) -> dict:
    row = {"name": name, **{k: v for k, v in cfg.items() if k != "set"}, "set": cfg.get("set")}
    cash = _G["cash"]
    for p, (a, b) in PERIODS.items():
        x = r.loc[a:b]
        m = sc.metrics(x, cash)
        row.update({f"{p}_cagr": m.get("cagr"), f"{p}_sortino": m.get("sortino_monthly"),
                    f"{p}_dd": m.get("max_drawdown"), f"{p}_total": float((1 + x).prod() - 1)})
    yearly = (1 + r.loc[START:LAST]).groupby(r.loc[START:LAST].index.year).prod() - 1
    row.update({f"y{y}": float(v) for y, v in yearly.items()})
    return row


def _work(item: tuple[str, dict]) -> dict:
    name, cfg = item
    return _row(name, cfg, _sim(cfg))


def grid() -> list[tuple[str, dict]]:
    out = []
    for s, ex, r, c, g, p in product(("MIX", "EP"), EXITS, RISKS, CAPS, GROSS, PYRAMID):
        cfg = {"set": s, "exit": ex, "risk": r, "cap": c, "gross": g, "pyramid": p}
        out.append((f"{s}_{ex}_R{r * 100:g}_C{c * 100:g}_G{g:g}_P{int(p)}", cfg))
    return out


def run(args) -> int:
    LK.LAST = LAST
    LK.cmd_prepare(argparse.Namespace(panel_dir=args.panel_dir, out=args.out, cache=args.cache,
                                      sec_cache=args.sec_cache, nasdaq=args.nasdaq))
    qi.START, qi.WARMUP, qi.END = START, WARMUP, LAST
    merge_caches(args.old_cache, args.cache)
    panel, bench = LK.PANEL.load_panel(args.out / "panel")
    cash_index = LK.MAB.tbill_index({}).loc[:LAST]
    nasdaq = LK.QS.nasdaq_close(args.out / "panel" / "ixic.csv")
    industry = pd.read_csv(LK.SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    api = LK.FETCH.Alpaca()
    alp_daily = LK.FETCH.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    LK.FETCH.fetch_minutes(api, args.cache, need)
    print(f"Alpaca calls for missing data: {api.calls}", flush=True)
    wind_df = qw.wind(panel, ind, ctx)
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, LK.FETCH.minute_loader(args.cache), alp_daily)
    _, ie, mix = qs.intraday_signals(prep, kept[("MODEL", 3)])
    del kept
    dates = prep["panel"]["close"].index
    _G.update(panel=prep["panel"], ind=prep["ind"], cash=prep["cash"], rank=prep["rank"], dates=dates,
              signals={"MIX": mix, "EP": ie})

    # gate: the base book must reproduce its published 2016-2020 result
    scale, gross, cap = qw.policy("E0", wind_df)
    base_trades: list = []
    base = sc.simulate(prep["panel"], prep["ind"], mix[0], mix[1], qw.EXIT, prep["cash"], prep["rank"], start=START,
                       entry_px=mix[2], same_day_px=mix[3], risk_scale=scale, max_gross=gross, cap=cap,
                       trades=base_trades)["return"]
    m = sc.metrics(base.loc[START:SPLIT], prep["cash"])
    ref_s, ref_c = RA.REFERENCE["I_MIX_MODEL_N3_E0"]
    gate = max(abs(m["sortino_monthly"] - ref_s), abs(m["cagr"] - ref_c))
    print(f"gate: Sortino {m['sortino_monthly']:.6f} vs {ref_s:.6f}, CAGR {m['cagr']:.6f} vs {ref_c:.6f}", flush=True)
    if not np.isfinite(gate) or gate > 1e-9:
        print("GATE FAILED: the 2016-2026 build does not reproduce 2016-2020", flush=True)
        return 1

    # A. monster moves
    mons = monsters(panel, range(2016, 2027))
    cmask = (cands["IEP_N0"] | cands["IBO_SCAN35"]).fillna(False).astype(bool)
    bt = pd.DataFrame(base_trades, columns=["symbol", "entry_date", "exit_date", "entry", "exit", "fraction", "return"])
    bt["symbol"] = prep["panel"]["close"].columns[bt["symbol"].to_numpy(dtype=int)]
    cov, slot, capt = [], [], []
    for _, r in mons.iterrows():
        col = cmask[r["symbol"]] if r["symbol"] in cmask.columns else pd.Series(False, index=cmask.index)
        cov.append(bool(col.loc[r["low_date"]:r["half_date"]].any()))
        tr = bt[(bt["symbol"] == r["symbol"]) & (bt["entry_date"] >= r["low_date"]) & (bt["entry_date"] <= r["peak_date"])]
        slot.append(len(tr) > 0)
        capt.append(float(tr["return"].max() / (r["multiple"] - 1)) if len(tr) else 0.0)
    mons["covered"], mons["bought"], mons["captured"] = cov, slot, capt

    # B. levers
    todo = grid()
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            rows = list(pool.imap_unordered(_work, todo))
    else:
        rows = [_work(t) for t in todo]

    # C. foresight bounds
    tl = st.trade_list(prep["panel"], prep["ind"], mix[0], mix[1], qw.EXIT, start=START, entry_px=mix[2],
                       same_day_px=mix[3])
    tl["year"] = tl["entry_date"].dt.year
    top = tl[tl["return"] >= tl.groupby("year")["return"].transform(lambda x: x.quantile(0.9))]
    like = mix[0]

    def only(cells: pd.DataFrame) -> tuple:
        mk = np.zeros(like.shape, dtype=bool)
        r_, c_ = like.index.get_indexer(cells["entry_date"]), like.columns.get_indexer(cells["symbol"])
        ok = (r_ >= 0) & (c_ >= 0)
        mk[r_[ok], c_[ok]] = True
        return (like & pd.DataFrame(mk, index=like.index, columns=like.columns), mix[1], mix[2], mix[3])

    mon_cells = []
    for _, r in mons.iterrows():
        if r["symbol"] in like.columns:
            hit = like.loc[r["low_date"]:r["peak_date"], r["symbol"]]
            mon_cells += [(d, r["symbol"]) for d in hit.index[hit.to_numpy()]]
    mon_df = pd.DataFrame(mon_cells, columns=["entry_date", "symbol"])
    for oname, cells in (("O_TOP10", top), ("O_MONSTER", mon_df)):
        for label, cfg in (("BASE", BASE), ("AGGRESSIVE", AGGRESSIVE)):
            rows.append(_row(f"{oname}_{label}", {**cfg, "set": "MIX"}, _sim({**cfg, "set": "MIX"}, only(cells))))
    rows.append(_row("BASE_E0", {**BASE, "set": "MIX"}, base))
    spy = bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    rows.append(_row("SPY", {"set": None}, spy))

    out = args.out
    df = pd.DataFrame(rows)
    df.to_parquet(out / "levers.parquet", index=False)
    mons.to_csv(out / "monsters.csv", index=False)
    text = render(df, mons)
    (out / "GAP.md").write_text(text, encoding="utf-8")
    print(text[:15000], flush=True)
    return 0


def _p(v) -> str:
    return "-" if v is None or not np.isfinite(float(v)) else f"{float(v):+.0%}"


def _s(v) -> str:
    return "-" if v is None or not np.isfinite(float(v)) else f"{float(v):.2f}"


def render(df: pd.DataFrame, mons: pd.DataFrame) -> str:
    lines = ["# Gap study against Qullamaggie (diagnostic, 2016-2026)", "",
             f"Self-reported: 2020 {HIS['2020']:+.0%} ($3.5M to $36M). Gate passed: the base book reproduces its "
             "published 2016-2020 result.", "", "## A. Monster moves (3x within 126 sessions, $5+, $5M+ a day)", "",
             "| year | monsters | covered by a candidate before half the move | bought by the base book | "
             "median share of the move captured when bought |", "|---|---|---|---|---|"]
    for y, g in mons.groupby("year"):
        b = g[g["bought"]]
        lines.append(f"| {y} | {len(g)} | {g['covered'].mean():.0%} | {g['bought'].mean():.0%} | "
                     f"{(b['captured'].median() if len(b) else float('nan')):.0%} |")
    lines += ["", "Largest 25 monsters:", "", "| year | symbol | multiple | covered | bought | captured |",
              "|---|---|---|---|---|---|"]
    for _, r in mons.sort_values("multiple", ascending=False).head(25).iterrows():
        lines.append(f"| {r['year']} | {r['symbol']} | {r['multiple']:.1f}x | {'yes' if r['covered'] else 'no'} | "
                     f"{'yes' if r['bought'] else 'no'} | {r['captured']:.0%} |")
    years = [c for c in df.columns if c.startswith("y")]
    head = ("| configuration | CAGR 16-20 | Sortino 16-20 | DD 16-20 | CAGR 21-26 | Sortino 21-26 | DD 21-26 | "
            + " | ".join(c[1:] for c in years) + " |")
    sep = "|" + "---|" * (7 + len(years))

    def line(r) -> str:
        return (f"| {r['name']} | {_p(r['p1_cagr'])} | {_s(r['p1_sortino'])} | {_p(r['p1_dd'])} | {_p(r['p2_cagr'])} | "
                f"{_s(r['p2_sortino'])} | {_p(r['p2_dd'])} | " + " | ".join(_p(r[c]) for c in years) + " |")

    lines += ["", "## B. His levers on our signals (all 96, sorted by 2016-2020 CAGR)", "", head, sep]
    lines += [line(r) for _, r in df[df["name"].str.startswith(("MIX_", "EP_"))].sort_values("p1_cagr", ascending=False).iterrows()]
    lines += ["", "## C. Foresight bounds (not tradable) and references", "", head, sep]
    lines += [line(r) for _, r in df[df["name"].str.startswith(("O_", "BASE_E0", "SPY"))].iterrows()]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--out", type=Path, default=Path("outputs/gap"))
    a.add_argument("--old-cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca_locked"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec_locked"))
    a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    a.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
