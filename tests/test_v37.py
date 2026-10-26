"""v37 checks: the grid, the three setups (known at the setup close), the new members' rows and the books."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v37", "run_v37_under_test")


def test_grid(V) -> None:
    assert sum(len(V.new_grid(k)) for k in V.NEW) == 1400 and len(V.BOOKS) == 8 and len(V.JOBS) == 8
    assert all(V.R28.registry()[k][0] == "event" for k in V.NEW)


def _D(C):
    return {"C": np.array(C, float)[:, None]}


def test_first_red_day(V) -> None:
    S, prio = V.setup_mask(_D([1, 1, 1, 2, 3, 2.5, 2.4]), "C:FRD_SHORT", (1.0, 3))
    assert S[:, 0].tolist() == [False] * 5 + [True, False]  # the second red day is not a first red day
    assert prio[5, 0] == pytest.approx(2.0)
    S, _ = V.setup_mask(_D([1, 1, 1, 2, 3, 2.5, 2.4]), "C:FRD_SHORT", (2.5, 3))
    assert not S.any()


def test_rotation(V) -> None:
    C = [1, 1, 1.3, 1.1]
    so = np.full((4, 1), 1e6)
    vol = np.array([1e5, 1e5, 4e6, 6e6])[:, None]
    S, _ = V.setup_mask(_D(C), "C:ROT_SHORT", 3.0, so, vol)
    assert S[:, 0].tolist() == [False, False, True, False]  # the last session rotates but falls


def test_bounce(V) -> None:
    C = [1.0] * 40 + [2.5, 3, 2, 1.5, 1.4, 1.8]
    S, _ = V.setup_mask(_D(C), "C:BOUNCE_SHORT", 0.2)
    assert np.flatnonzero(S[:, 0]).tolist() == [45]


def test_new_rows(V) -> None:
    rows = V.new_rows({"picks": {"C:FRD": {"2020": {"name": "C:FRD_SHORT|7"}}}})
    assert rows == [{"year": 2020, "fam": "C:FRD", "name": "C:FRD_SHORT|7", "var": [None, None, False]}]
