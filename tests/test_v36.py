"""v36 checks: the grid, the member sets and HOT rules, and the choice on 2018-2022 paths."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v36", "run_v36_under_test")


def test_grid(V) -> None:
    assert len(V.BOOKS) == len(set(V.BOOKS)) == 64 and len(V.JOBS) == 16


def test_rules(V) -> None:
    its = [{"member": "B:v19:DS1", "side": -1, "tier": 2, "w": 0.2},
           {"member": "B:v19:ON1", "side": -1, "tier": 1, "w": 0.2},
           {"member": "C:SYMPATHY", "side": -1, "tier": 2, "w": 0.2}]
    out, cap = V.apply_rules(its, V.SETS["no_both"], "none")
    assert [it["member"] for it in out] == ["B:v19:DS1"] and cap is None
    out, cap = V.apply_rules(its, V.SETS["no_on1"], "half")
    assert [it["w"] for it in out] == [0.1, 0.1] and cap is None and its[0]["w"] == 0.2
    assert V.apply_rules(its, (), "cap25")[1] == 0.25 and V.apply_rules(its, (), "cap50")[1] == 0.5


def test_pick(V) -> None:
    a = {"early": {"med": 20000, "p_ruin": 0.03}}
    b = {"early": {"med": 15000, "p_ruin": 0.02}}
    assert V.pick([a, b]) is b and V.pick([a]) is None
