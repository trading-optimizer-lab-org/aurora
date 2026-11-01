"""v53 checks on v51's synthetic world: joining two event folders, and the whole walk-forward pipeline, where every
test year's book is chosen from the years before it only."""
from __future__ import annotations

import argparse
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from test_v24 import _script
from test_v51 import _world

GROUPS = ("GAPUP-short", "STRONG-long", "RUN40-short")


@pytest.fixture(scope="module")
def W():
    return _script("run_v53", "run_v53_under_test")


@pytest.fixture(scope="module")
def MD():
    return _script("run_v51_data", "run_v51_data_v53")


def test_merge_joins_overlapping_days(W, MD, tmp_path) -> None:
    _world(tmp_path, MD)
    a, b = tmp_path / "v51", tmp_path / "b"
    (b / "minutes").mkdir(parents=True)
    ev = pd.read_parquet(a / "events.parquet")
    ev.iloc[: len(ev) // 3].to_parquet(b / "events.parquet")
    (b / "census.json").write_text(json.dumps({"hold": 3}), encoding="utf-8")
    days = sorted((a / "minutes").glob("*.parquet"))
    for p in days[:3]:
        df = pd.read_parquet(p)
        df[df["symbol"].astype(str) == str(df["symbol"].iloc[0])].to_parquet(b / "minutes" / p.name)
    out = tmp_path / "m"
    assert W.cmd_merge(argparse.Namespace(src=[a, b], out=out, move=False, procs=1)) == 0
    assert len(pd.read_parquet(out / "events.parquet")) == len(ev)
    assert len(list((out / "minutes").glob("*.parquet"))) == len(days)
    x, y = (pd.read_parquet(d / "minutes" / days[0].name) for d in (a, out))
    assert len(x) == len(y) and set(x["symbol"].astype(str)) == set(y["symbol"].astype(str))


@pytest.mark.slow
def test_walk_forward_pipeline(W, MD, tmp_path, monkeypatch) -> None:
    _world(tmp_path, MD)
    V = W.V
    for k, v in {"PATHS": 200, "Y0": 2021, "NPER": 3}.items():
        monkeypatch.setattr(V, k, v)
    for k, v in {"FIRST": pd.Timestamp("2021-08-02"), "TEST_YEARS": (2022, 2023), "SEL_YEARS": (2022,),
                 "LOCK_YEARS": (2023,), "WINDOWS": {"exp": None, "roll1": 1}, "TOP_ENTRY": 5, "TOP_GROUP": 2,
                 "TOP_CTX": 3, "SIZES": (0.2,), "NEWS": (3,), "SINGLES": 2, "BOOK_SIZES": (0.2,),
                 "SEEDS_SEL": (0,), "SEEDS_OOS": (0, 1), "SEEDS_STRESS": (0,)}.items():
        monkeypatch.setattr(W, k, v)
    assert W.contexts() == ["2021-2021|raw", "2021-2021|cap25", "2021-2022|raw", "2021-2022|cap25",
                            "2022-2022|raw", "2022-2022|cap25"]
    assert W.proc_ctx("roll1/cap25/r10", 2023) == "2022-2022|cap25"
    ns = argparse.Namespace
    data = tmp_path / "v53"
    shutil.copytree(tmp_path / "v51", data)
    fac = tmp_path / "fac"
    for g in GROUPS:
        assert W.cmd_factory(ns(group=g, inputs=tmp_path / "v18", extras=tmp_path / "v28", data=data,
                                out=fac / g, procs=1)) == 0
    rep = json.loads((fac / GROUPS[0] / "report.json").read_text(encoding="utf-8"))
    assert rep["n_scored"] > 0 and rep["contexts"]
    sel = tmp_path / "sel"
    assert W.cmd_select(ns(factory=fac, out=sel, procs=1)) == 0
    ctxs = json.loads((sel / "contexts.json").read_text(encoding="utf-8"))
    assert ctxs and all(len(v) <= 3 for v in ctxs.values())
    # a context's paths come from its training years only
    S = W.load_sel(sel)
    ix = W.ctx_S(S, "2021-2021|raw")["idx"]["train"]
    assert set(np.unique(S["years"][ix])) == {2021}
    runs = tmp_path / "runs"
    for s in range(2):
        assert W.cmd_account(ns(sel=sel, shard=s, shards=2, out=runs / "acc", procs=1)) == 0
    picks = tmp_path / "picks"
    assert W.cmd_pick(ns(runs=runs / "acc", out=picks, procs=1)) == 0
    assert W.cmd_books(ns(sel=sel, picks=picks, shard=0, shards=1, out=runs / "books", procs=1)) == 0
    ch = tmp_path / "choose"
    assert W.cmd_choose(ns(acc=runs / "acc", books=runs / "books", out=ch, procs=1)) == 0
    chosen = json.loads((ch / "choose.json").read_text(encoding="utf-8"))
    for s in range(len(chosen["books"]) + 1):
        assert W.cmd_oos(ns(sel=sel, choose=ch, shard=s, shards=len(chosen["books"]) + 1, out=runs / "oos",
                            procs=1)) == 0
    out = tmp_path / "final"
    assert W.cmd_final(ns(factory=fac, sel=sel, choose=ch, oos=runs / "oos", out=out, procs=1)) == 0
    assert "# v53 report" in (out / "V53_REPORT.md").read_text(encoding="utf-8")
    summ = json.loads((out / "v53_summary.json").read_text(encoding="utf-8"))
    assert set(summ["grades"]) == set(W.procedures())
    # v53b: the same books at smaller sizes; scale 1 repeats v53's returns, smaller scales shrink them
    B = _script("run_v53b", "run_v53b_under_test")
    for k, v in {"SCALES": (1.0, 0.5), "W": W, "V": V}.items():
        monkeypatch.setattr(B, k, v)
    nb = len(chosen["books"])
    for s in range(3):
        assert B.cmd_oos(ns(sel=sel, choose=ch, shard=s, shards=3, out=runs / "oosb", procs=1)) == 0
    assert len(list((runs / "oosb").glob("oos-*.npz"))) == 2 * nb
    for b in range(nb):
        full, half, ref = (np.load(runs / p) for p in (f"oosb/oos-{b}-1.00.npz", f"oosb/oos-{b}-0.50.npz",
                                                          f"oos/oos-{b}.npz"))
        assert np.allclose(full["base"], ref["base"])
        assert np.abs(half["base"]).sum() < np.abs(full["base"]).sum()
    outb = tmp_path / "finalb"
    assert B.cmd_final(ns(choose=ch, oos=runs / "oosb", out=outb, procs=1)) == 0
    sb = json.loads((outb / "v53b_summary.json").read_text(encoding="utf-8"))
    assert len(sb["grades"]) == 2 * len(W.procedures())
    assert sb["grades"]["exp/raw/r25@1.00"]["base"] == summ["grades"]["exp/raw/r25"]["base"]
    # v53c: each year's scale from the procedure's earlier years only; the first year takes START
    C = _script("run_v53c", "run_v53c_under_test")
    for k, v in {"B": B, "W": W, "V": V, "E": W.E, "START": 0.5, "HIST_SEEDS": (0,)}.items():
        monkeypatch.setattr(C, k, v)
    outc = tmp_path / "finalc"
    assert C.cmd_final(ns(choose=ch, oos=runs / "oosb", out=outc)) == 0
    sc = json.loads((outc / "v53c_summary.json").read_text(encoding="utf-8"))
    assert len(sc["grades"]) == 2 * len(W.procedures())
    for proc in W.procedures():
        s = sc["scales"][f"{proc}/safe"]
        assert s["2022"] == (0.5 if chosen["chosen"][proc]["2022"] else None)
        assert s["2023"] in (None, 1.0, 0.5)
