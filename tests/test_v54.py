"""v54: the size books, and the walk-forward final on synthetic daily returns (each year chosen from earlier years)."""
from __future__ import annotations

import argparse
import json

import numpy as np
import pytest

from test_v24 import _script


@pytest.fixture(scope="module")
def M():
    return _script("run_v54", "run_v54_under_test")


def test_books(M) -> None:
    assert len(M.BOOKS) == 126 and all(any(b[:3]) for b in M.BOOKS)
    for v in M.REFS.values():
        assert v in M.BOOKS


def _write(root, years, rets: dict, M) -> None:
    root.mkdir(parents=True)
    nl = len(M.LEVELS)
    for b, r in rets.items():
        arr = {}
        for t in M.TASKS:
            arr[f"{M.MAIN}|{t}"] = np.broadcast_to(r, (len(M.SEEDS), nl, len(r))).astype(np.float32)
        for n in M.STRESS.values():
            arr[f"{n}|base"] = np.broadcast_to(r, (len(M.STRESS_SEEDS), nl, len(r))).astype(np.float32)
        np.savez_compressed(root / f"b{b}.npz", years=years, **arr)


def test_walk_forward_final(M, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(M.R29, "PATHS", 300)
    monkeypatch.setattr(M, "SEEDS", (0, 1))
    monkeypatch.setattr(M, "STRESS_SEEDS", (0,))
    monkeypatch.setattr(M, "HIST_SEEDS", (0,))
    years = np.repeat(np.arange(2018, 2027), 60)
    a, b, c = M.BOOKS.index(M.REFS["v49"]), M.BOOKS.index(M.REFS["v50"]), 0
    rng = np.random.default_rng(1)
    base = rng.normal(0.0005, 0.002, len(years))
    ra = base + np.where(years == 2018, 0.01, 0.0)          # best on 2018 only
    rb = base + np.where(years >= 2019, 0.006, 0.0)         # best from 2019 on
    rc = base + np.where(years == 2021, -0.2, 0.004)        # good, then ruinous in 2021
    _write(tmp_path / "runs", years, {a: ra, b: rb, c: rc}, M)
    out = tmp_path / "final"
    assert M.cmd_final(argparse.Namespace(runs=tmp_path / "runs", out=out, procs=1)) == 0
    s = json.loads((out / "v54_summary.json").read_text(encoding="utf-8"))
    bk = {i: M.W.book_id(*M.BOOKS[i][:3], int(M.BOOKS[i][3])) for i in (a, b, c)}
    # 2019 is chosen on 2018 alone, where book a is best
    assert s["plans"]["wf-exp"]["2019"] == bk[a]
    # book c's 2021 crash is never seen before 2021, and it is never chosen after it
    assert all(s["plans"]["wf-exp"][str(y)] != bk[c] for y in range(2022, 2027))
    assert set(s["plans"]) == {"wf-exp", "wf-roll3", "fixed-v49", "fixed-v50"}
    assert "# v54 report" in (out / "V54_REPORT.md").read_text(encoding="utf-8")
