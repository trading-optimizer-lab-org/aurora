"""v56's choice on 2018-2022, its test on all paths, and the report on synthetic grades."""
from __future__ import annotations

import argparse
import json

from test_v24 import _script


def _res(med: float, ruin: float, late_ruin: float | None = None) -> dict:
    g = {"med": med, "p_ruin": ruin}
    one = {"all": g, "early": g, "late": {"med": med, "p_ruin": ruin if late_ruin is None else late_ruin}}
    return {"0": one, "1": one}


def test_v56_pick_and_final(tmp_path) -> None:
    S = _script("run_v56", "run_v56_under_test")
    assert len(S.BOOKS) == 48 and S.SETS["W50"]["loc"] == {1: 0.10, 2: 0.50}
    grades = {"A": (13_000, 0.04, None), "B": (20_000, 0.09, None), "C": (12_000, 0.01, None), "D": (14_000, 0.02, 0.2)}
    runs = tmp_path / "runs"
    runs.mkdir()
    for i, (b, (m, r, lr)) in enumerate(grades.items()):
        res = {w: {t: _res(m, r, lr) for t in S.TASKS} for w in S.SETS}
        (runs / f"b{i}.json").write_text(json.dumps({"book": b, "res": res}), encoding="utf-8")
    assert S.cmd_final(argparse.Namespace(runs=runs, out=tmp_path / "out")) == 0
    s = json.loads((tmp_path / "out" / "v56_summary.json").read_text(encoding="utf-8"))
    # D has the best 2018-2022 median within 5% ruin but fails on 2023+; B breaks the ruin bar
    assert s["picks"]["W0"] == {"choice": "D", "met": False, "hindsight": "D"}
    assert "NOT MET" in (tmp_path / "out" / "V56_REPORT.md").read_text(encoding="utf-8")
