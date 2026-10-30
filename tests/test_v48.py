"""v48 checks: the grid as pre-registered, the seeded dropout, the joined replays, the ensemble statistics and the
choice rule."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def W():
    from test_v24 import _script
    return _script("run_v48", "run_v48_under_test")


def test_grid_matches_the_preregistration(W) -> None:
    assert len(W.COMBOS) == 63 == len(set(W.COMBOS)) and len(W.COMBOS) * len(W.NEWS) == 126
    assert W.BASE[:3] in W.COMBOS and W.BASE[3] in W.NEWS
    assert W.RUS == (0.70, 0.50, 0.40, 0.30, 0.25, 0.20, 0.15) and W.NSS == (0.40, 0.30, 0.25)
    assert W.DSS == (0.20, 0.25, 0.30) and W.NEWS == (3, 5) and len(W.SEEDS) == 31 and W.DROP == 0.10
    assert W.sizes_of(0.2, 0.4, 0.7) == {"B:v19:DS1": 0.2, "B:v20:RU": 0.7, "B:v20:NS": 0.4}
    assert list(W.sizes_of(0.2, 0.4, 0.7)) == W.MEMBERS
    assert W.book_id(*W.BASE) == "DS0.20-NS0.40-RU0.70-N3"
    import ast
    from pathlib import Path
    gen = ast.parse((Path(__file__).resolve().parents[1] / "scripts" / "gen_v48_wf.py").read_text(encoding="utf-8"))
    got = {n.targets[0].id: ast.literal_eval(n.value) for n in gen.body if isinstance(n, ast.Assign)
           and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("SHARDS", "CANARY")}
    assert got["SHARDS"] == len(W.COMBOS)
    assert [W.COMBOS[k] for k in got["CANARY"]] == [W.BASE[:3], (0.20, 0.40, 0.25)]


def test_dropout(W) -> None:
    its = [{"sym": f"S{k % 97}", "t": k, "member": "B:v20:RU"} for k in range(5000)]
    assert not any(W.dropped(it, 0) for it in its)
    for s in (1, 2):
        d = [W.dropped(it, s) for it in its]
        assert 0.08 < np.mean(d) < 0.12 and d == [W.dropped(it, s) for it in its]
    assert [W.dropped(it, 1) for it in its] != [W.dropped(it, 2) for it in its]


def test_merge_points_each_trade_at_its_replay(W) -> None:
    a = ([{"sym": "A", "_rec": 0}, {"sym": "B", "_rec": 1}], [{"id": "a0"}, {"id": "a1"}])
    b = ([{"sym": "C", "_rec": 0}], [{"id": "b0"}])
    items, recs = W.merge([a, b])
    assert [recs[it["_rec"]]["id"] for it in items] == ["a0", "a1", "b0"] and a[0][0]["_rec"] == 0


def _res(meds, ruins):
    return {str(s): {k: {"med": m, "p_ruin": r} for k in ("all", "early", "late")}
            for s, (m, r) in enumerate(zip(meds, ruins))}


def test_ensemble_and_choice(W) -> None:
    z = W.ensemble(_res([10, 20, 30], [0.0, 0.03, 0.06]), "all")
    assert z["med"] == 20 and z["ruin"] == pytest.approx(0.03) and z["med0"] == 10 and z["ruin0"] == 0
    assert z["ruin90"] == pytest.approx(np.quantile([0, 0.03, 0.06], 0.9))
    books = {"big": {"res": {"base": _res([30, 30], [0.02, 0.04]), "hot5": _res([20, 20], [0.0, 0.0])}},
             "mid": {"res": {"base": _res([25, 25], [0.01, 0.02]), "hot5": _res([20, 20], [0.02, 0.02])}},
             "low": {"res": {"base": _res([15, 15], [0.0, 0.0]), "hot5": _res([10, 10], [0.0, 0.0])}}}
    assert W.choose(books) == "mid"
    books["mid"]["res"]["hot5"] = _res([20, 20], [0.03, 0.03])
    assert W.choose(books) == "low"
    assert W.choose({"big": books["big"]}) is None
