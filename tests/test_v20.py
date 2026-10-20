"""v20 checks: the grid, and the vectorised v14 procedure against the original on random data."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v20_grid as v20

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R20 = _script("run_v20")


def _grid() -> list[dict]:
    return [{"rule": "X", **g} for g in core.grid({"a": (0.1, 0.2, 0.3), "b": ("p", "q"), "s": (0.25, "none")})]


def _random(n_cfg: int, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    ix = pd.bdate_range("2016-01-04", "2026-10-16")
    R = pd.DataFrame(rng.normal(0.0004, 0.01, (len(ix), n_cfg)) + rng.normal(0, 0.0005, n_cfg), index=ix,
                     columns=[f"X|{i}" for i in range(n_cfg)])
    return R, pd.Series(0.00005, index=ix)


def _monthly(R: pd.DataFrame, cash: pd.Series) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    M = core.monthly(R)
    cm = core.monthly(cash.to_frame("c"))["c"].to_numpy()
    return M.to_numpy(), cm, M.index.to_timestamp()


def test_grid_size_and_no_nan_dimensions() -> None:
    dims = {**v20.INTRA_DIMS, **v20.DAILY_DIMS}
    assert sum(len(core.grid(d)) for d in dims.values()) == 38762
    for d in dims.values():
        for vals in d.values():
            assert all(not (isinstance(x, float) and np.isnan(x)) for x in vals)


def test_neighbours_match_core() -> None:
    cfgs = _grid()
    A = R20.neighbours_matrix(cfgs).toarray()
    for i, nb in enumerate(core.neighbours(cfgs)):
        assert sorted(np.flatnonzero(A[i])) == sorted(nb)


def test_walk_forward_and_cpcv_match_core() -> None:
    cfgs = _grid()
    R, cash = _random(len(cfgs))
    end = pd.Timestamp("2026-10-16")
    _, picks = core.walk_forward(R, cash, core.neighbours(cfgs), end=end)
    M, cm, months = _monthly(R, cash)
    A = R20.neighbours_matrix(cfgs)
    mine = R20.walk_forward(M, cm, A, months, end.year)
    assert {y: R.columns[i] for y, (i, _) in mine.items()} == {y: n for y, (n, _) in picks.items()}
    assert all(mine[y][1] == pytest.approx(picks[y][1]) for y in picks)
    a, b = core.cpcv(R, cash, core.neighbours(cfgs), end=end), R20.cpcv(M, cm, A)
    assert a["pbo"] == pytest.approx(b["pbo"]) and a["test_median"] == pytest.approx(b["test_median"])


def test_combo_pbo_matches_run_v14() -> None:
    cfgs = _grid()
    fam_R, mats = {}, {}
    cash = None
    for f, seed in (("F1", 1), ("F2", 2)):
        R, cash = _random(len(cfgs), seed)
        R = R + 0.0006  # make the training scores reach 1 so that the families enter
        fam_R[f] = (R, core.neighbours(cfgs))
        M, cm, _ = _monthly(R, cash)
        mats[f] = (M, R20.neighbours_matrix(cfgs))
    a = R20.R14.combo_pbo(fam_R, cash, pd.Timestamp("2026-10-16"))
    b = R20.combo_pbo(mats, cm)
    assert a["splits"] == b["splits"] and a["pbo"] == pytest.approx(b["pbo"])


def test_benjamini_hochberg() -> None:
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    assert R20.bh(p, 0.05).tolist() == [True, True] + [False] * 8


def test_bands() -> None:
    p = np.array([0.5, 1.0, 1.99, 2.0, 4.99, 5.0, 19.0, 20.0, 20.5])
    assert v20.in_band(p, "1-2").tolist() == [False, True, True, False, False, False, False, False, False]
    assert v20.in_band(p, "10-20").tolist() == [False] * 6 + [True, True, False]
    assert v20.in_band(p, None).tolist() == [False] + [True] * 7 + [False]
