"""The borrow logger against fakes: what it records, that it never accepts a locate, and its report."""
from __future__ import annotations

import gzip
import importlib.util
import json
from argparse import Namespace
from datetime import datetime
from pathlib import Path


def _script(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _R:
    def __init__(self, body):
        self.body, self.status_code, self.content = body, 200, b"x"

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


class FakeTZ:
    """AAA easy to borrow; BBB regular locate; CCC with Single Use only; DDD busy (meter's quote)."""

    def __init__(self):
        self.calls, self.hist = [], []

    def get(self, url, **kw):
        self.calls.append(("get", url))
        path = url.split("webapi.tradezero.com")[1]
        if path == "/v1/api/accounts":
            return _R({"accounts": [{"account": "2TZ9"}]})
        if path.startswith("/v1/api/account/"):
            return _R({"accountType": "Margin", "bp": 585.0})
        if "is-easy-to-borrow" in path:
            return _R({"isEasyToBorrow": path.endswith("/AAA")})
        if path.endswith("/locates/history"):
            return _R({"locateHistory": self.hist})
        if path.endswith("/pnl"):
            return _R({"availableCash": 585.0, "pnl": []})
        if path.endswith("/positions"):
            return _R({"positions": []})
        if path.endswith("/orders"):
            return _R({"orders": []})
        if path.endswith("/locates/inventory"):
            return _R({"locateInventory": []})
        if "/cash-transactions/" in path:
            return _R({"cashTransactions": [{"type": "Deposit"}]})
        raise AssertionError(path)

    def post(self, url, json=None, **kw):
        self.calls.append(("post", url))
        assert url.endswith("/locates/quote")
        q, s = json["quoteReqID"], json["symbol"]
        if s == "BBB":
            self.hist += [{"quoteReqID": q, "locateStatus": 65, "locateType": 1, "locatePrice": 0.05}]
        elif s == "CCC":
            self.hist += [{"quoteReqID": q, "locateStatus": 54, "locateType": 3, "text": "11 No shares available."},
                          {"quoteReqID": q + ".SU", "locateStatus": 65, "locateType": 4, "locatePrice": 0.02}]
        else:
            self.hist += [{"quoteReqID": q, "locateStatus": 56, "text": "14 Locate is already pending"}]
        return _R({"locateQuoteSent": "true"})

    def delete(self, url, **kw):
        self.calls.append(("delete", url))
        q = url.rsplit("/", 1)[1]
        for r in self.hist:
            if r["quoteReqID"] in (q, q + ".SU") and r["locateStatus"] in (54, 65):
                r["locateStatus"] = 52
        return _R({})


def test_logger_snap_and_report(tmp_path, monkeypatch) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test")
    fake = FakeTZ()
    real_tz = L.T.TZ
    monkeypatch.setattr(L.T, "TZ", lambda k, s: real_tz(k, s, http=fake, sleep=lambda x: None))
    today = f"{datetime.now(L.T.NY):%Y-%m-%d}"

    def alpaca(url, params):
        if url.endswith("/movers"):
            return {"last_updated": today + "T15:00:00Z", "gainers": [
                {"symbol": s, "price": 2.0, "percent_change": p} for s, p in
                (("AAA", 150.0), ("BBB", 120.0), ("CCC", 60.0), ("DDD", 30.0))]}
        return {"snapshots": params["symbols"]}

    monkeypatch.setattr(L.T, "_alpaca_get", alpaca)
    monkeypatch.setattr(L.P, "ib_fetch", lambda: "BBB|USD|B|1|X|0|12.5|>10000000|F|\nCCC|USD|C|1|X|0|90|0|F|\n")
    monkeypatch.setenv("TZ_API_KEY_ID", "k")
    monkeypatch.setenv("TZ_API_SECRET_KEY", "s")
    args = Namespace(state=tmp_path / "state", out=tmp_path / "out", force=True, force_quotes=True)
    monkeypatch.setattr(L, "quote_slot", lambda now: None)  # the clock must not pick a real slot
    assert L.cmd_snap(args) == 0
    assert not any("accept" in u or "/order" in u and m != "get" for m, u in fake.calls)
    recs = {r["symbol"]: r for r in L.T.load(args.state / "records.jsonl")}
    assert recs["AAA"]["etb"] is True and recs["AAA"]["outcome"] == "easy to borrow"  # counted, not quoted
    assert recs["BBB"]["outcome"] == "offered" and recs["BBB"]["offer"]["regular"] == 0.05 and recs["BBB"]["ib"] == "enough"
    assert recs["CCC"]["pb_su_pool"] and recs["CCC"]["offer"] == {"regular": None, "pb": None, "su": 0.02}
    assert recs["CCC"]["threshold"] is None  # no threshold list fetched yet: unknown
    assert recs["DDD"]["outcome"] == "busy"
    run = args.out / today
    snap = next(run.iterdir())
    assert gzip.decompress((snap / "ib_usa.txt.gz").read_bytes()).startswith(b"BBB")
    assert json.loads((snap / "account.json").read_text())["pnl"]["availableCash"] == 585.0
    audits = L.T.load(args.state / "audits.jsonl")
    assert audits[0] == {"date": today, "time": audits[0]["time"], "spent": [], "cash_rows": 1}  # no balance
    ok: dict = {"orders": {"orders": []}, "inventory": {"locates": []}}
    assert L.spent({**ok, "positions": {"positions": [{"symbol": "X"}]}}) == ["positions"]
    assert L.spent({**ok, "positions": {"error": "Timeout"}}) == ["positions unchecked"]  # a failed check is not clean
    assert L.snap_records([{"symbol": "Z", "price": 2.0}], None, {}, {}, {"slot": "snap"})[0]["ib"] is None
    text = L.report(list(recs.values()), audits)
    assert "| qforced |" not in text  # forced quotes stay out of the slot table
    recs2 = [{**r, "slot": "q1550"} for r in recs.values()]
    text = L.report(recs2, audits)
    assert "| q1550 | 3 | 33% | 67% | 33% | 0% | 33% | 0% | 0% | 0% | 1.75% |" in text
    assert "Pre-Borrow offered on 0, Single Use on 1." in text
    assert "no positions, orders or locates" in text and "cash now" not in text
    assert "- cash now: 585.0" in L.report(recs2, audits, 585.0)
    late = [{**r, "slot": "snap", "time": "20:30:00"} for r in recs.values()]
    assert "## Easy to borrow through the day" not in L.report(late, audits)  # after 20:00 TradeZero gives no locates
    monkeypatch.setattr(L, "quote_slot", lambda now: "q1100")
    args.force_quotes = False
    assert L.cmd_snap(args) == 0 and L.cmd_snap(args) == 0
    slots = [r["slot"] for r in L.T.load(args.state / "records.jsonl")]
    assert slots == ["qforced"] * 4 + ["q1100"] * 4 + ["snap"] * 4  # a second run in the same slot does not quote


def test_logger_daily_files_and_failures(tmp_path, monkeypatch) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test2")
    for k in ("TZ_API_KEY_ID", "TZ_API_SECRET_KEY", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)

    def fetch(url, **kw):
        if "finra" in url:
            raise L.requests.ConnectionError("down")
        if "threshold" in url or "regsho" in url:
            return Namespace(text="Symbol|Name|Flag\nZZZ|Z corp|Y\n20261109210500\n")
        return Namespace(text=f"Symbol|x\n{url}\n")

    monkeypatch.setattr(L, "fetch", fetch)
    args = Namespace(state=tmp_path / "state", out=tmp_path / "out", force=False, force_quotes=False)
    assert L.cmd_daily(args) == 0
    day = next(d for d in (tmp_path / "out").iterdir() if d.is_dir())
    names = {p.name for p in (day / "daily").iterdir()}
    assert {"nasdaq_threshold.txt", "nyse_threshold.txt", "nasdaqlisted.txt.gz", "halts.xml", "REPORT.md"} <= names
    assert "finra_short_volume.txt" in (day / "daily" / "errors.txt").read_text()
    assert (tmp_path / "out" / "REPORT.md").exists()
    assert L.json.loads((args.state / "threshold.json").read_text())["symbols"] == ["ZZZ"]
    calls: list[str] = []
    monkeypatch.setattr(L, "fetch", lambda url, **kw: calls.append(url))
    assert L.cmd_daily(args) == 0 and any("finra" in u for u in calls)  # FINRA failed: the backup run retries
    monkeypatch.setattr(L, "fetch", lambda url, **kw: Namespace(text="Symbol|Name|Flag\nZZZ|Z corp|Y\n"))
    assert L.cmd_daily(args) == 0  # every source answers: the day is done
    calls.clear()
    monkeypatch.setattr(L, "fetch", lambda url, **kw: calls.append(url))
    assert L.cmd_daily(args) == 0 and calls == []  # the backup cron does not collect the same day twice


def test_errors_keep_the_account_out_of_the_public_log(monkeypatch, capsys) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test3")

    def boom(args):
        raise RuntimeError("500 Server Error for url: https://webapi.tradezero.com/v1/api/account/SECRET123")
    monkeypatch.setattr(L, "cmd_snap", boom)
    monkeypatch.setattr("sys.argv", ["borrow_logger.py", "snap"])
    assert L.main() == 1
    out = capsys.readouterr().out
    assert "failed: RuntimeError" in out and "SECRET123" not in out


def test_session_day_and_web_pages_are_not_data(monkeypatch) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test4")
    assert L.T.session_day({"last_updated": "2026-11-10T00:59:00.058246601Z"}) == "2026-11-09"  # 19:59 New York
    assert L.T.session_day({"last_updated": "2026-11-09T15:00:00Z"}) == "2026-11-09"
    assert L.T.session_day({}) == ""

    class Page:
        text, url = "  <!DOCTYPE html><title>Page Not Available</title>", "https://x/Trader.aspx?id=http404"

        def raise_for_status(self) -> None:
            pass
    monkeypatch.setattr(L.requests, "get", lambda *a, **k: Page())
    log: list[str] = []
    L.try_save(Path("unused"), "nasdaq_threshold.txt", lambda: L.fetch("https://x/nasdaqth20261109.txt").text, log)
    assert log and "web page instead of data" in log[0]


def test_premarket_candidates_and_threshold_files() -> None:
    L = _script("borrow_logger", "borrow_logger_under_test5")
    old = {"date": "2026-11-09", "threshold": True, "offer": {"su": 0.02}}
    assert L.migrate(dict(old)) == {"date": "2026-11-09", "offer": {"su": 0.02}, "pb_su_pool": True,
                                    "threshold": None, "threshold_day": None}
    new = {"date": "2026-11-10", "threshold": True, "threshold_day": "20261109"}
    assert L.migrate(dict(new)) == new

    snap = {"AAA": {"latestTrade": {"p": 3.1}}, "BBB": {"latestTrade": {"p": 0.2}}, "CCC": {}}
    assert L.prior_cands(["AAA", "BBB", "CCC"], snap) == [{"symbol": "AAA", "price": 3.1, "pct": None, "src": "prior"}]
    nas = "Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Rule 3210|Filler\nAAPD|X|G|Y|N|\n20261109\n"
    assert L.threshold_symbols(nas, "Symbol|Security Name\n20261109210500\n") == ["AAPD"]
    assert L.quote_slot(L.datetime(2026, 11, 10, 4, 5, tzinfo=L.T.NY)) == "q0415"
    assert L.quote_slot(L.datetime(2026, 11, 10, 19, 35, tzinfo=L.T.NY)) == "q1930"


def test_market_scan_prices_and_premarket(tmp_path, monkeypatch) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test6")
    calls: list[tuple] = []

    def get(url, params):
        calls.append((url, params))
        return {s: {} for s in params["symbols"].split(",")}
    assert len(L.market_scan(get, [f"S{i}" for i in range(2500)])) == 2500
    assert [p["feed"] for _, p in calls] == ["delayed_sip"] * 3 and len(calls[0][1]["symbols"].split(",")) == 1000

    # a premarket trade of today; yesterday's trade is older and not today's
    sip = {"latestTrade": {"p": 2.5, "t": "2026-11-10T12:10:00Z"}}
    iex = {"latestTrade": {"p": 2.0, "t": "2026-11-09T20:51:00Z"}}
    assert L.fresh_price("2026-11-10", sip, iex) == (2.5, "2026-11-10T12:10:00Z", "delayed_sip")
    assert L.fresh_price("2026-11-10", None, iex) is None
    scan = {"UPP": {**sip, "dailyBar": {"c": 1.0, "t": "2026-11-09T05:00:00Z"}},
            "FLAT": {**sip, "dailyBar": {"c": 2.4, "t": "2026-11-09T05:00:00Z"}},
            "TOD": {**sip, "dailyBar": {"c": 2.5, "t": "2026-11-10T05:00:00Z"}, "prevDailyBar": {"c": 2.0}},
            "OLD": {**iex, "dailyBar": {"c": 1.0, "t": "2026-11-09T05:00:00Z"}}}
    assert [(c["symbol"], c["pct"]) for c in L.scan_gainers(scan, "2026-11-10", set())] == [("UPP", 150.0), ("TOD", 25.0)]

    pages = iter([{"bars": {"A": [1, 2]}, "next_page_token": "x"}, {"bars": {"A": [3], "B": [4]}}])
    assert L.alpaca_all(lambda u, p: next(pages), "u", {}) == {"bars": {"A": [1, 2, 3], "B": [4]}}
    assert L.cash_rows({"cash": {"error": "HTTPError"}}) is None and L.cash_rows({"cash": [{"a": 1}, {"b": 2}]}) == 2
    assert L.cash_rows({"cash": {"rows": [{"a": 1}, {"b": 2}]}}) == 2

    class Clock(L.datetime):  # type: ignore[name-defined]
        @classmethod
        def now(cls, tz=None):
            return L.datetime(2026, 11, 10, 7, 35, tzinfo=L.T.NY)
    monkeypatch.setattr(L, "datetime", Clock)
    monkeypatch.setattr(L, "trading_day", lambda d: True)
    for k in ("TZ_API_KEY_ID", "TZ_API_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(L.P, "ib_fetch", lambda: "")
    monkeypatch.setattr(L, "fetch", lambda url, **kw: Namespace(text="<rss/>"))

    def alpaca(url, params):
        if url.endswith("/movers"):
            return {"last_updated": "2026-11-09T21:00:00Z", "gainers": []}  # still the prior session
        if params.get("feed") == "delayed_sip":
            return {s: scan.get(s, {}) for s in params["symbols"].split(",")}
        return {}
    monkeypatch.setattr(L.T, "_alpaca_get", alpaca)
    state = tmp_path / "state"
    state.mkdir()
    (state / "universe.json").write_text(L.json.dumps(sorted(scan)))
    (state / "prior.json").write_text(L.json.dumps({"2026-11-09": ["FLAT"]}))
    args = Namespace(state=state, out=tmp_path / "out", force=False, force_quotes=False)
    assert L.cmd_snap(args) == 0
    recs = L.T.load(state / "records.jsonl")
    assert [(r["symbol"], r["src"], r["price"], r.get("price_feed")) for r in recs] == [
        ("FLAT", "prior", 2.5, "delayed_sip"), ("UPP", "scan", 2.5, "delayed_sip"), ("TOD", "scan", 2.5, "delayed_sip")]
    assert (tmp_path / "out" / "2026-11-10" / "snap-0735" / "market_snapshot.json.gz").exists()
    assert L.cmd_snap(args) == 0 and len(L.T.load(state / "records.jsonl")) == 3  # a second trigger minutes later
    monkeypatch.setattr(L, "trading_day", lambda d: False)
    (state / "records.jsonl").unlink()
    assert L.cmd_snap(args) == 0 and not (state / "records.jsonl").exists()  # a holiday records nothing
