#!/usr/bin/env python3
"""Earnings options study: straddles, calls/puts and iron flies around earnings releases.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... SEC_USER_AGENT="Name email" \
        python scripts/run_earnings_options.py probe --out outputs/earnings_options

See docs/research/EARNINGS_OPTIONS_PREREGISTRATION.md. Only reports and strategy returns are written to the
artifact; raw market data stays in the cache folder.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests

DATA = "https://data.alpaca.markets"
TRADE = "https://paper-api.alpaca.markets"


class Http:
    """GET with retries; Alpaca at most ~3 requests a second, the SEC at most 8."""

    def __init__(self, headers: dict, pause: float) -> None:
        self.s = requests.Session()
        self.s.headers.update(headers)
        self.pause = pause
        self.calls = 0

    def get(self, url: str, params: dict | None = None) -> dict | None:
        for attempt in range(8):
            time.sleep(self.pause)
            self.calls += 1
            try:
                r = self.s.get(url, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                raise SystemExit(f"refused (403): {url.split('?')[0]}")
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"kept failing: {url.split('?')[0]}")


def alpaca() -> Http:
    key, sec = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not sec:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    return Http({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}, 0.32)


def sec_http() -> Http:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise SystemExit("SEC_USER_AGENT is not set")
    return Http({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, 0.13)


def cmd_probe(args) -> int:
    """Data-format checks only (no strategy result): expired contracts, option bars, SEC acceptance times."""
    a, s = alpaca(), sec_http()
    out: dict = {}
    c = a.get(f"{TRADE}/v2/options/contracts", {"underlying_symbols": "AAPL", "status": "inactive",
                                                 "expiration_date_gte": "2024-02-02", "expiration_date_lte": "2024-02-09",
                                                 "strike_price_gte": "180", "strike_price_lte": "190", "limit": 50})
    rows = (c or {}).get("option_contracts", [])
    out["inactive_contracts"] = [(r["symbol"], r["expiration_date"], r["strike_price"], r["type"]) for r in rows][:12]
    syms = [r["symbol"] for r in rows if r["expiration_date"] == "2024-02-02" and float(r["strike_price"]) in (185.0, 187.5)]
    b = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": ",".join(syms[:4]), "timeframe": "15Min",
                                               "start": "2024-02-01T19:00:00Z", "end": "2024-02-02T15:30:00Z",
                                               "limit": 10000})
    bars = (b or {}).get("bars", {})
    out["bars"] = {k: [(x["t"], x["vw"], x["n"]) for x in v] for k, v in bars.items()}
    d = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": syms[0] if syms else "", "timeframe": "1Day",
                                               "start": "2024-01-02", "end": "2024-02-02"})
    out["first_daily"] = [(x["t"], x["c"], x["v"]) for x in (d or {}).get("bars", {}).get(syms[0] if syms else "", [])][:3]
    e = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": "AAPL240119C00185000", "timeframe": "1Day",
                                               "start": "2023-10-01", "end": "2024-01-19"})
    out["pre_feb_2024_daily"] = [(x["t"], x["c"]) for x in (e or {}).get("bars", {}).get("AAPL240119C00185000", [])][:3]
    sub = s.get("https://data.sec.gov/submissions/CIK0000320193.json") or {}
    rec = sub.get("filings", {}).get("recent", {})
    out["sec_keys"] = sorted(rec)
    out["aapl_202"] = [(f, d, t, it) for f, d, t, it in zip(rec.get("form", []), rec.get("filingDate", []),
                                                           rec.get("acceptanceDateTime", []), rec.get("items", []))
                       if f == "8-K" and "2.02" in str(it)][:8]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "probe.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # prices stay out of the public log: counts, timestamps and SEC filing times only
    print(json.dumps({"inactive_contracts": len(rows), "contract_example": out["inactive_contracts"][:2],
                      "bars": {k: [(t, n) for t, _, n in v] for k, v in out["bars"].items()},
                      "first_daily_dates": [t for t, _, _ in out["first_daily"]],
                      "pre_feb_2024_dates": [t for t, _ in out["pre_feb_2024_daily"]],
                      "sec_keys": out["sec_keys"], "aapl_202": out["aapl_202"]}, indent=1))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("probe")
    q.add_argument("--out", type=Path, default=Path("outputs/earnings_options"))
    q.set_defaults(fn=cmd_probe)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
