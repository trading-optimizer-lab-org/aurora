"""The locate logger only reads, quotes and cancels: no accept, sell-back or order call can leave it; it stops when the
account's locate costs move; offers (and the Single Use sibling) are read from the history; tiers as v29's."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from test_v24 import _script

L = _script("tz_locate_logger", "tz_locate_logger_under_test")


class Resp:
    def __init__(self, body: dict | None, code: int = 200) -> None:
        self.status_code, self.text = code, json.dumps(body) if body is not None else ""
        self._b = body

    def json(self):
        return self._b


class Fake:
    """A TradeZero stand-in: one live account, SYM threshold (Pre-Borrow + Single Use offers), ETB for 'BIG'."""

    def __init__(self, cost_after_quote: float = 0.0) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.cost, self.bump = 0.0, cost_after_quote
        self.rows: list[dict] = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        path = url.replace(L.TZ_BASE, "")
        self.calls.append((method, path, json))
        if path == "/v1/api/accounts":
            return Resp({"accounts": [{"account": "TZP1", "accountType": "Paper", "accountStatus": "Active"},
                                      {"account": "TZ9", "accountType": "Margin", "accountStatus": "Active",
                                       "totalLocateCosts": self.cost}]})
        if "/is-easy-to-borrow/" in path:
            return Resp({"isEasyToBorrow": path.endswith("/BIG")})
        if path.endswith("/locates/quote"):
            q = json["quoteReqID"]
            self.rows += [{"quoteReqID": q, "symbol": json["symbol"], "locateStatus": 65, "locatePrice": 0.06,
                           "locateType": 3},
                          {"quoteReqID": q + ".SU", "symbol": json["symbol"], "locateStatus": 65, "locatePrice": 0.04,
                           "locateType": 4}]
            self.cost += self.bump
            return Resp({"locateQuoteSent": "true"})
        if path.endswith("/locates/history"):
            return Resp({"locateHistory": self.rows})
        if "/locates/cancel/" in path:
            qid = path.rsplit("/", 1)[1]
            for r in self.rows:
                if r["quoteReqID"] == qid:
                    r["locateStatus"] = 52
            return Resp({"locateCancelSent": "true"})
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def tz(monkeypatch):
    monkeypatch.setenv("TZ_API_KEY_ID", "k")
    monkeypatch.setenv("TZ_API_SECRET_KEY", "s")

    def make(bump: float = 0.0):
        f = Fake(bump)
        return L.TZ(session=f, sleep=lambda s: None), f
    return make


def _cands() -> pd.DataFrame:
    return pd.DataFrame([{"symbol": "SYM", "price": 3.0, "prev_close": 2.0, "gap": 1.5, "rise20": 1.2,
                          "threshold": True, "move": 0.5},
                         {"symbol": "BIG", "price": 15.0, "prev_close": 14.0, "gap": 15 / 14, "rise20": 1.1,
                          "threshold": False, "move": 0.07}])


def test_only_reads_quotes_and_cancels(tz, tmp_path) -> None:
    client, fake = tz()
    rows = L.run_quotes(client, _cands(), tmp_path / "q.csv")
    assert not any("accept" in p or "/sell" in p or "/order" in p for _, p, _ in fake.calls)
    q = [b for m, p, b in fake.calls if p.endswith("/quote")]
    assert len(q) == 1 and q[0]["account"] == "TZ9" and q[0]["quantity"] == 100  # the live account, BIG is ETB
    assert {r["quoteReqID"]: r["locateStatus"] for r in fake.rows} == {q[0]["quoteReqID"]: 52,
                                                                     q[0]["quoteReqID"] + ".SU": 52}
    assert rows[0]["locate_pct"] == pytest.approx(0.02) and rows[0]["su_pct"] == pytest.approx(0.04 / 3)
    assert rows[0]["tier"] == "HOT" and rows[1]["tier"] == "ETB" and rows[1]["status"] == "etb"
    df = pd.read_csv(tmp_path / "q.csv")
    assert list(df.columns) == L.COLS and len(df) == 2


def test_blocked_calls(tz) -> None:
    client, _ = tz()
    for m, p in (("POST", "/v1/api/accounts/locates/accept"), ("POST", "/v1/api/accounts/locates/sell"),
                 ("POST", "/v1/api/accounts/TZ9/order"), ("DELETE", "/v1/api/accounts/orders")):
        with pytest.raises(L.Blocked):
            client.call(m, p, {})


def test_stops_when_locate_costs_move(tz, tmp_path) -> None:
    client, _ = tz(bump=6.0)
    with pytest.raises(SystemExit, match="STOP"):
        L.run_quotes(client, _cands(), tmp_path / "q.csv")


def test_tiers_and_features() -> None:
    closes = np.array([4.0] * 25 + [2.0] + [1.0] * 19 + [3.0])
    pc, gap, rise = L.features(4.5, closes)
    assert pc == 3.0 and gap == pytest.approx(1.5) and rise == pytest.approx(3.0)
    assert L.tier(False, False, 1.1, 1.2) == "HTB" and L.tier(False, False, 1.1, 2.0) == "HOT"
    assert L.tier(True, True, 2.0, 3.0) == "ETB" and L.tier(False, True, np.nan, np.nan) == "HOT"


def test_summary_by_tier(tmp_path) -> None:
    rows = [{"ts_utc": "2026-10-26T13:10:00+00:00", "tier": "HOT", "locate_pct": x, "error": ""} for x in
            (0.01, 0.03, 0.05)] + [{"ts_utc": "2026-10-26T13:10:00+00:00", "tier": "HOT", "locate_pct": "",
                                    "error": "11"},
                                   {"ts_utc": "2026-10-27T13:10:00+00:00", "tier": "ETB", "locate_pct": "",
                                    "error": ""}]
    pd.DataFrame(rows).to_csv(tmp_path / "q.csv", index=False)
    s = L.summary(tmp_path / "q.csv").set_index("tier")
    assert s.loc["HOT", "offered"] == 3 and s.loc["HOT", "unavailable"] == 1
    assert s.loc["HOT", "median"] == pytest.approx(0.03) and s.loc["ETB", "rows"] == 1
