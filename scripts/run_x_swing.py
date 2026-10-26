#!/usr/bin/env python3
"""Run the pre-registered X traders momentum swing study.

See docs/research/X_SWING_PREREGISTRATION.md. Reads the local ``free_us_daily`` catalog through the SEPA study's
loaders; every series is cut before 2021-01-01 as soon as it is read.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import stocks_sepa as ss
from aurora.research import x_swing as xs


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEPA = _script("run_stocks_sepa")


def render(study: dict, report: dict) -> str:
    res = study["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    lines = ["# US stocks, momentum swing rules from X traders (pre-registered)", "",
             "Locked period from 2021-01-01 never read. Candidates are bias-adjusted (see the SEPA "
             "pre-registration); monthly metrics on excess returns over T-bills.", "",
             "Survivorship bias, local minus French top momentum decile, per month: "
             + ", ".join(f"{p} {b:.2%}" for p, b in study["bias_monthly"].items()), ""]
    for period in ("train", "validation"):
        lines += [f"## {period.capitalize()}", "",
                  "| strategy | " + " | ".join(k for k, _ in keys) + " | trades a year | win rate |",
                  "|" + "---|" * (len(keys) + 3)]
        for n, r in res.items():
            tr = r.get(f"{period}_trades")
            tail = f" | {tr['trades_per_year']:.0f} | {tr['win_rate']:.0%} |" if tr else " | - | - |"
            lines.append(f"| {n} | " + " | ".join(f.format(r[period][k]) for k, f in keys) + tail)
            if f"{period}_unadjusted" in r:
                u = r[f"{period}_unadjusted"]
                lines.append(f"| {n} (unadjusted) | " + " | ".join(f.format(u[k]) for k, f in keys) + " | | |")
        lines.append("")
    lines += ["## Pre-registered criteria (validation 2011-2020, bias-adjusted)", ""]
    for n in xs.CANDIDATES:
        r = res[n]
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{n}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}; "
                     f"average invested {r['invested_mean']:.0%}")
    lines += ["", "## Industry filter A1, yearly return with minus without (unadjusted, descriptive)", "",
              "| year | " + " | ".join(n for n in xs.CANDIDATES if not n.endswith("_ind")) + " |",
              "|" + "---|" * (1 + len(xs.CANDIDATES) // 2)]
    yr = study["yearly"]
    base_names = [n for n in xs.CANDIDATES if not n.endswith("_ind")]
    for y in sorted(yr[base_names[0]]):
        lines.append(f"| {y} | " + " | ".join(f"{yr[n + '_ind'].get(y, 0) - yr[n].get(y, 0):+.1%}"
                                              for n in base_names) + " |")
    lines += ["", "## Data", "", "```json", json.dumps(report, indent=2), "```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices-dir", type=Path, default=SEPA.DEFAULT_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/x_swing"))
    args = parser.parse_args()
    spy = SEPA.benchmark(args.prices_dir, "SPY")
    gspc = SEPA.benchmark(args.prices_dir, "GSPC")
    calendar = spy.loc[ss.WARMUP_START:].index
    panel, symbols = SEPA.build_panel(args.prices_dir, calendar)
    meta = pd.read_parquet(args.prices_dir / "metadata" / "company_metadata.parquet",
                           columns=["symbol", "exchange", "industry"])
    nyse = pd.Index(meta.loc[meta["exchange"].eq("NYQ"), "symbol"])
    industry = meta.drop_duplicates("symbol").set_index("symbol")["industry"].reindex(symbols)
    cash_report: dict = {}
    raw_cash = SEPA._script("run_multiasset_baselines").tbill_index(cash_report)
    cash_index = raw_cash.loc[raw_cash.index < ss.LOCKED_START]
    report = {"symbols": len(symbols), "with_industry": int(industry.notna().sum()),
              "industries": int(industry.nunique()), "calendar": [str(calendar[0].date()), str(calendar[-1].date())],
              "cash": cash_report}
    study = xs.run_study(panel, industry, gspc, spy, cash_index, SEPA.local_hi_prior(panel, nyse),
                         SEPA.french_hi_prior())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(study["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    (args.output_dir / "results.json").write_text(
        json.dumps({"data": report, "bias_monthly": study["bias_monthly"], "results": study["results"],
                    "yearly": study["yearly"]}, indent=2, default=str), encoding="utf-8")
    text = render(study, report)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
