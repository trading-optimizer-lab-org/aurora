"""Read-only check that the TradeZero paper keys work: finds the paper account and reads its positions and orders.

Prints only yes/no facts and counts: no account id, no balance. It places, cancels and accepts nothing.
"""
from __future__ import annotations

import os
import sys

import requests

BASE = "https://webapi.tradezero.com"


def main() -> int:
    h = {"Accept": "application/json", "TZ-API-KEY-ID": os.environ["TZ_PAPER_KEY_ID"],
         "TZ-API-SECRET-KEY": os.environ["TZ_PAPER_SECRET_KEY"]}

    def get(path: str) -> requests.Response:
        return requests.get(BASE + path, headers=h, timeout=15)

    r = get("/v1/api/accounts")
    print(f"accounts call: HTTP {r.status_code}")
    if not r.ok:
        return 1
    accts = r.json().get("accounts", [])
    kinds = []
    for a in accts:
        d = get(f"/v1/api/account/{a['account']}")
        kinds.append(d.json().get("accountType") if d.ok else f"HTTP {d.status_code}")
    print(f"accounts visible with the paper keys: {len(accts)}, types: {kinds}")
    paper = [a["account"] for a, k in zip(accts, kinds) if k == "Paper"]
    if not paper:
        print("no paper account visible")
        return 1
    for name, path in (("positions", f"/v1/api/accounts/{paper[0]}/positions"),
                       ("orders", f"/v1/api/accounts/{paper[0]}/orders")):
        r = get(path)
        n = len(r.json().get(name, [])) if r.ok else None
        print(f"{name} call: HTTP {r.status_code}, items: {n}")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tz_locate_meter as M
    import tz_paper_bot as B
    br = B.Broker(M.TZ(os.environ["TZ_PAPER_KEY_ID"], os.environ["TZ_PAPER_SECRET_KEY"]))
    print(f"the bot's own position reader: {len(br.shorts())} open shorts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
