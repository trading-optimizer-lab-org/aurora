import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tz_paper_bot as B  # noqa: E402

SESS = [f"2026-11-{d:02d}" for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23)]


def bars(closes, low_last=None, vol=1_000_000):
    out = [{"t": f"{SESS[i]}T05:00:00Z", "c": c, "l": c * 0.95, "v": vol} for i, c in enumerate(closes)]
    if low_last is not None:
        out[-1]["l"] = low_last
    return out


def test_runup_fires_at_four_times_the_five_day_low():
    b = bars([1.0, 1.1, 1.2, 1.0, 1.3, 4.0])
    assert B.runup(b, SESS[5]) == 3.0
    assert B.runup(bars([1.0, 1.1, 1.2, 1.0, 1.3, 3.9]), SESS[5]) is None


def test_runup_rules_out_floor_band_volume_ssr_and_stale_day():
    assert B.runup(bars([0.5, 0.6, 0.5, 0.55, 0.5, 2.4]), SESS[5]) is None  # under $2.50
    assert B.runup(bars([5, 5, 5, 5, 5, 21.0]), SESS[5]) is None  # over $20
    assert B.runup(bars([1.0, 1.1, 1.2, 1.0, 1.3, 4.0], vol=1000), SESS[5]) is None  # dollar volume
    assert B.runup(bars([1.0, 1.1, 1.2, 1.0, 1.3, 4.0], low_last=1.0), SESS[5]) is None  # SSR
    assert B.runup(bars([1.0, 1.1, 1.2, 1.0, 1.3, 4.0]), SESS[6]) is None  # no bar for that day


def test_nightshort():
    assert abs(B.nightshort(2.0, 4.0, 4.4, 3.0, 3.2, 2e6) - 1.0) < 1e-9
    assert B.nightshort(2.0, 2.5, 2.6, 2.0, 2.1, 2e6) is None  # gap 25%
    assert B.nightshort(2.0, 4.0, 4.4, 3.0, 3.7, 2e6) is None  # not 10% under the open
    assert B.nightshort(2.0, 4.0, 4.4, 2.0, 3.6, 2e6) is None  # top of the range
    assert B.nightshort(2.0, 4.0, 4.4, 2.0, 2.2, 2e6) is None  # under $2.50
    assert B.nightshort(2.0, 4.0, 4.4, 3.0, 3.2, 5e5) is None  # dollar volume


def test_shares_cap_at_one_percent_of_dollar_volume():
    assert B.SIZE == {"DS1": 0.20, "RU": 0.25, "NS": 0.80}
    assert B.shares(0.6, 5000, 1e7, 3.0) == 1000
    assert B.shares(0.6, 5000, 1e5, 3.0) == 333


def test_recent_blocks_twenty_sessions():
    st = {"fired": {"DS1": {"X": SESS[0]}}}
    assert B.recent(st, "DS1", "X", SESS, SESS[15])
    assert not B.recent(st, "DS1", "Y", SESS, SESS[15])


class FakeBroker:
    def __init__(self):
        self.sent, self.book, self.cancelled = [], {}, []

    def order(self, sym, side, oc, qty, kind, tif, limit=None):
        cid = f"c{len(self.sent)}"
        self.sent.append((sym, side, oc, qty, kind, tif, limit))
        self.book[cid] = {"clientOrderId": cid, "orderStatus": "New", "executed": 0, "priceAvg": 0}
        return {"cid": cid, "status": "PendingNew", "text": None}

    def orders(self):
        return self.book

    def cancel(self, cid):
        self.cancelled.append(cid)

    def shorts(self):
        return getattr(self, "have", {})


empty = B.empty


def test_entries_rank_pool_and_skip_without_locate(monkeypatch):
    st, br = empty(), FakeBroker()
    calls = []

    def fake_locate(live, acct, sym, qty):
        calls.append(sym)
        return (sym != "BAD"), 0.02 * qty, {"outcome": "offered" if sym != "BAD" else "no shares"}

    monkeypatch.setattr(B, "locate", fake_locate)
    cands = [(5.0, 0, "DS1", "AAA", 4.0, 1e8, 4.8), (5.0, 1, "RU", "AAA", 4.0, 1e8, 4.8),
             (9.0, 0, "DS1", "BAD", 4.0, 1e8, 4.8)] + [(1.0 + i, 0, "DS1", f"S{i}", 4.0, 1e8, 4.8) for i in range(6)]
    n = B.place_entries(st, br, object(), "acct", cands, SESS[5], 5000.0, {}, "Limit")
    assert calls[0] == "BAD" and calls.count("AAA") == 1  # ranked first, and one quote a symbol
    assert n == 4 and len(calls) == B.QUOTES_PER_RUN  # the quote budget binds before the 5 names
    assert [x[0] for x in br.sent] == ["S5", "AAA", "S4", "S3"]
    assert br.sent[1] == ("AAA", "Sell", "Open", 208, "Limit", "Day", 4.8)
    assert st["fired"]["DS1"]["AAA"] == SESS[5] and "AAA" not in st["fired"]["RU"]


def test_fill_then_time_exit_books_pnl_and_locate():
    st, br = empty(), FakeBroker()
    st["pending"].append({"cid": "c0", "sym": "AAA", "member": "NS", "what": "entry", "qty": 100,
                          "day": SESS[5], "loc": 3.0})
    br.book["c0"] = {"clientOrderId": "c0", "orderStatus": "PartiallyFilled", "executed": 50, "priceAvg": 4.0}
    B.reconcile(st, br, SESS, SESS[5])
    br.book["c0"].update(orderStatus="Filled", executed=100)
    B.reconcile(st, br, SESS, SESS[5])
    assert st["open"] == [{"sym": "AAA", "member": "NS", "qty": 100, "entry": 4.0, "day": SESS[5], "due": SESS[8]}]
    assert abs(st["locate_cost"] - 3.0) < 1e-9 and st["pending"] == []


def test_exit_fill_realizes_short_pnl():
    st, br = empty(), FakeBroker()
    st["open"].append({"sym": "AAA", "member": "DS1", "qty": 100, "entry": 10.0, "day": SESS[0], "due": SESS[9]})
    st["pending"].append({"cid": "x", "sym": "AAA", "member": "DS1", "what": "time", "qty": 100, "day": SESS[9]})
    br.book["x"] = {"clientOrderId": "x", "orderStatus": "Filled", "executed": 100, "priceAvg": 7.0}
    B.reconcile(st, br, SESS, SESS[9])
    assert st["open"] == [] and st["realized"] == 300.0
    assert B.equity(st, {}) == 5300.0


def test_report_hides_dollars_by_default():
    st = empty()
    st["realized"] = 123.0
    assert "$" not in B.report(st) and "$123" in B.report(st, money=True)


def test_sync_books_unseen_cover_and_adopts_lost_entry():
    st, br = empty(), FakeBroker()
    st["open"].append({"sym": "AAA", "member": "DS1", "qty": 100, "entry": 10.0, "day": SESS[0], "due": SESS[9]})
    st["pending"].append({"cid": "gone", "sym": "NNN", "member": "NS", "what": "entry", "qty": 200,
                          "day": SESS[3], "loc": 4.0})
    B.reconcile(st, br, SESS, SESS[4])  # yesterday's entry is no longer in today's order book
    assert st["pending"] == [] and st["lost"][0]["sym"] == "NNN"
    br.have = {"NNN": {"qty": 100, "px": 3.0, "day": SESS[3]}}
    B.sync(st, br, SESS, SESS[4], {"AAA": 8.0})
    assert st["realized"] == 200.0  # AAA covered unseen at the last price
    assert st["open"] == [{"sym": "NNN", "member": "NS", "qty": 100, "entry": 3.0, "day": SESS[3], "due": SESS[6]}]
    assert abs(st["locate_cost"] - 2.0) < 1e-9


def test_sync_leaves_symbols_with_working_orders():
    st, br = empty(), FakeBroker()
    st["open"].append({"sym": "AAA", "member": "NS", "qty": 100, "entry": 4.0, "day": SESS[0], "due": SESS[3]})
    st["pending"].append({"cid": "t", "sym": "AAA", "member": "NS", "what": "target", "qty": 100, "day": SESS[1]})
    B.sync(st, br, SESS, SESS[1], {})
    assert st["open"][0]["qty"] == 100 and st["realized"] == 0.0


def test_no_order_after_the_deadline(monkeypatch):
    st, br = empty(), FakeBroker()
    monkeypatch.setattr(B, "locate", lambda live, acct, sym, qty: (True, 0.0, {"outcome": "offered"}))
    monkeypatch.setattr(B, "late", lambda d: d == B.LAST_MARKET)
    n = B.place_entries(st, br, object(), "acct", [(1.0, 2, "NS", "AAA", 3.0, 1e8, None)], SESS[5], 5000.0, {},
                        "Market", deadline=B.LAST_MARKET)
    assert n == 0 and br.sent == [] and st["events"][-1]["kind"] == "late"
    assert "AAA" not in st["fired"]["NS"]  # a skipped entry does not block the symbol for 20 sessions


def test_rejected_order_hands_its_slot_to_the_next_name(monkeypatch):
    class Rejecting(FakeBroker):
        def order(self, sym, *a, **k):
            o = super().order(sym, *a, **k)
            return {**o, "status": "Rejected", "text": "no"} if sym == "TOP" else o

    st, br = empty(), Rejecting()
    monkeypatch.setattr(B, "locate", lambda live, acct, sym, qty: (True, 0.0, {"outcome": "offered"}))
    monkeypatch.setattr(B, "room", lambda *a: (1, 1e9))
    cands = [(9.0, 0, "DS1", "TOP", 4.0, 1e8, 4.8), (5.0, 0, "DS1", "NXT", 4.0, 1e8, 4.8),
             (4.0, 0, "DS1", "LST", 4.0, 1e8, 4.8)]
    assert B.place_entries(st, br, object(), "acct", cands, SESS[5], 5000.0, {}, "Limit") == 1
    assert [x[0] for x in br.sent] == ["TOP", "NXT"] and [p["sym"] for p in st["pending"]] == ["NXT"]


def test_sync_extra_shares_take_the_broker_basis_and_lost_locate():
    st, br = empty(), FakeBroker()
    st["open"].append({"sym": "AAA", "member": "DS1", "qty": 50, "entry": 10.0, "day": SESS[3], "due": SESS[12]})
    st["lost"].append({"cid": "gone", "sym": "AAA", "member": "DS1", "what": "entry", "qty": 100, "day": SESS[3],
                       "loc": 6.0})
    br.have = {"AAA": {"qty": 100, "px": 9.5, "day": SESS[3]}}
    B.sync(st, br, SESS, SESS[4], {})
    assert st["open"][0]["qty"] == 100 and st["open"][0]["entry"] == 9.5
    assert abs(st["locate_cost"] - 3.0) < 1e-9 and st["lost"] == []
