"""v48b checks: the books as pre-registered, v30's reserve accounts, the capital-plan rule, the choice and the final
report on synthetic shards."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(scope="module")
def B():
    from test_v24 import _script
    return _script("run_v48b", "run_v48b_under_test")


def test_books_and_plans(B) -> None:
    assert B.BOOKS[:7] == [(0.20, 0.40, ru, 5) for ru in (0.70, 0.50, 0.40, 0.30, 0.25, 0.20, 0.15)]
    assert B.BOOKS[7] == (0.20, 0.40, 0.70, 3) and len(B.BOOKS) == 8
    assert B.PLANS == {"A": (5000.0, 0.0), "B": (2500.0, 2500.0), "C": (2000.0, 0.0)}
    assert B.HORIZONS["1y"][0] == 252 and B.HORIZONS["3y"][0] == 756


def test_reserve_is_deposited_once(B) -> None:
    lv = np.array([2000.0, 5000.0])
    R = np.array([[-0.95, 0.0, -0.9], [-0.95, 0.0, -0.9]])
    idx = np.array([[0, 1, 2], [1, 1, 1]])
    w, used = B.accounts(R, lv, idx, 0.0, 2500.0, 2500.0)
    # path 0: 2500 -> 125, deposit -> 2625, flat, -90% -> 262.5 frozen; path 1 flat with the reserve unused
    assert w[0] == pytest.approx(262.5) and used.tolist() == [True, False] and w[1] == pytest.approx(5000.0)
    w, used = B.accounts(R, lv, idx, 0.0, 5000.0, 0.0)
    assert w[0] == pytest.approx(250.0) and not used.any()  # frozen under $500


def test_b_rule_and_choice(B) -> None:
    a = {"med": 10.0, "es5": 1.0, "p_1000": 0.05}
    assert B.b_better(a, {"med": 11.0, "es5": 2.0, "p_1000": 0.05})
    assert not B.b_better(a, {"med": 11.0, "es5": 2.0, "p_1000": 0.06})
    assert not B.b_better(a, {"med": 9.0, "es5": 2.0, "p_1000": 0.0})

    def res(m, r):
        return {str(s): {"all": {"med": m, "p_ruin": r}} for s in range(2)}
    books = {"x": {"res": {"base": res(30, 0.05), "hot5": res(20, 0.0)}},
             "y": {"res": {"base": res(20, 0.02), "hot5": res(15, 0.02)}},
             "z": {"res": {"base": res(10, 0.0), "hot5": res(8, 0.0)}}}
    assert B.choose(books) == "y"
    assert B.choose({"x": books["x"]}) is None


def test_final_on_synthetic_shards(B, tmp_path) -> None:
    def res(m, r):
        return {str(s): {k: {"med": m, "p_ruin": r} for k in ("all", "early", "late")} for s in range(2)}

    def plans(m):
        st = {"med": m, "p10": m / 2, "p_1000": 0.01, "es5": m / 4, "p_dep": 0.1}
        return {str(s): {f"{p}_{hz}": dict(st) for p in B.PLANS for hz in B.HORIZONS} for s in range(2)}
    runs = tmp_path / "runs"
    runs.mkdir()
    for i, (ds, ns, ru, mn) in enumerate(B.BOOKS):
        bid = B.W.book_id(ds, ns, ru, mn)
        z = {"book": bid, "sizes": [ds, ns, ru, mn], "res": {"base": res(20000 - 1000 * i, 0.08 - 0.01 * i),
                                                             "hot5": res(15000, 0.08 - 0.01 * i)},
             "plans": {"base": plans(9000.0), "hot5": plans(8000.0)}}
        (runs / f"b{i}.json").write_text(json.dumps(z), encoding="utf-8")
    out = tmp_path / "out"
    assert B.cmd_final(SimpleNamespace(runs=runs, out=out)) == 0
    s = json.loads((out / "v48b_summary.json").read_text(encoding="utf-8"))
    assert s["choice"] == "DS0.20-NS0.40-RU0.15-N5" and s["plan"] == "A"
    assert "Definitive strategy" in (out / "V48B_REPORT.md").read_text(encoding="utf-8")
