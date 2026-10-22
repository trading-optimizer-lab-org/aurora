"""v27 checks: the symbol halves, the rotation filter and the adds to a short on the entry day."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from test_v24 import _script
from test_v26 import BASE, _D, _reset  # noqa: F401  (the fixture resets costs and the shield)


def _bars(c: list[float], v: float = 1e3) -> tuple:
    c = np.array(c, float)
    o = np.r_[c[0], c[:-1]]
    return (np.arange(len(c), dtype=np.int16), o, np.maximum(o, c), np.minimum(o, c), c, np.full(len(c), v), c)


def test_halves_are_fixed_and_balanced() -> None:
    R = _script("run_v27", "run_v27_halves")
    syms = [f"S{i}" for i in range(2000)]
    h = np.array([R.half_of(s) for s in syms])
    assert 0.45 < h.mean() < 0.55
    assert [R.half_of(s) for s in syms[:20]] == list(h[:20])
    assert set(R.registry_h()) == {f"H{k}/{x}" for k in (0, 1) for x in R.R26.registry()}


def test_rotation_and_adds() -> None:
    R = _script("run_v27", "run_v27_adds")
    D = _D()
    sh.prepare(D)
    t, j = 60, 0
    b = _bars([5.0, 5.0, 5.4, 5.6, 6.1, 5.5, 5.0, 4.8], v=1e6)
    cd = {"date": D["dates"][t], "t": t, "j": j, "symbol": "A", "open": 5.0, "pc": 4.0, "pmv": 1e6, "so": 3e7}
    line = b[4].copy()
    sh.set_params({**BASE, "hold": "d1", "stop": "pct50"})
    try:
        R.EXT.update(rot="r05", add="none")
        D["SO"][t, j] = 1e6  # 2 million shares traded before the entry bar 2: rotation 2
        assert not R.ext_row(D, cd, b, line, 2, 5.4, 8.1, 1.0)["keep"]
        D["SO"][t, j] = 3e7
        assert R.ext_row(D, cd, b, line, 2, 5.4, 8.1, 1.0)["keep"]
        R.EXT.update(rot="any", add="a10")
        row = R.ext_row(D, cd, b, line, 1, 5.0, 7.5, 1.0)
        # a third at 5.0, a third at 5.5 (bar 3 high 5.6 opens 5.4 < 5.5), a third at 6.0 (bar 4: open 5.6, high 6.1)
        want = ((5.0 - 4.8) + (5.5 - 4.8) + (6.0 - 4.8)) / 3 / 5.0
        assert float(row["rets"][0]) == pytest.approx(want)
        R.EXT.update(add="a30")  # the second add (6.5) is never reached
        row = R.ext_row(D, cd, b, line, 1, 5.0, 7.5, 1.0)
        assert float(row["rets"][0]) == pytest.approx(((5.0 - 4.8) + (6.5 - 4.8) * 0) / 3 / 5.0 + 0.0)
    finally:
        R.EXT.update(rot="any", add="none")
        sh.set_params(None)
        sh.intra_row = R._ORIG_INTRA


def test_daily_rotation_uses_the_known_session() -> None:
    R = _script("run_v27", "run_v27_daily")
    D = _D()
    E = {"V": np.full(D["C"].shape, 1e6)}
    E["V"][41, 0] = 9e7
    D["SO"][:, 0] = 3e7
    s_open = v19.Spec(0, 42, "open", -1, 3, 0.2, np.nan, np.nan, "time", 1.0)
    s_close = v19.Spec(0, 41, "close", -1, 3, 0.2, np.nan, np.nan, "time", 1.0)
    assert R.rotation_daily(D, E, s_open) == pytest.approx(3.0)
    assert R.rotation_daily(D, E, s_close) == pytest.approx(3.0)
    assert R.rotation_daily(D, E, v19.Spec(0, 41, "open", -1, 3, 0.2, np.nan, np.nan, "time", 1.0)) == \
        pytest.approx(1e6 / 3e7)
    sh.intra_row = R._ORIG_INTRA
    assert isinstance(pd.Timestamp("2020-01-01"), pd.Timestamp)
