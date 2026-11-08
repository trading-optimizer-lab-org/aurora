"""Borrow proxy meter: free public borrow data on the stocks the book would short, while TradeZero keys are pending.

Same windows and candidates as tz_locate_meter.py (Alpaca's top gainers and the prior session's). For each one it
records Interactive Brokers' public shortable file (shares available and annual fee, refreshed every few minutes,
no account needed) and Alpaca's shortable and easy-to-borrow flags. Other brokers' inventory is not TradeZero's,
so this is a proxy for how often hot stocks can be borrowed at all. Records stay in the Actions cache.

  run     measure now (skips outside the windows unless --force)
  report  the aggregates of the stored records
"""
from __future__ import annotations

import argparse
import ftplib  # nosec B402: IB serves this public file over plain FTP only (no TLS), no secret is sent
import io
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tz_locate_meter as T  # noqa: E402

IB_HOST, IB_USER, IB_FILE = "ftp2.interactivebrokers.com", "shortstock", "usa.txt"
ALPACA = ("https://paper-api.alpaca.markets", "https://api.alpaca.markets")
MANY = 10_000_001  # IB writes ">10000000"


def ib_fetch() -> str:
    buf = io.BytesIO()
    with ftplib.FTP(IB_HOST, timeout=60) as f:  # nosec B321: anonymous read of a public file
        f.login(IB_USER, "")
        f.retrbinary(f"RETR {IB_FILE}", buf.write)
    return buf.getvalue().decode("utf-8", "replace")


def ib_parse(text: str) -> dict[str, tuple[int, float]]:
    """Symbol -> (shares available, annual fee rate in %)."""
    out = {}
    for line in text.splitlines():
        p = line.split("|")
        if line.startswith("#") or len(p) < 8 or p[1] != "USD":
            continue
        a = p[7].strip()
        try:
            out[p[0]] = (MANY if a.startswith(">") else int(a), float(p[6]))
        except ValueError:
            continue
    return out


def ib_state(ib: dict, sym: str, qty: int) -> dict:
    if sym not in ib:
        return {"ib": "none", "ib_avail": 0, "ib_fee": None}
    avail, fee = ib[sym]
    return {"ib": "enough" if avail >= qty else "some" if avail > 0 else "none", "ib_avail": avail, "ib_fee": fee}


def alpaca_asset(get, sym: str) -> dict:
    a = get(sym)  # {} when the lookup failed
    return {"al_short": bool(a.get("shortable")), "al_etb": bool(a.get("easy_to_borrow")), "ok": bool(a)}


def _alpaca_asset_get():
    h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
    base = next((b for b in ALPACA if requests.get(f"{b}/v2/account", headers=h, timeout=15).ok), ALPACA[0])

    def get(sym: str) -> dict:
        r = requests.get(f"{base}/v2/assets/{sym}", headers=h, timeout=15)
        return r.json() if r.ok else {}
    return get


def report(recs: list[dict]) -> str:
    L = ["# Borrow proxy meter (Interactive Brokers public file, Alpaca flags)", "",
         f"{len({r['date'] for r in recs})} sessions, {len(recs)} stocks. Needed: about ${T.NOTIONAL:,.0f} of stock, "
         "at least 100 shares. IB fee: annual borrow rate.", "",
         "| window | group | stocks | IB enough | IB some | IB none | IB median fee | Alpaca shortable | "
         "Alpaca easy | Alpaca unknown |", "|---|---|---|---|---|---|---|---|---|---|"]
    for slot in T.WINDOWS:
        for name, _ in T.BUCKETS:
            g = [r for r in recs if r["slot"] == slot and T.bucket(r) == name]
            if not g:
                continue
            n = len(g)
            fees = [r["ib_fee"] for r in g if r["ib"] != "none" and r["ib_fee"] is not None]
            med = f"{statistics.median(fees):.1f}%" if fees else "-"
            ok = [r for r in g if not r.get("al_error")]
            al = (" | ".join(f"{sum(r[k] for r in ok) / len(ok):.0%}" for k in ("al_short", "al_etb")) if ok
                  else "- | -")
            L.append(f"| {slot} | {name} | {n} | " + " | ".join(f"{sum(r['ib'] == k for r in g) / n:.0%}"
                                                             for k in ("enough", "some", "none"))
                     + f" | {med} | {al} | {n - len(ok)} |")
    forced = sum(r["slot"] not in T.WINDOWS for r in recs)
    L += ["", f"Forced samples outside the windows, left out of the table: {forced}."]
    return "\n".join(L) + "\n"


def measure(cands: list[dict], ib: dict, asset) -> list[dict]:
    out = []
    for c in cands:
        qty = T.quantity(c["price"])
        try:
            al = alpaca_asset(asset, c["symbol"])
            al_ok = al.pop("ok")
        except requests.RequestException:
            al_ok = False
        if not al_ok:
            al = {"al_short": False, "al_etb": False, "al_error": True}
        out.append({**c, "qty": qty, **ib_state(ib, c["symbol"], qty), **al})
    return out


def cmd_run(args) -> int:
    now = datetime.now(T.NY)
    slot = T.slot_of(now) or ("forced" if args.force else None)
    if slot is None or now.weekday() >= 5:
        print(f"outside the measuring windows ({now:%a %H:%M} New York): nothing to do", flush=True)
        return 0
    if not os.environ.get("APCA_API_KEY_ID") or not os.environ.get("APCA_API_SECRET_KEY"):
        print("Alpaca keys are not set: nothing to do", flush=True)
        return 0
    today = f"{now:%Y-%m-%d}"
    recs = T.load(args.store)
    if any(r["date"] == today and r["slot"] == slot for r in recs) and not args.force:
        print(f"{today} {slot} already measured", flush=True)
        return 0
    days = sorted({r["date"] for r in recs if r["date"] < today})
    prior = [r["symbol"] for r in recs if days and r["date"] == days[-1] and r["src"] == "today"]
    cands = T.candidates(T._alpaca_get, today, prior)
    if cands is None:
        print("the market screener is not on today's session (market closed): nothing to do", flush=True)
        return 0
    stamp = {"date": today, "slot": slot, "time": f"{datetime.now(T.NY):%H:%M:%S}"}
    new = [{**stamp, **r} for r in measure(cands, ib_parse(ib_fetch()), _alpaca_asset_get())]
    args.store.parent.mkdir(parents=True, exist_ok=True)
    with args.store.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in new)
    (args.store.parent / "changed").write_text(today, encoding="utf-8")
    args.report.write_text(report(recs + new), encoding="utf-8")
    print(f"{today} {slot}: {len(new)} stocks measured", flush=True)
    return 0


def cmd_report(args) -> int:
    text = report(T.load(args.store))
    args.report.write_text(text, encoding="utf-8")
    print(text, flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "report"))
    ap.add_argument("--store", type=Path, default=Path("outputs/tzloc/proxy.jsonl"))
    ap.add_argument("--report", type=Path, default=Path("outputs/tzloc/PROXY.md"))
    ap.add_argument("--force", action="store_true", help="measure now even outside the windows")
    args = ap.parse_args()
    return {"run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
