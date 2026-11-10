"""The borrow logger ticker against a fake gh: its start times, the chain hand-over and the twin guard."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path


def _ticker():
    path = Path(__file__).resolve().parents[1] / "scripts" / "borrow_ticker.py"
    spec = importlib.util.spec_from_file_location("borrow_ticker_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_start_times() -> None:
    T = _ticker()
    mon, sat, sun = (datetime(2026, 11, d, tzinfo=T.NY) for d in (9, 14, 15))
    ev = T.events(mon)
    assert len(ev) == 33 and ev[0][0].strftime("%H:%M") == "04:05" and ev[-1][0].strftime("%H:%M") == "19:35"
    assert ("daily" not in {m for _, m in ev}) and any(t.strftime("%H:%M") == "15:45" for t, _ in ev)
    assert [(t.strftime("%H:%M"), m) for t, m in T.events(sat)] == [("05:30", "daily")]
    assert T.events(sun) == []
    fri_night = datetime(2026, 11, 13, 21, 0, tzinfo=T.NY)
    assert [m for _, m in T.upcoming(fri_night, fri_night + T.AHEAD)] == ["daily"]
    sat_noon = datetime(2026, 11, 14, 12, 0, tzinfo=T.NY)
    assert T.upcoming(sat_noon, sat_noon + T.AHEAD) == []  # the chain rests until a Sunday-night cron kick
    assert T.older_twin(50, "40", [{"databaseId": 40}, {"databaseId": 50}]) is False  # the parent is finishing
    assert T.older_twin(50, "", [{"databaseId": 45}, {"databaseId": 50}]) is True
    assert T.older_twin(45, "", [{"databaseId": 45}, {"databaseId": 50}]) is False


def test_chain(monkeypatch) -> None:
    T = _ticker()
    calls: list[tuple] = []

    def gh(*args):
        calls.append(args)
        if args[:2] == ("run", "list"):
            return json.dumps([{"databaseId": 7}] if "in_progress" in args else [])
        return ""

    now = datetime.now(T.NY)
    monkeypatch.setattr(T, "gh", gh)
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    monkeypatch.setattr(T, "upcoming", lambda a, b: [(a, "snap"), (a, "daily")])
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setenv("PARENT", "")
    monkeypatch.setenv("SINCE", "")
    assert T.main() == 0 and not any(c[0] == "workflow" for c in calls)  # older run 7 keeps the chain

    calls.clear()
    monkeypatch.setenv("PARENT", "7")
    since = now - timedelta(minutes=2)
    monkeypatch.setenv("SINCE", since.isoformat())
    assert T.main() == 0
    runs = [c for c in calls if c[0] == "workflow"]
    assert [c[2] for c in runs] == ["borrow-logger.yml", "borrow-logger.yml", "borrow-ticker.yml"]
    assert runs[0][-1] == "mode=snap" and runs[1][-1] == "mode=daily"
    assert runs[2][-3:] == ("parent=9", "-f", f"since={(since + T.LIFE).isoformat()}")
