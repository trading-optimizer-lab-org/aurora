"""v29 section 6 checks: IEX stores keep the candidates that have IEX bars and recompute that day's facts from them,
an IEX signal fills on SIP's first bar a minute or more later, and the pooled criterion."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_intraday as vi
from test_v26 import _D, _reset  # noqa: F401


@pytest.fixture(scope="module")
def E():
    from test_v24 import _script
    return _script("run_v29_iex_eval", "run_v29_iex_eval_under_test")


def _store(D: dict) -> vi.Store:
    day = D["dates"][60]
    cands = pd.DataFrame([{"date": day, "symbol": "A", "t": 60, "j": 0, "off": 0, "n": 3, "open": 9.0, "pc": 5.0,
                           "gap": 0.8, "pmv": 1.0, "pmh": 9.9, "pml": 8.0, "so": 1e7},
                          {"date": day, "symbol": "B", "t": 60, "j": 1, "off": 3, "n": 3, "open": 4.0, "pc": 4.0,
                           "gap": 0.0, "pmv": 1.0, "pmh": 4.1, "pml": 3.9, "so": 1e7}])
    m = np.array([0, 1, 2, 0, 1, 2], np.int16)
    px = np.array([9.0, 9.5, 9.2, 4.0, 4.1, 4.0], np.float32)
    return vi.Store(cands, {"m": m, "o": px, "h": px * 1.01, "l": px * 0.99, "c": px, "v": np.full(6, 1e4, np.float32),
                            "vw": px})


def test_iex_store_recomputes_the_day_and_drops_missing(E, tmp_path) -> None:
    D = _D(120, 3)
    st = _store(D)
    day = D["dates"][60]
    bars = pd.DataFrame({"symbol": ["A"] * 4, "minute": np.array([300, 330, 331, 335], np.int16),
                         "o": [7.0, 8.0, 8.4, 8.2], "h": [7.5, 8.5, 8.6, 8.3], "l": [6.9, 7.9, 8.3, 8.1],
                         "c": [7.2, 8.3, 8.5, 8.2], "v": [100.0, 200.0, 300.0, 50.0], "vw": [7.1, 8.2, 8.45, 8.2],
                         "n": [1, 2, 3, 1]})
    bars.to_parquet(tmp_path / f"{day.date()}.parquet", index=False)
    new, seen = E.iex_stores({"event": st}, D, tmp_path)
    c = new["event"].cands
    assert seen == {"cands": 2, "kept": 1} and c["symbol"].tolist() == ["A"]
    assert c.at[0, "open"] == 8.0 and c.at[0, "gap"] == pytest.approx(8.0 / 5 - 1)
    assert c.at[0, "pmh"] == 7.5 and c.at[0, "pml"] == 6.9 and c.at[0, "pmv"] == pytest.approx(710.0)
    assert c.at[0, "n"] == 3 and new["event"].arrays["m"].tolist() == [0, 1, 5]
    assert c.at[0, "so"] == 1e7  # the prior days' facts are kept


def test_iex_signal_fills_on_sip_a_minute_later(E) -> None:
    D = _D(120, 3)
    st = _store(D)
    idx = E.sip_index([st])
    cd = {"t": 60, "j": 0}
    b_iex = (np.array([0, 1, 5], np.int16),) + (np.zeros(3),) * 6
    got = E.on_sip((cd, b_iex, None, 0, 8.0, 9.6, 1.0), idx)
    assert got[3] == 1 and got[4] == pytest.approx(9.5) and got[5] == pytest.approx(9.5 * 1.2)
    assert got[0]["symbol"] == "A"
    assert E.on_sip((cd, b_iex, None, 2, 8.0, 9.6, 1.0), idx) is None  # minute 5 + 1 is past A's last SIP bar
    assert E.on_sip(({"t": 61, "j": 0}, b_iex, None, 0, 8.0, 9.6, 1.0), idx) is None


def test_pooled_criterion(E) -> None:
    def fam(n_sip, s_sip, n_iex, s_iex):
        return {"sip": {"trades": n_sip, "sum_net": s_sip}, "sip1": {"trades": n_sip, "sum_net": s_sip},
                "iex": {"trades": n_iex, "sum_net": s_iex}}
    v = E.verdict({"F": fam(100, 2.0, 80, 1.4), "G": fam(100, 2.0, 70, 1.6)})
    assert v["share"] == pytest.approx(0.75) and v["keep"] == pytest.approx((3.0 / 150) / 0.02) and v["met"]
    assert not E.verdict({"F": fam(100, 2.0, 60, 1.2)})["met"]  # 60% of the trades
