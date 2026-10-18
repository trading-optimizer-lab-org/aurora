#!/usr/bin/env python3
"""Qullamaggie phase 5 (EPs with a real earnings catalyst): fetch SEC 8-K Item 2.02
dates and XBRL revenue for the EP candidates, run the 16 trials, write the report.

    SEC_USER_AGENT="Name email@example.com" APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... \
        python scripts/run_qullamaggie_catalyst.py run --panel-dir outputs/stock_panel \
        --cache outputs/alpaca --sec-cache outputs/sec --output-dir outputs/qullamaggie_catalyst

SEC data stays in ``--sec-cache``. See docs/research/QULLAMAGGIE_CATALYST_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_catalyst as qc
from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc

PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")
FIRST, LAST = "2015-12-01", "2020-12-31"
CONCEPTS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
QUARTERS = [f"CY{y}Q{n}" for y in range(2014, 2021) for n in range(1, 5) if (y, n) <= (2020, 3)]


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Sec:
    """SEC EDGAR JSON with the declared user agent, at most 8 requests a second."""

    def __init__(self) -> None:
        ua = os.environ.get("SEC_USER_AGENT")
        if not ua:
            raise SystemExit("SEC_USER_AGENT is not set (the SEC requires a name and contact email)")
        self.headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
        self.calls = 0

    def get(self, url: str) -> dict | None:
        for attempt in range(8):
            time.sleep(0.13)
            self.calls += 1
            r = requests.get(url, headers=self.headers, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                raise SystemExit(f"SEC refused the request (403): check SEC_USER_AGENT. {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"SEC kept failing: {url}")


def _cached(path: Path, fetch):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def ticker_ciks(sec: Sec, cache: Path) -> dict[str, int]:
    raw = _cached(cache / "company_tickers.json", lambda: sec.get("https://www.sec.gov/files/company_tickers.json"))
    if not raw:
        raise SystemExit("could not download the SEC ticker list")
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in raw.values()}


def _item_202_dates(block: dict) -> list[str]:
    for key in ("form", "filingDate", "items"):
        if key not in block:
            raise SystemExit(f"unexpected SEC submissions format: missing '{key}'")
    return [d for f, d, it in zip(block["form"], block["filingDate"], block["items"])
            if f in ("8-K", "8-K/A") and "2.02" in str(it).split(",") and FIRST <= d <= LAST]


def earnings_dates(sec: Sec, cache: Path, cik: int) -> list[str] | None:
    def fetch():
        sub = sec.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if sub is None:
            return None
        filings = sub.get("filings")
        if not filings or "recent" not in filings:
            raise SystemExit("unexpected SEC submissions format: no filings.recent")
        dates = _item_202_dates(filings["recent"])
        for f in filings.get("files", []):
            if f.get("filingTo", "9999") >= FIRST and f.get("filingFrom", "0000") <= LAST:
                older = sec.get(f"https://data.sec.gov/submissions/{f['name']}")
                if older:
                    dates += _item_202_dates(older)
        return sorted(set(dates))
    return _cached(cache / "earnings" / f"{cik}.json", fetch)


def revenue_frames(sec: Sec, cache: Path) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for frame in QUARTERS:
        merged: dict[int, float] = {}
        for concept in CONCEPTS:
            def fetch(concept=concept, frame=frame):
                raw = sec.get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{frame}.json")
                if raw is None:
                    return {}
                if "data" not in raw:
                    raise SystemExit("unexpected SEC frames format: no data")
                return {str(r["cik"]): float(r["val"]) for r in raw["data"]}
            for k, v in _cached(cache / "frames" / f"{concept}_{frame}.json", fetch).items():
                merged.setdefault(int(k), v)
        out[frame] = merged
    return out


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


def _cells(r, p: str) -> str:
    return (f"{_fmt(r[f'{p}_sortino_monthly'], '{:.2f}')} | {_fmt(r[f'{p}_cagr'], '{:.1%}')} | "
            f"{_fmt(r[f'{p}_max_drawdown'], '{:.1%}')} | {_fmt(r[f'{p}_total'], '{:+.0%}')}")


def render(agg: dict, info: dict) -> str:
    df, spy = agg["df"], pd.Series(agg["spy"])
    lines = ["# Qullamaggie phase 5: episodic pivots with a real earnings catalyst (pre-registered, 16 trials)", "",
             f"{len(df)} of {agg['expected']} trials (2016-2020); deflated Sharpe over {agg['n_trials']:,} trials. "
             "Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly "
             "Sortino | CAGR | max drawdown | total return of the portfolio.", "",
             f"Coverage: {info['ep_candidates']:,} EP candidate gaps; {info['with_filings']:,} with SEC filings; "
             f"{info['earn']:,} on an Item 2.02 release; {info['with_growth']:,} with revenue growth; "
             f"{info['earn_growth25']:,} on a release with revenue +25% or more. SEC calls: {info.get('sec_calls', '-')}.",
             "", f"SPY: 2016-2018 {_cells(spy, 'p1')} · 2019-2020 {_cells(spy, 'p2')} · 2016-2020 {_cells(spy, 'all')}.",
             "", "## 1. All trials", "",
             "| trial | 2016-18 Sortino | CAGR | max DD | total | 2019-20 Sortino | CAGR | max DD | total | 2016-20 Sortino | "
             "CAGR | max DD | total | trades | win | PF | avg | DSR | passed |", "|" + "---|" * 19]
    for n, r in df.iterrows():
        lines.append(f"| {n} | {_cells(r, 'p1')} | {_cells(r, 'p2')} | {_cells(r, 'all')} | "
                     f"{_fmt(r['all_tl_trades'], '{:,.0f}')} | {_fmt(r['all_tl_win_rate'], '{:.0%}')} | "
                     f"{_fmt(r['all_tl_profit_factor'], '{:.2f}')} | {_fmt(r['all_tl_avg_return'], '{:+.2%}')} | "
                     f"{_fmt(r['deflated_sharpe'], '{:.2f}')} | {'YES' if r['passed'] else 'no'} |")
    lines += ["", "## 2. Pre-registered criteria on 2016-2020", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", ""]
    return "\n".join(lines) + "\n"


def report(rows: pd.DataFrame, info: dict, output_dir: Path) -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k in ("v1", "v2", "v3", "v4", "v5", "v6", "qullamaggie", "qullamaggie_intraday",
                        "qullamaggie_wind", "qullamaggie_stars", "qullamaggie_sizing") for x in prior[k].values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = qc.aggregate(rows, pool)
    output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(output_dir / "results.parquet")
    (output_dir / "summary.json").write_text(json.dumps({"passed": agg["passed"], "info": info, "spy": agg["spy"]},
                                                        indent=1, default=str), encoding="utf-8")
    text = render(agg, info)
    (output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if len(agg["df"]) == agg["expected"] else 1


def cmd_run(args) -> int:
    fetch = _script("run_qullamaggie_intraday")
    sec = Sec()
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = _script("run_qullamaggie").nasdaq_close(args.cache / "ixic.csv")
    ind = sc.indicators(panel, bench["gspc"], industry)
    cands = qi.candidates(panel, ind, q.context(panel, ind, nasdaq))
    need = qi.needed(cands)
    ep_symbols = sorted(cands["IEP_N0"].columns[cands["IEP_N0"].fillna(False).astype(bool).any()])
    del ind, cands
    api = fetch.Alpaca()
    alp_daily = fetch.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    fetch.fetch_minutes(api, args.cache, need)
    ciks = ticker_ciks(sec, args.sec_cache)
    cik = {s: ciks[s.upper()] for s in ep_symbols if s.upper() in ciks}
    earnings: dict[str, list[pd.Timestamp]] = {}
    for n, (s, c) in enumerate(sorted(cik.items())):
        dates = earnings_dates(sec, args.sec_cache, c)
        if dates is not None:
            earnings[s] = [pd.Timestamp(d) for d in dates]
        if n % 200 == 0:
            print(f"SEC filings: {n}/{len(cik)} companies, {sec.calls} calls", flush=True)
    revenue = revenue_frames(sec, args.sec_cache)
    print(f"SEC calls: {sec.calls}; {len(earnings)} of {len(ep_symbols)} EP symbols covered", flush=True)
    rows, info = qc.run(panel, bench["gspc"], bench["spy"], nasdaq, cash_index, industry,
                        fetch.minute_loader(args.cache), alp_daily, earnings, set(earnings), cik, revenue,
                        workers=args.workers)
    info["sec_calls"] = sec.calls
    df = pd.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output_dir / "rows.parquet", index=False)
    return report(df, info, args.output_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie_catalyst"))
    a.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
