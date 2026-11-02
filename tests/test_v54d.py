"""v54d on v51's synthetic world: every stage runs and the report has a row per entry x exit."""
from __future__ import annotations

import argparse
import json

from test_v24 import _script
from test_v51 import _world


def test_v54d_stages(tmp_path, monkeypatch) -> None:
    MD = _script("run_v51_data", "run_v51_data_v54d")
    D = _script("run_v54d", "run_v54d_under_test")
    _world(tmp_path, MD)
    monkeypatch.setattr(D, "SETUP", "FADE")
    ns = argparse.Namespace
    kw = dict(inputs=tmp_path / "v18", extras=tmp_path / "v28", data=tmp_path / "v51", procs=1, out=tmp_path / "res")
    for cmd in (D.cmd_daily, D.cmd_minute, D.cmd_cover):
        assert cmd(ns(**kw)) == 0
    m = json.loads((tmp_path / "res" / "minute.json").read_text(encoding="utf-8"))
    assert m["events"] > 0
    assert len([k for k in m if k not in ("events", "codes")]) == len(D.ENTRIES) * len(D.TIMES) * len(D.EXITS)
    c = json.loads((tmp_path / "res" / "cover.json").read_text(encoding="utf-8"))
    assert all(v["with_bars"] <= v["events"] for v in c.values())
    assert D.cmd_final(ns(res=tmp_path / "res", out=tmp_path / "final")) == 0
    assert "# v54d report" in (tmp_path / "final" / "V54D_REPORT.md").read_text(encoding="utf-8")
