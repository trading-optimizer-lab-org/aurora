"""Tests for the v13 walk-forward, plateau and PBO helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v13


def test_grid_and_neighbours():
    cfgs = v13.grid()
    nb = v13.neighbours(cfgs)
    assert len(cfgs) == 144 and len(set(map(v13.cname, cfgs))) == 144
    # each configuration has itself plus (sizes - 1) summed over the dimensions as neighbours
    assert all(len(ix) == 1 + sum(len(v) - 1 for v in v13.DIMS.values()) for ix in nb)


def test_score_is_the_worse_half():
    rng = np.random.default_rng(0)
    M = np.vstack([rng.normal(0.02, 0.02, (24, 3)), rng.normal(-0.01, 0.02, (24, 3))])
    s = v13.score(M, np.zeros(48))
    full = v13.sortino_cols(M[24:], np.zeros(24))
    assert np.allclose(s, np.minimum(v13.sortino_cols(M[:24], np.zeros(24)), full))


def test_walk_forward_uses_only_earlier_years():
    idx = pd.bdate_range("2016-01-04", "2026-10-16")
    rng = np.random.default_rng(1)
    cols = [v13.cname(g) for g in v13.grid()]
    R = pd.DataFrame(rng.normal(0.0003, 0.01, (len(idx), len(cols))), index=idx, columns=cols)
    best_late = cols[7]
    R.loc["2023":, best_late] += 0.01  # only good after 2023: a forward-looking rule would pick it earlier
    wf = v13.walk_forward(R, pd.Series(0.0, index=idx), v13.neighbours(v13.grid()))
    assert wf["picks"][2018]["one"] != best_late and set(wf["picks"]) == set(v13.WF_YEARS)
    assert wf["one"].index.min() >= pd.Timestamp("2018-01-01")


def test_pbo_is_low_when_one_configuration_is_always_better():
    idx = pd.bdate_range("2016-01-04", "2026-10-16")
    rng = np.random.default_rng(2)
    cols = [v13.cname(g) for g in v13.grid()]
    R = pd.DataFrame(rng.normal(0.0, 0.01, (len(idx), len(cols))), index=idx, columns=cols)
    R[cols[0]] = rng.normal(0.003, 0.005, len(idx))
    out = v13.cpcv(R, pd.Series(0.0, index=idx), [[i] for i in range(len(cols))])
    assert out["splits"] == 252 and out["pbo"] < 0.05
