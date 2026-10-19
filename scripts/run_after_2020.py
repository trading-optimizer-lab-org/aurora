#!/usr/bin/env python3
"""Follow-up requested by the owner: the intraday stock strategies with a 2016-2020 monthly Sortino of 4 or more,
from 2021-01-04 to 2026-10-16. Descriptive; see docs/research/AFTER_2020_FOLLOWUP.md.

    python scripts/run_after_2020.py rehearse --panel-dir outputs/stock_panel --cache outputs/alpaca --sec-cache outputs/sec
    python scripts/run_after_2020.py evaluate --panel-dir outputs/stock_panel --out outputs/after \
        --cache outputs/alpaca_locked --sec-cache outputs/sec_locked --nasdaq outputs/alpaca/ixic.csv

Reuses the data steps of scripts/run_intraday_locked.py with the end moved to 2026-10-16.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import combination as cb
from aurora.research import combination_plus as cp
from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_catalyst as qc
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_sizing as qz
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import v9_common as c

LAST = pd.Timestamp("2026-10-16")
TOLERANCE = 1e-9
REFERENCE = {"I_EP_E0": (4.718379619056188, 0.2615470857179578),
             "I_MIX_MODEL_N3_E0": (4.449006765954816, 0.39845288342310203),
             "SIZE_S2_P0_C0_X1": (4.805092904619223, 0.40520426927058306)}
ORDER = ["INTRADAY_EQ", "INTRADAY_EQ_L2", "INTRADAY_EQ_L3", "I_EP_E0", "I_MIX_MODEL_N3_E0", "SIZE_S2_P0_C0_X1",
         "EP_EARN", "EP_NEWS", "BO_TOP3", "SPY"]


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LK = _script("run_intraday_locked")


def build(panel: dict, bench: pd.DataFrame, cash_index: pd.Series, nasdaq: pd.Series, cache: Path,
          sec_cache: Path) -> tuple[dict[str, pd.Series], pd.Series]:
    """All six streams from one preparation; the phase 7a part as in combination.intraday_streams."""
    fetch, cat = LK.FETCH, LK.CAT
    industry = pd.read_csv(LK.SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    ep_symbols = sorted(cands["IEP_N0"].columns[cands["IEP_N0"].fillna(False).astype(bool).any()])
    del cands
    api = fetch.Alpaca()
    alp_daily = fetch.fetch_daily(api, cache, sorted({s for v in need.values() for s in v}))
    fetch.fetch_minutes(api, cache, need)
    sec = cat.Sec()
    ciks = cat.ticker_ciks(sec, sec_cache)
    cik = {s: ciks[s.upper()] for s in ep_symbols if s.upper() in ciks}
    earnings: dict[str, list[pd.Timestamp]] = {}
    for s, k in sorted(cik.items()):
        dts = cat.earnings_dates(sec, sec_cache, k)
        if dts is not None:
            earnings[s] = [pd.Timestamp(d) for d in dts]
    print(json.dumps({"alpaca_calls": api.calls, "sec_calls": sec.calls}), flush=True)
    wind_df = qw.wind(panel, ind, ctx)
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, fetch.minute_loader(cache), alp_daily)
    ib, ie, mix = qs.intraday_signals(prep, kept[("MODEL", 3)])

    def sim(sig, **kw) -> pd.Series:
        e, s, px, sd = sig
        return sc.simulate(prep["panel"], prep["ind"], e, s, qw.EXIT, prep["cash"], prep["rank"], start=qi.START,
                           entry_px=px, same_day_px=sd, **kw)["return"]

    out: dict[str, pd.Series] = {}
    cand = prep["cands"]["IEP_N0"].stack()
    cells = cand[cand].index.to_frame(index=False)
    cells.columns = ["date", "symbol"]
    lab = qc.labels(cells, prep["panel"]["close"].index, earnings, set(earnings), cik, {})
    for name, cat_name, n in (("EP_EARN", "EARN", "N0"), ("EP_NEWS", "NOEARN", "N1")):
        mask = qc.label_mask(lab, cat_name, prep["cands"]["IEP_N0"])
        cands2 = dict(prep["cands"])
        cands2[f"IEP_{n}"] = cands2[f"IEP_{n}"] & mask.reindex_like(cands2[f"IEP_{n}"]).fillna(False)
        trial = qi.Trial(f"IEP_{n}_Q05_K5_XQ3_20", "IEP", n, "Q05", 5, qw.EXIT)
        out[name] = sim(qi.trial_inputs(trial, prep["table"], cands2, prep["m1"], prep["adr_prior"], prep["like"])[:4])
    out["BO_TOP3"] = sim(ib)
    scale, gross, cap = qw.policy("E0", wind_df)
    out["I_EP_E0"] = sim(ie, risk_scale=scale, max_gross=gross, cap=cap)
    out["I_MIX_MODEL_N3_E0"] = sim(mix, risk_scale=scale, max_gross=gross, cap=cap)
    out["SIZE_S2_P0_C0_X1"] = sim(mix, risk=sc.RISK, cap=sc.CAP, pyramid=False, cushion=False,
                                  extended_sell=qz.EXTENDED)
    return out, prep["cash"]


def cmd_rehearse(args) -> int:
    panel, bench = LK.PANEL.load_panel(args.panel_dir)
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("the rehearsal must run on the sealed panel")
    cash_index = LK.MAB.tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    out, cash = build(panel, bench, cash_index, LK.QS.nasdaq_close(args.cache / "ixic.csv"), args.cache, args.sec_cache)
    ref = cp.load_7a()
    bad = []
    for k in LK.STREAMS:
        a, b = out[k].reindex(ref.index).loc[qi.START:qi.END], ref[k].loc[qi.START:qi.END]
        worst = float((a - b).abs().max())
        print(f"{k}: max difference {worst:.3e}", flush=True)
        if not bool((a.isna() == b.isna()).all()) or not np.isfinite(worst) or worst > TOLERANCE:
            bad.append(k)
    for k, (sortino, cagr) in REFERENCE.items():
        m = sc.metrics(out[k].loc[qi.START:qi.END], cash)
        d = max(abs(m["sortino_monthly"] - sortino), abs(m["cagr"] - cagr))
        print(f"{k}: Sortino {m['sortino_monthly']:.6f} (published {sortino:.6f}), CAGR {m['cagr']:.6f} "
              f"(published {cagr:.6f}), difference {d:.2e}", flush=True)
        if not np.isfinite(d) or d > TOLERANCE:
            bad.append(k)
    if bad:
        print(f"REHEARSAL FAILED for {bad}", flush=True)
        return 1
    print("rehearsal passed", flush=True)
    return 0


def _yearly(r: pd.Series) -> dict[str, float]:
    return {str(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}


def cmd_evaluate(args) -> int:
    LK.LAST = LAST
    LK.cmd_prepare(argparse.Namespace(panel_dir=args.panel_dir, out=args.out, cache=args.cache,
                                      sec_cache=args.sec_cache, nasdaq=args.nasdaq))
    panel, bench = LK.PANEL.load_panel(args.out / "panel")
    cash_index = LK.MAB.tbill_index({}).loc[:LAST]
    out, _ = build(panel, bench, cash_index, LK.QS.nasdaq_close(args.out / "panel" / "ixic.csv"), args.cache,
                   args.sec_cache)
    first = LK.FIRST
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0).loc[first:LAST]
    S = pd.DataFrame(out).loc[first:LAST].fillna(0.0)
    eq = S[list(LK.STREAMS)].mean(axis=1)
    series = {"INTRADAY_EQ": eq, "INTRADAY_EQ_L2": cp.leverage(eq, cash, 2.0), "INTRADAY_EQ_L3": cp.leverage(eq, cash, 3.0),
              **{k: S[k] for k in ("I_EP_E0", "I_MIX_MODEL_N3_E0", "SIZE_S2_P0_C0_X1", *LK.STREAMS)},
              "SPY": bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0).loc[first:LAST]}
    periods = {"after": (first, LAST), "y2124": (first, pd.Timestamp("2024-12-31")),
               "y2526": (pd.Timestamp("2025-01-01"), LAST)}
    rows = {n: {**c.evaluate(r, cash, periods), "yearly": _yearly(r)} for n, r in series.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(series).to_csv(args.out / "streams_after.csv")
    (args.out / "results.json").write_text(json.dumps(rows, indent=1, default=float), encoding="utf-8")
    text = render(rows)
    (args.out / "AFTER.md").write_text(text, encoding="utf-8")
    print(text, flush=True)
    return 0


def _f(v, fmt: str) -> str:
    return "-" if v is None or not np.isfinite(float(v)) else fmt.format(float(v))


def render(rows: dict) -> str:
    lines = [f"# Intraday strategies with a 2016-2020 Sortino of 4 or more, 2021-01-04 to {LAST.date()}", "",
             "| strategy | monthly Sortino | CAGR | max DD | total | worst month | worst day | Sortino 2021-24 | "
             "Sortino 2025-26 |", "|---|---|---|---|---|---|---|---|---|"]
    for n in ORDER:
        r = rows[n]
        lines.append(f"| {n} | {_f(r.get('after_sortino_monthly'), '{:.2f}')} | {_f(r.get('after_cagr'), '{:.1%}')} | "
                     f"{_f(r.get('after_max_drawdown'), '{:.1%}')} | {_f(r.get('after_total'), '{:+.0%}')} | "
                     f"{_f(r.get('after_worst_month'), '{:+.1%}')} | {_f(r.get('after_worst_day'), '{:+.1%}')} | "
                     f"{_f(r.get('y2124_sortino_monthly'), '{:.2f}')} | {_f(r.get('y2526_sortino_monthly'), '{:.2f}')} |")
    years = list(rows["INTRADAY_EQ"]["yearly"])
    lines += ["", "| strategy | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for n in ORDER:
        lines.append(f"| {n} | " + " | ".join(_f(rows[n]["yearly"].get(y), "{:+.1%}") for y in years) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("rehearse", "evaluate"):
        a = sub.add_parser(name)
        a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
        a.add_argument("--out", type=Path, default=Path("outputs/after"))
        a.add_argument("--cache", type=Path, default=Path("outputs/alpaca" if name == "rehearse" else "outputs/alpaca_locked"))
        a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec" if name == "rehearse" else "outputs/sec_locked"))
        a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    args = ap.parse_args()
    return {"rehearse": cmd_rehearse, "evaluate": cmd_evaluate}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
