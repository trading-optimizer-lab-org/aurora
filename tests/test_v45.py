"""v45 checks: the jobs, each strategy's items and the historical path's statistics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v45", "run_v45_under_test")


def test_jobs(V) -> None:
    assert len(V.JOBS) == len(set(V.JOBS)) == 4 * 7
    assert V.STRATS["BOOK"][1] == {"B:v19:DS1": 0.20, "B:v20:RU": 0.70, "B:v20:NS": 0.40}
    assert {V.STRATS[s][2] for s in V.IDS} == {"FREE", "PAID"} and V.STRATS["XS1"][2] == "PAID"


def test_items(V, monkeypatch) -> None:
    calls = []

    def fake(rows, level, size, ladder, **costs):
        calls.append((rows[0]["fam"], size, costs))
        return [{"fam": rows[0]["fam"], "size": size}]
    monkeypatch.setattr(V.R35, "book_items", fake)
    rows = [{"fam": m} for m in ("B:v19:DS1", "B:v20:RU", "B:v20:NS", "B:v19:ON1")]
    its = V.strat_items(rows, "BOOK", 5000.0, hot=0.05)
    assert [(c[0], c[1]) for c in calls] == [("B:v19:DS1", 0.2), ("B:v20:RU", 0.7), ("B:v20:NS", 0.4)]
    assert all(c[2] == {"hot": 0.05} for c in calls) and len(its) == 3
    monkeypatch.setattr(V.R35, "paid_items", lambda level, size, **c: [{"member": "B:v19:XS1"}, {"member": "B:v19:XS2"}])
    assert V.strat_items(rows, "XS1", 5000.0) == [{"member": "B:v19:XS1"}]


def test_hist_stats(V) -> None:
    cal = pd.bdate_range("2020-01-01", periods=504)
    r = np.full(504, 0.001)
    r[10] = -0.5
    h = V.hist_stats(r, cal, 0.0)
    assert h["worst_day"] == pytest.approx(-0.5)
    assert h["max_dd"] == pytest.approx(-0.5, abs=1e-9)
    assert h["cagr"] == pytest.approx((0.5 * 1.001 ** 503) ** 0.5 - 1)
    assert np.isfinite(h["sortino"])
    assert V.hist_stats(np.full(504, 0.001), cal, 0.0)["max_dd"] == 0.0
