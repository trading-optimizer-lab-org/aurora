"""v44 checks: the data helpers (session mapping, tick aggregation), the statistics, the new families' signals and
counts, part M's triggers and filters, part C's sleeve."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def DV():
    from test_v24 import _script
    return _script("run_v44_data", "run_v44_data_under_test")


def test_session_events(DV) -> None:
    D = {"dates": pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"]), "cols": pd.Index(["AAA", "BBB"])}
    when = pd.Series(pd.to_datetime(["2024-01-02 08:00", "2024-01-02 10:15", "2024-01-02 17:30",
                                     "2024-01-03 09:29", "2024-01-06 11:00"]))
    ev = DV.session_events(D, pd.Series(["AAA", "BBB", "AAA", "ZZZ", "BBB"]), when)
    assert list(ev.index) == [0, 1, 2]  # ZZZ has no column; Saturday falls past the last session
    assert ev["t"].tolist() == [0, 0, 1] and ev["minute"].tolist() == [-1, 45, -1] and ev["j"].tolist() == [0, 1, 0]


def test_aggregate_ticks(DV) -> None:
    start = pd.Timestamp("2024-01-02 14:00", tz="UTC")
    t = start + pd.to_timedelta([10, 20, 30, 70, 80], unit="s")
    trades = pd.DataFrame({"t": t, "p": [10.0, 10.1, 10.1, 10.0, 10.2], "s": [100, 50, 20000, 300, 100],
                           "c": [[], ["F"], [], [], ["I"]]})
    quotes = pd.DataFrame({"t": [start + pd.Timedelta(seconds=65)], "bp": [10.0], "ap": [10.4], "bs": [3], "as": [1]})
    out = DV.aggregate_ticks(trades, quotes, start).set_index("minute")
    # minute 0: tick rule (no quote yet): +1 for 10.1, carried for the second 10.1; the first trade has no sign
    assert out.loc[0, "vb"] == 20050 and out.loc[0, "vs"] == 0 and out.loc[0, "viso"] == 50
    assert out.loc[0, "vodd"] == 50 and out.loc[0, "vblk"] == 20000 and out.loc[0, "n"] == 3
    # minute 1: mid 10.2: 10.0 is a sell, 10.2 at the mid falls back to the tick rule (up)
    assert out.loc[1, "vs"] == 300 and out.loc[1, "vb"] == 100
    assert out.loc[1, "spread"] == pytest.approx(0.4 / 10.2) and out.loc[1, "dimb"] == pytest.approx(0.5)
