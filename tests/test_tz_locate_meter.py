"""The locate meter against a fake TradeZero: quotes are cancelled, never accepted, and outcomes are classified."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest


def _script(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _R:
    def __init__(self, body, code=200):
        self.body, self.status_code, self.content = body, code, b"x"

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeTZ:
    """ETB for AAA; BBB offered as Single Use only; CCC expired; DDD restricted; EEE no shares; FFF silent."""

    def __init__(self):
        self.calls, self.quotes, self.hist = [], {}, []

    def get(self, url, **kw):
        self.calls.append(("get", url))
        path = url.split("webapi.tradezero.com")[1]
        if path == "/v1/api/accounts":
            return _R({"accounts": [{"account": "TZP1"}, {"account": "2TZ9"}]})
        if path.startswith("/v1/api/account/"):
            return _R({"accountType": "Paper" if path.endswith("TZP1") else "Margin"})
        if "is-easy-to-borrow" in path:
            return _R({"isEasyToBorrow": path.endswith("/AAA")})
        if path.endswith("/locates/history"):
            return _R({"locateHistory": self.hist})
        raise AssertionError(path)

    def post(self, url, json=None, **kw):
        self.calls.append(("post", url))
        assert url.endswith("/locates/quote")
        q, s = json["quoteReqID"], json["symbol"]
        if s == "BBB":
            self.hist += [{"quoteReqID": q, "locateStatus": 54, "text": "11 No shares available."},
                          {"quoteReqID": q + ".SU", "locateStatus": 65, "locateType": 4, "locatePrice": 0.02}]
        elif s == "CCC":
            self.hist += [{"quoteReqID": q, "locateStatus": 67, "text": "Quote expired."}]
        elif s == "EEE":
            self.hist += [{"quoteReqID": q, "locateStatus": 54, "text": "11 No shares available."}]
        elif s == "FFF":
            pass
        else:
            self.hist += [{"quoteReqID": q, "locateStatus": 56, "text": "R06: This symbol is restricted"}]
        return _R({"locateQuoteSent": "true"})

    def delete(self, url, **kw):
        self.calls.append(("delete", url))
        q = url.rsplit("/", 1)[1]
        for r in self.hist:
            if r["quoteReqID"] in (q, q + ".SU") and r["locateStatus"] in (54, 65):
                r["locateStatus"] = 52
        return _R({"locateCancelSent": "true"})


def test_meter_measures_and_cancels(tmp_path) -> None:
    M = _script("tz_locate_meter", "tz_locate_meter_under_test")
    fake = FakeTZ()
    tz = M.TZ("k", "s", http=fake, sleep=lambda s: None)
    acct = M.live_account(tz)
    assert acct == "2TZ9"
    got = {s: M.measure(tz, acct, s, 100) for s in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")}
    assert {s: g["outcome"] for s, g in got.items()} == {
        "AAA": "easy to borrow", "BBB": "offered", "CCC": "expired", "DDD": "rejected",
        "EEE": "no shares", "FFF": "no answer"}
    assert not any("accept" in u for _, u in fake.calls)
    dels = [u for m, u in fake.calls if m == "delete"]
    # only live quotes need a cancel, and history confirms each one
    assert all(any(u.endswith(got[s]["qid"]) for u in dels) for s in ("BBB", "EEE")) and len(dels) == 2
    assert got["BBB"]["cancel"] == got["EEE"]["cancel"] == "confirmed" and "cancel" not in got["CCC"]
    M.check_nothing_filled(tz, acct, {g["qid"] for g in got.values() if g.get("qid")})
    fake.hist.append({"quoteReqID": got["CCC"]["qid"], "locateStatus": 50})
    with pytest.raises(SystemExit):
        M.check_nothing_filled(tz, acct, {got["CCC"]["qid"]})
    with pytest.raises(AssertionError):
        tz.post("/v1/api/accounts/locates/accept", {})


def test_meter_candidates_and_report() -> None:
    M = _script("tz_locate_meter", "tz_locate_meter_under_test2")

    def get(url, params):
        if url.endswith("/movers"):
            return {"last_updated": "2026-11-06T20:10:00Z", "gainers": [
                {"symbol": "AAA", "price": 3.0, "percent_change": 120.0},
                {"symbol": "BBBBW", "price": 1.0, "percent_change": 90.0},
                {"symbol": "CCC", "price": 0.3, "percent_change": 60.0},
                {"symbol": "DDD", "price": 5.0, "percent_change": 25.0}]}
        assert params["symbols"] == "EEE"
        return {"EEE": {"latestTrade": {"p": 2.5}}}

    c = M.candidates(get, "2026-11-06", ["AAA", "EEE"])
    assert [(x["symbol"], x["src"]) for x in c] == [("AAA", "today"), ("DDD", "today"), ("EEE", "prior")]
    assert M.candidates(get, "2026-11-07", []) is None
    assert M.quantity(3.0) == 200 and M.quantity(50.0) == 100
    assert M.slot_of(datetime(2026, 11, 6, 15, 20)) == "close" and M.slot_of(datetime(2026, 11, 6, 12, 0)) is None
    recs: list[dict] = [{"date": "2026-11-06", "slot": "close", "src": "today", "pct": 120.0, "price": 2.0, "outcome": "offered",
             "rows": [{"locateStatus": 65, "locatePrice": 0.04}]},
            {"date": "2026-11-06", "slot": "close", "src": "prior", "pct": None, "price": 2.0, "outcome": "no shares",
             "rows": []}]
    recs = [{**r, "notional": M.NOTIONAL} for r in recs] + [{**recs[0], "outcome": "rejected"}]  # old $2,000 record
    text = M.report(recs)
    assert "| close | up 100%+ | 1 | 0% | 100% | 0% | 0% | 0% | 0% | 0% | 2.00% |" in text
    assert "| close | prior day gainer | 1 | 0% | 0% | 100% |" in text
    assert "Quotes at another size, left out: 1." in text
