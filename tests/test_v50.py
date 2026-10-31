"""v50 checks: the grid and sets as pre-registered, the set switches reach v49's variant, the choice rule."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def M():
    from test_v24 import _script
    return _script("run_v50", "run_v50_under_test")


def test_books_and_sets(M) -> None:
    assert len(M.BOOKS) == 54 and (0.20, 0.40, 0.20, 5) in M.BOOKS
    assert {b[0] for b in M.BOOKS} == {0.20, 0.30, 0.40} and {b[3] for b in M.BOOKS} == {5, 8}
    assert M.SETS["TZA"] is None and M.SETS["TZC"]["loc"] == {1: 0.10, 2: 0.50} and M.MAIN == "TZC"
    assert M.SETS["TZC-L0"]["loc"] == {} and M.SETS["TZC-T0"]["two"] is False and M.SETS["TZC-V0"]["vol"] is False
    assert M.SETS["TZC-B2"]["borrow"] == 2.0 and M.TARGET == 10_000.0 and M.MAX_RUIN == 0.025


def test_variant_switches(M, monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(M.Q, "variant", lambda items, recs, s: seen.append((dict(M.Q.UNAVAIL), M.Q.vol_scale(5, 0)))
                        or (items, recs))
    vs = M.Q.vol_scale
    M.variant([], [], M.SETS["TZC-V0"])
    M.variant([], [], M.SETS["TZC-L0"])
    assert seen == [({1: 0.10, 2: 0.50}, 1.0), ({}, 0.0)] and M.Q.vol_scale is vs
    assert M.variant([1], [2], None) == ([1], [2])


def test_choose(M, monkeypatch) -> None:
    ens = {"a": (12_000, 0.03), "b": (11_000, 0.02), "c": (9_000, 0.0)}
    monkeypatch.setattr(M.W, "ensemble", lambda z, s: {"med": ens[z][0], "ruin": ens[z][1]})
    books = {k: {"res": {"TZC": {t: k for t in M.ENS_TASKS}}} for k in ens}
    assert M.choose(books) == "b"
    ens["b"] = (11_000, 0.03)
    assert M.choose(books) == "c"
