"""v34 checks: the jobs cover every members x size x costs once, and the verdict compares each bigger size of the
limit members with A1 at 20% on the four tests and the ruin rule."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v34", "run_v34_under_test")


def test_jobs(V) -> None:
    assert len(V.JOBS) == len(set(V.JOBS)) == 2 * 4 * len(V.TASKS)


def test_verdict(V) -> None:
    get = {}
    for t, a1 in (("base", 10), ("base_late", 20), ("hot5", 8), ("spread2", 9)):
        get[("A1", 0.20, t)] = {"med": a1, "p_ruin": 0.005}
        get[("limit", 0.25, t)] = {"med": a1 + 1, "p_ruin": 0.005}
        get[("limit", 0.30, t)] = {"med": a1 + 2, "p_ruin": 0.02}
        get[("limit", 0.40, t)] = {"med": a1 + 3 if t != "hot5" else a1 - 1, "p_ruin": 0.005}
    v = V.verdict(get)
    assert v["sizes"]["0.25"]["raises"] and not v["sizes"]["0.3"]["raises"] and not v["sizes"]["0.4"]["raises"]
    assert v["choice"] == "0.25"
