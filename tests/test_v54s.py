"""v54s on v51's synthetic world: asis reproduces v54d, stricter fill rules fill no more limits; v54m's margin rule."""
from __future__ import annotations

import argparse
import json

import numpy as np

from test_v24 import _script
from test_v51 import _world
from test_v54 import _write


def test_v54s_rules(tmp_path, monkeypatch) -> None:
    MD = _script("run_v51_data", "run_v51_data_v54s")
    D = _script("run_v54d", "run_v54d_for_v54s")
    S = _script("run_v54s", "run_v54s_under_test")
    monkeypatch.setattr(S, "D", D)
    monkeypatch.setattr(S, "V", D.V)
    monkeypatch.setattr(S, "E", D.E)
    monkeypatch.setitem(S._orig, "limit", D.E._limit)
    monkeypatch.setitem(S._orig, "frames", D.V._frames)
    monkeypatch.setattr(D.E, "_limit", D.E._limit)
    monkeypatch.setattr(D.V, "_frames", D.V._frames)
    _world(tmp_path, MD)
    monkeypatch.setattr(D, "SETUP", "FADE")
    monkeypatch.setitem(S.RULES, "vol3k5", 1e18)  # never filled
    ns = argparse.Namespace
    kw = dict(inputs=tmp_path / "v18", extras=tmp_path / "v28", data=tmp_path / "v51", procs=1, out=tmp_path / "res")
    assert D.cmd_minute(ns(**kw)) == 0
    for r in S.RULES:
        assert S.cmd_minute(ns(rule=r, **kw)) == 0
    ref = json.loads((tmp_path / "res" / "minute.json").read_text(encoding="utf-8"))
    got = {r: json.loads((tmp_path / "res" / f"minute-{r}.json").read_text(encoding="utf-8")) for r in S.RULES}
    for k, d in got["asis"].items():
        if k in ref and isinstance(d, dict):
            assert {y: v for y, v in d.items() if y != "2021-2026"} == ref[k]
    share = {r: got[r]["c_1555 d1pm/t0.00/s0.00 limit share"] for r in S.RULES}
    assert any(v > 0 for v in share["asis"].values())
    for y, v in share["asis"].items():
        assert share["through1"].get(y, 0) <= v and share["vol3k1"].get(y, 0) <= share["through1"].get(y, 0)
    assert all(v == 0 for v in share["vol3k5"].values())
    monkeypatch.setattr(S, "CHECK", ("2099", 0, 0.0, 0.0))
    assert S.cmd_final(ns(res=tmp_path / "res", out=tmp_path / "final")) == 0
    assert "# v54s report" in (tmp_path / "final" / "V54S_REPORT.md").read_text(encoding="utf-8")


def test_v54m_margin(tmp_path, monkeypatch) -> None:
    Mm = _script("run_v54m", "run_v54m_under_test")
    M = Mm.M
    monkeypatch.setattr(M.R29, "PATHS", 200)
    monkeypatch.setattr(M, "SEEDS", (0,))
    monkeypatch.setattr(M, "STRESS_SEEDS", (0,))
    assert Mm.neighbours(M.BOOKS.index((0.40, 0.0, 0.0, 5))) is None
    v49 = M.BOOKS.index(M.REFS["v49"])
    nb = Mm.neighbours(v49)
    assert sorted(M.BOOKS[n][:3] for n in nb) == [(0.20, 0.40, 0.25), (0.20, 0.60, 0.20), (0.30, 0.40, 0.20)]
    safe = M.BOOKS.index((0.20, 0.40, 0.15, 5))
    years = np.repeat(np.arange(2018, 2027), 60)
    rng = np.random.default_rng(2)
    base = rng.normal(0.002, 0.002, len(years))
    cliff = base + np.where(years == 2024, -0.02, 0.0)  # RU 25%: a ruinous 2024
    rets = {b: base for b in Mm.neighbours(safe) + [safe, v49] + nb}
    rets[M.BOOKS.index((0.20, 0.40, 0.25, 5))] = cliff
    _write(tmp_path / "runs", years, rets, M)
    out = tmp_path / "final"
    assert Mm.cmd_final(argparse.Namespace(runs=tmp_path / "runs", out=out, procs=1)) == 0
    s = json.loads((out / "v54m_summary.json").read_text(encoding="utf-8"))
    assert s["margin"][s["v49"]] is False
    assert s["pick"] == M.W.book_id(0.20, 0.40, 0.15, 5)
    assert "# v54m report" in (out / "V54M_REPORT.md").read_text(encoding="utf-8")
