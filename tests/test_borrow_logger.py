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
    """AAA easy to borrow; BBB regular locate; CCC threshold with Single Use only; DDD busy (meter's quote)."""

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
    assert L.cmd_snap(args) == 0
    assert not any("accept" in u or "/order" in u and m != "get" for m, u in fake.calls)
    recs = {r["symbol"]: r for r in L.T.load(args.state / "records.jsonl")}
    assert recs["AAA"]["etb"] is True and recs["AAA"]["outcome"] == "easy to borrow"  # counted, not quoted
    assert recs["BBB"]["outcome"] == "offered" and recs["BBB"]["offer"]["regular"] == 0.05 and recs["BBB"]["ib"] == "enough"
    assert recs["CCC"]["threshold"] and recs["CCC"]["offer"] == {"regular": None, "pb": None, "su": 0.02}
    assert recs["DDD"]["outcome"] == "busy"
    run = args.out / today
    snap = next(run.iterdir())
    assert gzip.decompress((snap / "ib_usa.txt.gz").read_bytes()).startswith(b"BBB")
    assert json.loads((snap / "account.json").read_text())["pnl"]["availableCash"] == 585.0
    audits = L.T.load(args.state / "audits.jsonl")
    assert audits[0] == {"date": today, "time": audits[0]["time"], "spent": []}  # no balance in the cache
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
        return Namespace(text=f"Symbol|x\n{url}\n")

    monkeypatch.setattr(L, "fetch", fetch)
    args = Namespace(state=tmp_path / "state", out=tmp_path / "out", force=False, force_quotes=False)
    assert L.cmd_daily(args) == 0
    day = next(d for d in (tmp_path / "out").iterdir() if d.is_dir())
    names = {p.name for p in (day / "daily").iterdir()}
    assert {"nasdaq_threshold.txt", "nyse_threshold.txt", "nasdaqlisted.txt.gz", "halts.xml", "REPORT.md"} <= names
    assert "finra_short_volume.txt" in (day / "daily" / "errors.txt").read_text()
    assert (tmp_path / "out" / "REPORT.md").exists()


def test_errors_keep_the_account_out_of_the_public_log(monkeypatch, capsys) -> None:
    L = _script("borrow_logger", "borrow_logger_under_test3")

    def boom(args):
        raise RuntimeError("500 Server Error for url: https://webapi.tradezero.com/v1/api/account/SECRET123")
    monkeypatch.setattr(L, "cmd_snap", boom)
    monkeypatch.setattr("sys.argv", ["borrow_logger.py", "snap"])
    assert L.main() == 1
    out = capsys.readouterr().out
    assert "failed: RuntimeError" in out and "SECRET123" not in out
