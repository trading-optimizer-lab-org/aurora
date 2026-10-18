#!/usr/bin/env python3
"""v9: twenty strategy families aimed at a monthly Sortino of 10, all at once.
Pre-registered in docs/research/V9_PREREGISTRATION.md.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_v9.py fetch-bars \
        --panel-dir outputs/stock_panel --cache outputs/alpaca15
    SEC_USER_AGENT="name email" python scripts/run_v9.py fetch-inputs --panel-dir outputs/stock_panel \
        --sec-cache outputs/sec9 --out outputs/v9_inputs
    python scripts/run_v9.py shard --group daily --shard 0 --workers 4 --out outputs/v9/daily_0
    python scripts/run_v9.py report --parts outputs/v9 --output-dir outputs/v9_report

Market data stays in the Actions cache; only strategy returns and reports are uploaded.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import stock_catalog as sc
from aurora.research import v9_common as c
from aurora.research import v9_daily as vd
from aurora.research import v9_etf as vf
from aurora.research import v9_events as ve
from aurora.research import v9_intraday as vi
from aurora.research import v9_overlay as vo

N_SHARDS = 160
BATCH = 250  # symbols per Alpaca call: 250 x 26 bars fit in one page
ALPACA_PER_MIN, SEC_PER_SECOND = 190, 8
SEC_FIRST, SEC_LAST = "2003-01-01", "2020-12-31"
BAR_COLS = ["symbol", "slot", "o", "h", "l", "c", "v", "vw"]
PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")
SYMBOLS = Path("docs/research/data/stock_catalog_symbols.csv")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Limiter:
    """At most ``per_second`` calls a second across threads."""

    def __init__(self, per_second: float) -> None:
        self.gap, self.lock, self.next = 1.0 / per_second, threading.Lock(), time.monotonic()
        self.calls = 0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
            self.calls += 1
        time.sleep(max(0.0, at - now))


_local = threading.local()


def _get(url: str, params: dict | None, headers: dict, limiter: Limiter) -> dict | None:
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    for attempt in range(8):
        limiter.wait()
        r = _local.session.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 404:
            return None
        if r.status_code == 403:
            raise SystemExit(f"request refused (403): {url}")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"kept failing: {url}")


def _load(panel_dir: Path):
    panel, bench = _script("run_stock_catalog").load_panel(panel_dir)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    return panel, bench, cash_index.loc[cash_index.index < sc.LOCKED_START]


# ---------------------------------------------------------------- fetching (cache only)

def bar_days(panel: dict) -> dict[pd.Timestamp, list[str]]:
    ranks = c.universe_ranks(panel["close"], panel["volume"])
    dates = panel["close"].index
    out = {}
    for i in np.flatnonzero((dates >= c.INTRA_START) & (dates <= c.INTRA_END)):
        prev = ranks.iloc[i - 1]
        out[dates[i]] = sorted(prev.index[prev <= vi.UNIVERSE])
    return out


def consolidate(folder: Path, days: list[pd.Timestamp], out: Path) -> None:
    frames = {d: pd.read_parquet(folder / f"{d.date()}.parquet") for d in days}
    syms = sorted(set().union(*[set(f["symbol"]) for f in frames.values()]))
    pos = {s: i for i, s in enumerate(syms)}
    arr = {k: np.full((len(days), vi.SLOTS, len(syms)), np.nan, dtype=np.float32) for k in ("o", "c", "v", "vw")}
    for i, d in enumerate(days):
        f = frames[d]
        j, s = f["symbol"].map(pos).to_numpy(), f["slot"].to_numpy()
        for k in arr:
            arr[k][i, s, j] = f[k].to_numpy(np.float32)
    np.savez(out, days=np.array(days, dtype="datetime64[D]"), symbols=np.array(syms), **arr)
    print(f"bars: {len(days)} days x {len(syms)} symbols -> {out}", flush=True)


def cmd_fetch_bars(args) -> int:
    fetch = _script("run_qullamaggie_intraday")
    api = fetch.Alpaca()
    panel, _ = _script("run_stock_catalog").load_panel(args.panel_dir)
    need = bar_days(panel)
    del panel
    folder = args.cache / "bars15"
    folder.mkdir(parents=True, exist_ok=True)
    limiter = Limiter(ALPACA_PER_MIN / 60)

    def one(day: pd.Timestamp, syms: list[str]) -> None:
        path = folder / f"{day.date()}.parquet"
        if path.exists():
            return
        if day > fetch.LAST:
            raise ValueError("refusing to request data after 2020-12-31 (locked period)")
        back = {fetch.alpaca_symbol(s): s for s in syms}
        todo = list(back) + [e for e in vi.ETFS if e not in back]
        start, end = fetch._ny(day, 9, 30), fetch._ny(day, 15, 59)
        rows = []
        for b in range(0, len(todo), BATCH):
            params = {"symbols": ",".join(todo[b:b + BATCH]), "timeframe": "15Min", "start": start.isoformat(),
                      "end": end.isoformat(), "feed": "sip", "adjustment": "raw", "limit": 10000}
            while True:
                body = _get(fetch.API, params, api.headers, limiter) or {}
                for asym, bars in (body.get("bars") or {}).items():
                    for x in bars:
                        slot = int((pd.Timestamp(x["t"]) - start).total_seconds() // 900)
                        if 0 <= slot < vi.SLOTS:
                            rows.append((back.get(asym, asym), slot, x["o"], x["h"], x["l"], x["c"], x["v"],
                                         x.get("vw", np.nan)))
                token = body.get("next_page_token")
                if not token:
                    break
                params = {**params, "page_token": token}
        tmp = path.with_suffix(".tmp")
        pd.DataFrame(rows, columns=BAR_COLS).to_parquet(tmp, index=False)
        tmp.replace(path)

    days = sorted(need)
    with ThreadPoolExecutor(args.workers) as ex:
        futures = [ex.submit(one, d, need[d]) for d in days]
        for n, f in enumerate(as_completed(futures)):
            f.result()
            if n % 100 == 0:
                print(f"15-minute bars: {n}/{len(days)} days, {limiter.calls} calls", flush=True)
    print(f"Alpaca calls (only for days missing from the cache): {limiter.calls}", flush=True)
    consolidate(folder, days, args.cache / "bars15.npz")
    return 0


def _item_202(block: dict) -> list[str]:
    for key in ("form", "filingDate", "items"):
        if key not in block:
            raise SystemExit(f"unexpected SEC submissions format: missing '{key}'")
    return [d for f, d, it in zip(block["form"], block["filingDate"], block["items"])
            if f in ("8-K", "8-K/A") and "2.02" in str(it).split(",") and SEC_FIRST <= d <= SEC_LAST]


def sec_dates(cik: int, headers: dict, limiter: Limiter, cache: Path) -> list[str] | None:
    path = cache / "earnings_full" / f"{cik}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", None, headers, limiter)
    dates = None
    if sub is not None:
        filings = sub.get("filings")
        if not filings or "recent" not in filings:
            raise SystemExit("unexpected SEC submissions format: no filings.recent")
        dates = _item_202(filings["recent"])
        for f in filings.get("files", []):
            if f.get("filingTo", "9999") >= SEC_FIRST and f.get("filingFrom", "0000") <= SEC_LAST:
                older = _get(f"https://data.sec.gov/submissions/{f['name']}", None, headers, limiter)
                if older:
                    dates += _item_202(older)
        dates = sorted(set(dates))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dates), encoding="utf-8")
    return dates


def etf_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    import yfinance as yf

    opens, closes = {}, {}
    for s in vf.ALL_ETFS:
        df = yf.download(s, start="1993-01-01", end=str(sc.LOCKED_START.date()), auto_adjust=True, progress=False,
                         threads=False)
        if df is None or df.empty:
            print(f"warning: no Yahoo data for {s}", flush=True)
            continue
        for name, store in (("Open", opens), ("Close", closes)):
            col = df[name]
            col = col.iloc[:, 0] if isinstance(col, pd.DataFrame) else col
            col.index = pd.to_datetime(col.index).tz_localize(None).normalize()
            store[s] = col.loc[:sc.VALIDATION_END]
    return pd.DataFrame(opens), pd.DataFrame(closes)


def cmd_fetch_inputs(args) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    o, cl = etf_prices()
    o.to_parquet(args.out / "etf_open.parquet")
    cl.to_parquet(args.out / "etf_close.parquet")
    print(f"ETFs: {list(cl.columns)}", flush=True)
    catalyst = _script("run_qullamaggie_catalyst")
    sec = catalyst.Sec()
    panel, _ = _script("run_stock_catalog").load_panel(args.panel_dir)
    ranks = c.universe_ranks(panel["close"], panel["volume"]).loc["2003-01-01":]
    symbols = ranks.columns[(ranks <= vd.KEEP_RANK).any()]
    del panel, ranks
    ciks = catalyst.ticker_ciks(sec, args.sec_cache)
    cik = {s: ciks[s.upper()] for s in symbols if s.upper() in ciks}
    limiter = Limiter(SEC_PER_SECOND)
    earnings: dict[str, list[str]] = {}
    with ThreadPoolExecutor(args.workers) as ex:
        futures = {ex.submit(sec_dates, k, sec.headers, limiter, args.sec_cache): s for s, k in sorted(cik.items())}
        for n, f in enumerate(as_completed(futures)):
            dates = f.result()
            if dates is not None:
                earnings[futures[f]] = dates
            if n % 250 == 0:
                print(f"SEC filings: {n}/{len(cik)} companies, {limiter.calls} calls", flush=True)
    (args.out / "earnings.json").write_text(json.dumps(earnings), encoding="utf-8")
    print(f"SEC: {len(earnings)} of {len(symbols)} symbols covered, {limiter.calls} calls", flush=True)
    return 0


# ---------------------------------------------------------------- shards

_G: dict = {}


def _work(t: dict) -> tuple[dict, pd.Series]:
    fam = t["family"]
    if fam in vd.RUNNERS:
        series = vd.RUNNERS[fam](t, _G["x"])
    elif fam in ve.RUNNERS:
        series = ve.RUNNERS[fam](t, _G["x"], _G["ev"])
    elif fam in vf.RUNNERS:
        series = vf.RUNNERS[fam](t, _G["x"], _G["etf"])
    elif fam in vi.RUNNERS:
        series = vi.RUNNERS[fam](t, _G["intra"])
    else:
        series = vo.brake_trial(t, _G["bases"], _G["x"]["cash_s"])
    row = c.trial_row(t, series, _G["x"]["cash_s"])
    return row, series[c.COSTS[t["costs"]][0]].astype(np.float32).rename(t["name"])


def prepare(tri: list[dict], panel_dir: Path, inputs: Path | None, bars: Path | None) -> None:
    panel, bench, cash_index = _load(panel_dir)
    symbols = pd.read_csv(SYMBOLS).set_index("symbol")
    _G["x"] = vd.context(panel, bench["spy"], symbols, cash_index)
    del panel
    fams = {t["family"] for t in tri}
    if fams & set(c.EVENT_FAMILIES):
        earnings = json.loads((inputs / "earnings.json").read_text(encoding="utf-8"))
        _G["ev"] = ve.events(_G["x"], earnings)
    if fams & set(c.ETF_FAMILIES):
        _G["etf"] = vf.context(pd.read_parquet(inputs / "etf_open.parquet"),
                               pd.read_parquet(inputs / "etf_close.parquet"), _G["x"])
    if fams & set(c.INTRA_FAMILIES):
        with np.load(bars) as z:
            _G["intra"] = vi.context({k: z[k] for k in z.files}, _G["x"])
    if "BRAKE" in fams:
        _G["bases"] = vo.brake_bases(vo.phase7_streams())


def cmd_shard(args) -> int:
    tri = c.shard_trials(args.group, args.shard, args.n_shards)
    t0 = time.time()
    prepare(tri, args.panel_dir, args.inputs, args.bars)
    print(f"shard {args.group}/{args.shard}: {len(tri)} trials, context ready in {time.time() - t0:.0f}s", flush=True)
    if args.workers > 1:
        with mp.get_context("fork").Pool(args.workers) as pool:
            done = list(pool.imap_unordered(_work, tri))
    else:
        done = [_work(t) for t in tri]
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([r for r, _ in done]).to_parquet(args.out / "rows.parquet", index=False)
    pd.concat([s for _, s in done], axis=1).to_parquet(args.out / "series.parquet")
    print(f"shard done in {time.time() - t0:.0f}s", flush=True)
    return 0


# ---------------------------------------------------------------- report

def _fmt(v, f: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not np.isfinite(v) else f.format(v)


def _get_row(r: pd.Series, key: str):
    return r[key] if key in r.index else np.nan


def _line(name: str, r: pd.Series, extra: list[str] | None = None) -> str:
    sel, jud = c.SELECT[r["kind"]], c.JUDGE[r["kind"]]
    g = lambda k: _get_row(r, f"{jud}_{k}")  # noqa: E731
    cells = [name, _fmt(_get_row(r, f"{sel}_sortino_monthly"), "{:.2f}"), _fmt(g("sortino_monthly"), "{:.2f}"),
             _fmt(g("cagr"), "{:.1%}"), _fmt(g("max_drawdown"), "{:.1%}"), _fmt(g("total"), "{:+.0%}"),
             _fmt(g("worst_month"), "{:+.1%}"), _fmt(g("worst_day"), "{:+.1%}"), _fmt(g("positive_months"), "{:.0%}"),
             _fmt(_get_row(r, "deflated_sharpe"), "{:.2f}"), "YES" if r.get("passed") is True or r.get("passed") == 1
             else "no"]
    return "| " + " | ".join(cells + (extra or [])) + " |"


HEAD = ("| {} | selection Sortino | judgment Sortino | CAGR | max DD | total | worst month | worst day | "
        "positive months | DSR | passed |{}")


def render(df: pd.DataFrame, members: dict, corr: pd.DataFrame, expected: int, got: int) -> str:
    spy = df.attrs["spy"]
    lines = ["# v9: twenty families aimed at a monthly Sortino of 10 (pre-registered)", "",
             f"{got:,} of {expected:,} trials, plus the combinations; deflated Sharpe over {df.attrs['n_trials']:,} "
             "trials. Selection periods: 1995-2010 (daily families, from each one's start) and 2016-2018 (intraday); "
             "judgment periods: 2011-2020 and 2019-2020. Main costs: stocks 5 bps, ETFs 2 bps per unit of turnover. "
             "Survivorship bias NOT adjusted. Nothing after 2020-12-31 was read.", "",
             f"SPY judgment periods: 2011-2020 Sortino {_fmt(spy['daily'].get('validation_sortino_monthly'), '{:.2f}')}, "
             f"CAGR {_fmt(spy['daily'].get('validation_cagr'), '{:.1%}')}; 2019-2020 Sortino "
             f"{_fmt(spy['intraday'].get('p2_sortino_monthly'), '{:.2f}')}, CAGR "
             f"{_fmt(spy['intraday'].get('p2_cagr'), '{:.1%}')}.", ""]
    ten = df.index[df["sortino10"]]
    lines += ["## 1. Monthly Sortino of 10 or more in the judgment period", "",
              (", ".join(ten) if len(ten) else "none"), ""]
    sep = "|" + "---|" * 11
    lines += ["## 2. Final combinations", "", f"COMBO_DAILY members ({len(members['DAILY'])}): "
              f"{', '.join(members['DAILY']) or 'none'}.", "",
              f"COMBO_ALL members ({len(members['ALL'])}): {', '.join(members['ALL']) or 'none'}.", "",
              HEAD.format("combination", ""), sep]
    lines += [_line(n, df.loc[n]) for n in df.index if n.startswith("COMBO_")]
    pk = members["picks"].set_index("family")
    lines += ["", "## 3. One pick per family (best selection-period Sortino; judgment never used to choose)", "",
              HEAD.format("family: pick", " Sortino low / high cost | qualifies | variants with judgment Sortino >= 2 "
                          "| median judgment Sortino |"), "|" + "---|" * 15]
    for fam, p in pk.iterrows():
        r = df.loc[p["name"]]
        fam_rows = df[df["family"] == fam]
        jcol = f"{c.JUDGE[p['kind']]}_sortino_monthly"
        js = fam_rows[jcol].astype(float) if jcol in fam_rows.columns else pd.Series(dtype=float)
        lo, hi = c.COSTS["etf" if fam in c.ETF_FAMILIES or fam == "MKTINTRA" else "stock"][1:]
        sens = (f"{_fmt(_get_row(r, f's{lo}_{c.JUDGE[p.kind]}_sortino_monthly'), '{:.2f}')} / "
                f"{_fmt(_get_row(r, f's{hi}_{c.JUDGE[p.kind]}_sortino_monthly'), '{:.2f}')}")
        lines.append(_line(f"{fam}: {p['name']}", r, [sens, "yes" if p["qualifies"] else "no",
                                                      f"{int((js >= 2).sum())} of {len(fam_rows)}",
                                                      _fmt(js.median(), "{:.2f}")]))
    br = df[df["family"] == "BRAKE"]
    lines += ["", "## 4. Loss brake on the phase 7 streams", "", HEAD.format("brake", ""), sep]
    lines += [_line(n, br.loc[n]) for n in br.index]
    ranked = []
    for n, r in df[(df["family"] != "COMBO")].iterrows():
        ranked.append((float(_get_row(r, f"{c.JUDGE[r['kind']]}_sortino_monthly")), n))
    ranked = sorted([x for x in ranked if np.isfinite(x[0])], reverse=True)[:40]
    lines += ["", "## 5. The 40 best trials by judgment-period Sortino (choosing this way is overfitting; for "
              "information only)", "", HEAD.format("trial", ""), sep]
    lines += [_line(n, df.loc[n]) for _, n in ranked]
    lines += ["", "## 6. Monthly-return correlations of the qualifying picks and phase 7 members, 2016-2020", ""]
    if len(corr):
        lines += ["| | " + " | ".join(corr.columns) + " |", "|" + "---|" * (len(corr.columns) + 1)]
        lines += [f"| {n} | " + " | ".join(_fmt(v, "{:+.2f}") for v in r) + " |" for n, r in corr.iterrows()]
    passed = df.index[df["passed"]]
    lines += ["", "## 7. Pre-registered criteria on the judgment period (Sortino >= 2, CAGR above SPY, max drawdown "
              "no deeper than -25%)", "", f"Passed: {len(passed)}: {', '.join(passed[:200]) if len(passed) else 'none'}"
              f"{' ...' if len(passed) > 200 else ''}.", ""]
    return "\n".join(lines) + "\n"


def cmd_report(args) -> int:
    parts = sorted(args.parts.rglob("rows.parquet"))
    rows = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    series = pd.concat([pd.read_parquet(p.with_name("series.parquet")) for p in parts], axis=1).sort_index()
    expected = len(c.trials())
    panel_bench = pd.read_parquet(args.panel_dir / "benchmarks.parquet")
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    dates = panel_bench["gspc"].dropna().loc[sc.TRAIN_START:sc.VALIDATION_END].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    spy = panel_bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    phase7 = vo.phase7_streams()
    combo, members = vo.combos(series, rows, phase7, cash)
    crow = [{"name": n, "family": "COMBO", "kind": k, **c.evaluate(r, cash, c.PERIODS[k])} for n, (r, k) in combo.items()]
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k, v in prior.items() if isinstance(v, dict) for x in v.values()]
    pool += [x for x in prior["v7"] if x is not None]
    df = vo.finish(pd.concat([rows, pd.DataFrame(crow)], ignore_index=True), spy, cash, pool)
    keep = sorted(set(members["ALL"]))
    R = pd.concat([series.reindex(columns=[k for k in keep if k in series.columns]),
                   phase7[[k for k in keep if k in phase7.columns]]], axis=1).loc[c.INTRA_START:c.INTRA_END]
    corr = ((1 + R.fillna(0.0)).groupby(R.index.to_period("M")).prod() - 1).corr() if R.shape[1] else pd.DataFrame()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    df.reset_index().to_parquet(out / "results.parquet", index=False)
    members["picks"].to_csv(out / "picks.csv", index=False)
    pd.DataFrame({n: r for n, (r, _) in combo.items()}).to_csv(out / "combo_streams.csv")
    series[[n for n in members["picks"]["name"] if n in series.columns]].to_csv(out / "pick_streams.csv")
    text = render(df, members, corr, expected, len(rows))
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text[:20000])
    return 0 if len(rows) == expected else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("fetch-bars")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca15"))
    a.add_argument("--workers", type=int, default=4)
    a = sub.add_parser("fetch-inputs")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec9"))
    a.add_argument("--out", type=Path, default=Path("outputs/v9_inputs"))
    a.add_argument("--workers", type=int, default=4)
    a = sub.add_parser("shard")
    a.add_argument("--group", choices=("daily", "mixed"), required=True)
    a.add_argument("--shard", type=int, required=True)
    a.add_argument("--n-shards", type=int, default=N_SHARDS)
    a.add_argument("--workers", type=int, default=4)
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--inputs", type=Path, default=Path("outputs/v9_inputs"))
    a.add_argument("--bars", type=Path, default=Path("outputs/alpaca15/bars15.npz"))
    a.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("report")
    a.add_argument("--parts", type=Path, default=Path("outputs/v9"))
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/v9_report"))
    args = ap.parse_args()
    return {"fetch-bars": cmd_fetch_bars, "fetch-inputs": cmd_fetch_inputs, "shard": cmd_shard,
            "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
