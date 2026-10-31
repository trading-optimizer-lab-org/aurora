"""v52 checks on v51's synthetic world: the holdout factory reproduces v51's trades of a frozen configuration, the
every-short-HOT stress touches shorts only, and the whole holdout pipeline runs."""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import pytest

from test_v24 import _script
from test_v51 import _world

GROUPS = ("GAPUP-short", "STRONG-long")


@pytest.fixture(scope="module")
def W():
    return _script("run_v52", "run_v52_under_test")


@pytest.fixture(scope="module")
def MD():
    return _script("run_v51_data", "run_v51_data_v52")


def _frozen(W, fac, path) -> list[dict]:
    configs = []
    for g in GROUPS:
        for c in json.loads((fac / g / "report.json").read_text(encoding="utf-8"))["configs"]:
            configs.append({"id": len(configs), "src": c["id"], "group": g, "entry": c["entry"], "exit": c["exit"],
                            "filter": c["filter"], "q": c["q"], "x": c["x"], "f": c["f"], "cls": c["cls"],
                            "tag": c["tag"], "pf_d": c.get("pf_d"), "pf_l": (c.get("later") or {}).get("pf")})
    first = {g: next(c["id"] for c in configs if c["group"] == g) for g in GROUPS}
    books = [{"name": "H1", "role": "decides", "book": [[[first[GROUPS[0]], 0.3], [first[GROUPS[1]], 0.3]], 5]},
             {"name": "low2", "role": "report", "book": [[[first[GROUPS[1]], 0.2]], 3]}]
    path.write_text(json.dumps({"books": books, "configs": configs}), encoding="utf-8")
    return configs


@pytest.mark.slow
def test_holdout_pipeline(W, MD, tmp_path, monkeypatch) -> None:
    _world(tmp_path, MD)
    V = W.V
    monkeypatch.setattr(V, "PATHS", 300)
    monkeypatch.setattr(V, "SEEDS", (0, 1))
    monkeypatch.setattr(V, "SEEDS_CONF", (0, 1))
    monkeypatch.setattr(V, "TOP_ENTRY", 20)
    monkeypatch.setattr(V, "TOP_GROUP", 3)
    monkeypatch.setattr(W, "FIRST", pd.Timestamp("2021-08-02"))
    monkeypatch.setattr(W, "LAST", pd.Timestamp("2022-12-30"))
    monkeypatch.setattr(W, "SINGLE_GROUP", GROUPS[1])
    monkeypatch.setattr(W, "SINGLE_SIZES", (0.2,))
    monkeypatch.setattr(W, "SINGLE_NEWS", (3,))
    ns = argparse.Namespace
    common = {"inputs": tmp_path / "v18", "extras": tmp_path / "v28", "data": tmp_path / "v51", "procs": 1}
    fac51 = tmp_path / "fac51"
    for g in GROUPS:
        assert V.cmd_factory(ns(group=g, out=fac51 / g, **common)) == 0
    frozen = tmp_path / "frozen.json"
    configs = _frozen(W, fac51, frozen)
    assert len(configs) >= 2
    fac = tmp_path / "fac"
    for g in GROUPS:
        assert W.cmd_factory(ns(group=g, out=fac / g, frozen=frozen, **common)) == 0
    # the same engine on the same events: v52's trades of each frozen configuration are v51's
    for g in GROUPS:
        A51, c51 = V.load_trades(fac51 / g / "trades.npz")
        A52, _ = V.load_trades(fac / g / "trades.npz")
        for c in (c for c in configs if c["group"] == g):
            a = np.sort(A51["r"][A51["cfg"] == c["src"]])
            b = np.sort(A52["r"][A52["cfg"] == c["id"]])
            assert len(a) and np.allclose(a, b)
    S = W.load_holdout(fac, configs)
    assert S["n"] == sum(len(V.load_trades(fac / g / "trades.npz")[0]["t_in"]) for g in GROUPS)
    k = int(S["by_cfg"][configs[0]["id"]][0])
    o = int(S["A"]["off"][k])
    n_mark = int(S["A"]["t_out"][k] - S["A"]["t_in"][k] + 1)
    A0 = V.load_trades(fac / configs[0]["group"] / "trades.npz")[0]
    k0 = int(np.flatnonzero(A0["cfg"] == configs[0]["id"])[0])
    assert np.allclose(S["A"]["mark"][o:o + n_mark], A0["mark"][int(A0["off"][k0]):int(A0["off"][k0]) + n_mark])
    H = W.all_hot(S)
    short = S["A"]["side"] < 0
    assert short.any() and (H["A"]["tier"][short] == 2).all()
    assert (H["A"]["tier"][~short] == S["A"]["tier"][~short]).all()
    assert np.array_equal(H["A"]["loc"][~short], S["A"]["loc"][~short]) and (H["TR"].tier == H["A"]["tier"]).all()
    runs = tmp_path / "runs"
    n_items = len(W.items(json.loads(frozen.read_text(encoding="utf-8"))))
    for s in range(2):
        assert W.cmd_book(ns(factory=fac, shard=s, shards=2, out=runs, frozen=frozen, procs=1)) == 0
    res = V._read_json(runs, "book-*.json")
    assert len(res) == n_items and {"base", "hot5", "borrow2", "loc_never", "loc_half", "hot_all", "half0",
                                    "half1"} <= set(res["H1"]["res"])
    out = tmp_path / "final"
    assert W.cmd_final(ns(factory=fac, runs=runs, out=out, frozen=frozen, procs=1)) == 0
    text = (out / "V52_REPORT.md").read_text(encoding="utf-8")
    assert "# v52 report" in text and "MET" in text
    assert json.loads((out / "v52_summary.json").read_text(encoding="utf-8"))["met"] in (True, False)
