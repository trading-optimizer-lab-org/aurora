"""v57's locate repricing and its report on synthetic grades."""
from __future__ import annotations

import argparse
import json

from test_v24 import _script
from test_v56 import _res


def test_v57_relocate() -> None:
    S = _script("run_v57", "run_v57_under_test")
    assert len(S.WORLDS) == 17 and S.SETS["W0"]["loc"] == {1: 0.0, 2: 0.0} and S.TZA_PPS == (0.01, 0.03)
    items = [{"tier": 1, "side": -1, "loc": 0.004, "price": 2.5, "_rec": 0},
             {"tier": 2, "side": -1, "loc": 0.012, "price": 2.5, "_rec": 1},
             {"tier": 0, "side": -1, "loc": 0.0, "price": 10.0, "_rec": 2},
             {"tier": 0, "side": 1, "loc": 0.0, "price": 10.0, "_rec": 3}]
    recs = [{"cost": 0.01} for _ in items]
    same = S.relocate(items, recs, S.TZA_PPS, False)
    assert same[0] is items and same[1] is recs  # W0 is v56's W0 untouched
    its, rs = S.relocate(items, recs, (0.03, 0.12), True)
    assert abs(its[0]["loc"] - 0.012) < 1e-12 and abs(its[1]["loc"] - 0.048) < 1e-12  # x3 and x4 the price a share
    assert its[2]["tier"] == 1 and abs(its[2]["loc"] - 0.003) < 1e-12  # ETB short pays HTB and can fail as HTB
    assert its[3] is items[3] and rs[3]["cost"] == 0.01  # longs pay no locate
    assert abs(rs[1]["cost"] - (0.01 + 0.036)) < 1e-12 and recs[1]["cost"] == 0.01  # inputs not mutated
    its, _ = S.relocate(items, recs, (0.03, 0.12), False)
    assert its[2] is items[2]


def test_v57_final(tmp_path) -> None:
    S = _script("run_v57", "run_v57_under_test_final")
    runs = tmp_path / "runs"
    runs.mkdir()
    for i, (b, (m, r)) in enumerate({"A": (13_000, 0.04), "B": (20_000, 0.09)}.items()):
        res = {w: {t: _res(m, r) for t in S.TASKS} for w in S.SETS}
        (runs / f"b{i}.json").write_text(json.dumps({"book": b, "res": res}), encoding="utf-8")
    assert S.cmd_final(argparse.Namespace(runs=runs, out=tmp_path / "out")) == 0
    s = json.loads((tmp_path / "out" / "v57_summary.json").read_text(encoding="utf-8"))
    assert s["picks"]["F4C3E"] == {"choice": "A", "met": True, "hindsight": "A"}
    assert "| F1C2 | 2% / 10% | 0.03 / 0.12 | no |" in (tmp_path / "out" / "V57_REPORT.md").read_text(encoding="utf-8")
