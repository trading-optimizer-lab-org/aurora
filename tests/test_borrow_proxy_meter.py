"""The borrow proxy meter on a synthetic IB file and fake Alpaca assets."""
from __future__ import annotations

import importlib.util
from pathlib import Path

IB = """#BOF|2026.11.09|09:44:15
#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|
AAA|USD|A CORP|1|X|3.40|0.25|>10000000|F|
BBB|USD|B CORP|2|X|-80.00|85.50|200|F|
CCC|USD|C CORP|3|X|-200.00|210.00|0|F|
DDD|CAD|D CORP|4|X|1.00|0.25|5000|F|
#EOF|4
"""


def _script(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_proxy_meter_states_and_report() -> None:
    M = _script("borrow_proxy_meter", "borrow_proxy_meter_under_test")
    ib = M.ib_parse(IB)
    assert ib == {"AAA": (M.MANY, 0.25), "BBB": (200, 85.5), "CCC": (0, 210.0)}  # non-USD rows dropped
    flags = {"AAA": {"shortable": True, "easy_to_borrow": True}, "BBB": {"shortable": True, "easy_to_borrow": False}}
    cands = [{"symbol": s, "price": 2.0, "pct": p, "src": "today"} for s, p in
             (("AAA", 120.0), ("BBB", 120.0), ("CCC", 60.0), ("DDD", 60.0))]
    got = {r["symbol"]: r for r in M.measure(cands, ib, lambda s: flags.get(s, {}))}
    assert got["AAA"]["qty"] == 300  # about $500 at $2, in hundreds
    assert {s: r["ib"] for s, r in got.items()} == {"AAA": "enough", "BBB": "some", "CCC": "none", "DDD": "none"}
    assert got["BBB"]["al_short"] and not got["BBB"]["al_etb"] and got["DDD"]["al_error"]
    recs = [{"date": "2026-11-09", "slot": "close", **r} for r in got.values()]
    recs.append({**recs[0], "slot": "forced"})
    text = M.report(recs)
    assert "| close | up 100%+ | 2 | 50% | 50% | 0% | 42.9% | 100% | 50% | 0 |" in text
    assert "| close | up 50-100% | 2 | 0% | 0% | 100% | - | - | - | 2 |" in text
    assert "left out of the table: 1." in text
