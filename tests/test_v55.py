"""v55 on a synthetic world: the IEX decision, fail-closed sessions, the fetch's frame and the verdict."""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from test_v24 import _script


def _world(S, monkeypatch) -> None:
    dates = pd.DatetimeIndex(["2024-03-01", "2024-03-04"])
    D = {"dates": dates, "cols": ["AAA", "BBB"], "F": np.array([[1.0, 2.0], [1.0, 2.0]]),
         "C": np.full((2, 2), 10.0), "H": np.full((2, 2), 11.0), "L": np.full((2, 2), 9.0)}
    monkeypatch.setitem(S.R43._G, "D", D)


def test_v55_decision(tmp_path, monkeypatch) -> None:
    S = _script("run_v55", "run_v55_under_test")
    _world(S, monkeypatch)
    folder = tmp_path / "iex"
    folder.mkdir()
    pd.DataFrame({"symbol": ["AAA", "AAA", "AAA", "BBB"], "minute": [330, 400, 705, 500],
                  "h": [5.0, 7.0, 6.0, 3.0], "l": [4.0, 4.5, 3.5, 2.0], "c": [4.5, 6.0, 5.5, 2.5]}
                 ).to_parquet(folder / "2024-03-01.parquet", index=False)
    pd.DataFrame({"symbol": ["AAA"], "minute": [720], "h": [1.0], "l": [1.0], "c": [1.0]}
                 ).to_parquet(folder / "2024-03-04.parquet", index=False)  # after 15:50 only
    S.load_iex(folder)
    monkeypatch.setitem(S._G, "maxage", None)
    assert S.iex_decision(0, 0) == (5.5, 7.0, 3.5)
    assert S.iex_decision(0, 1) == (5.0, 6.0, 4.0)  # split factor 2
    assert S.iex_decision(1, 0) is None and S.iex_decision(1, 1) is None
    monkeypatch.setitem(S._G, "maxage", 10)
    assert S.iex_decision(0, 0) is not None and S.iex_decision(0, 1) is None  # BBB's last bar at 12:20
    D = S.R43._G["D"]
    keep = S.patch_iex(D, {(0, 0), (0, 1)})
    assert keep == {(0, 0): (10.0, 11.0, 9.0)}
    assert (D["C"][0, 0], D["H"][0, 0], D["L"][0, 0]) == (5.5, 7.0, 3.5) and D["C"][0, 1] == 10.0
    S.V.restore(D, keep)
    assert D["C"][0, 0] == 10.0


def test_v55_frame_and_verdict(tmp_path, monkeypatch) -> None:
    S = _script("run_v55", "run_v55_under_test2")
    day = pd.Timestamp("2024-03-01")
    t = S.D14._ny(day, 9, 30)
    rows = [("AAA", (t + pd.Timedelta(minutes=k)).isoformat(), 1, 2, 0.5, 1.5, 100, 1.2, 3) for k in (0, 379, 380)]
    df = S._frame(rows, day)
    assert list(df["minute"]) == [330, 709] and list(df.columns) == ["symbol", "minute", "h", "l", "c"]
    assert S._frame([], day).empty
    good = {"med": S.CHECK[0], "ruin": 0.0}
    e = {(s, k, "all"): dict(good) for s in ("sip", "iex") for k in S.P.ENS_TASKS}
    assert S.verdict(e) == (True, True)
    e[("iex", "base", "all")] = {"med": 0.85 * S.CHECK[0], "ruin": 0.0}
    assert S.verdict(e) == (True, False)
    e[("iex", "base", "all")] = dict(good)
    e[("iex", "hot5", "all")] = {"med": S.CHECK[0], "ruin": 0.03}
    assert S.verdict(e) == (True, False)
    assert S.cmd_final(argparse.Namespace(runs=tmp_path / "none", out=tmp_path / "out")) == 0
