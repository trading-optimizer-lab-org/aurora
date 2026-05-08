"""Tests for quantforge.infra.observability.Observability."""
from __future__ import annotations

import json

import pytest

from quantforge.infra.observability import Observability, ObservabilityConfig


@pytest.fixture
def obs() -> Observability:
    return Observability(ObservabilityConfig(namespace="qf_test"))


def test_inc_counter_accumulates(obs):
    obs.inc_counter("orders_total")
    obs.inc_counter("orders_total", value=2.0)
    assert obs.get_counter("orders_total") == 3.0


def test_set_gauge_overwrites(obs):
    obs.set_gauge("pnl_total", 100.0)
    obs.set_gauge("pnl_total", 250.5)
    assert obs.get_gauge("pnl_total") == 250.5


def test_label_isolation(obs):
    obs.inc_counter("orders_total", labels={"venue": "alpaca"})
    obs.inc_counter("orders_total", labels={"venue": "ibkr"})
    assert obs.get_counter("orders_total", labels={"venue": "alpaca"}) == 1.0
    assert obs.get_counter("orders_total", labels={"venue": "ibkr"}) == 1.0
    # Unlabelled access returns 0; not the same series.
    assert obs.get_counter("orders_total") == 0.0


def test_snapshot_returns_counters_and_gauges(obs):
    obs.inc_counter("rejections_total")
    obs.set_gauge("position_size", -42.0)
    snap = obs.snapshot()
    assert "rejections_total" in snap["counters"]
    assert snap["counters"]["rejections_total"] == 1.0
    assert snap["gauges"]["position_size"] == -42.0


def test_snapshot_formats_labelled_keys(obs):
    obs.inc_counter("fills_total", labels={"sym": "SPY", "side": "BUY"})
    snap = obs.snapshot()
    keys = list(snap["counters"].keys())
    assert any("fills_total{" in k and "sym=SPY" in k and "side=BUY" in k
               for k in keys)


def test_render_grafana_dashboard_shape(obs):
    dash = obs.render_grafana_dashboard("Test")
    assert dash["title"] == "Test"
    assert dash["uid"] == "qf_test-overview"
    assert isinstance(dash["panels"], list)
    assert len(dash["panels"]) >= 6  # 3 counters + 3 gauges


def test_render_grafana_dashboard_includes_namespace(obs):
    dash = obs.render_grafana_dashboard()
    exprs = [t["expr"] for p in dash["panels"] for t in p["targets"]]
    assert any("qf_test_orders_total" in e for e in exprs)


def test_write_grafana_dashboard(tmp_path, obs):
    path = tmp_path / "dash.json"
    obs.write_grafana_dashboard(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "panels" in data
    assert data["uid"] == "qf_test-overview"


def test_default_labels_merge(obs):
    obs.config.labels = {"env": "prod"}
    obs.inc_counter("orders_total")
    # Default label was merged.
    snap = obs.snapshot()
    keys = list(snap["counters"].keys())
    assert any("env=prod" in k for k in keys)
