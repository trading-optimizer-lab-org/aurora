"""Tests for quantforge.reporting.daily_ops (P2.B).

Covers:
- DailyOpsConfig defaults and validation
- DailyOpsAlert immutability + severity validation
- DailyOpsReport.has_critical_alerts and round-trip md <-> json
- DailyOpsBuilder section assembly
- Alert checks (drawdown, kill switch, data freshness, regime change,
  drift, validation marker stale)
- No-trade reasoning explanations
- CLI smoke (ops daily / ops alerts / ops summary)

Run::

    cd "C:/Users/HP/MODELO SP500"
    "C:/Python314/python.exe" -m pytest quantforge/tests/test_daily_ops.py -v
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.reporting.daily_ops import (
    DailyOpsAlert,
    DailyOpsBuilder,
    DailyOpsConfig,
    DailyOpsReport,
    DailyOpsSection,
)


# --------------------------------------------------------------------------- #
# Helpers / fixtures                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture
def asof() -> pd.Timestamp:
    return pd.Timestamp("2026-01-15")


@pytest.fixture
def policy() -> ProtocolPolicy:
    return ProtocolPolicy.default()


DEFAULT_ASOF = pd.Timestamp("2026-01-15")


def _make_returns(n: int = 250, asof: pd.Timestamp = DEFAULT_ASOF,
                  seed: int = 42, mu: float = 0.0005,
                  sigma: float = 0.012) -> pd.Series:
    """Synthetic GBM-style daily returns ending at ``asof``."""
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, size=n)
    idx = pd.date_range(end=asof, periods=n, freq="B")
    return pd.Series(r, index=idx, name="returns")


def _make_drawdown_returns(asof: pd.Timestamp,
                           dd_size: float = -0.40) -> pd.Series:
    """Build a returns series with a controlled current drawdown."""
    # Up 50 days, then a big crash to push DD below threshold.
    idx = pd.date_range(end=asof, periods=80, freq="B")
    r = np.zeros(80)
    r[:50] = 0.005  # gentle uptrend
    r[50] = dd_size  # one-day crash
    return pd.Series(r, index=idx, name="returns")


def _basic_inputs(asof: pd.Timestamp) -> dict:
    return {
        "returns": _make_returns(asof=asof),
        "benchmark_returns": _make_returns(asof=asof, seed=7,
                                           mu=0.0003, sigma=0.010),
        "trades": pd.Series(
            [100.0, -20.0, 30.0, -5.0, 80.0],
            index=pd.date_range(end=asof, periods=5, freq="B"),
        ),
        "positions": pd.DataFrame(
            {
                "weight": [0.4, 0.3, 0.2, 0.1, -0.05],
                "sector": ["Tech", "Tech", "Energy", "Health", "Tech"],
            },
            index=["AAPL", "MSFT", "XOM", "JNJ", "TSLA"],
        ),
        "signals": {
            "S1": {
                "state": "long",
                "last_change": asof - pd.Timedelta(days=3),
                "pending": [],
            },
        },
        "regime": {
            "label": "bull",
            "probs": {"bull": 0.7, "neutral": 0.2, "bear": 0.1},
            "days_in_regime": 30,
            "last_transition": asof - pd.Timedelta(days=30),
        },
        "factor_attribution": pd.DataFrame(
            {
                "contrib": [0.012, 0.005, -0.003, -0.008],
                "tstat": [2.3, 1.4, -0.7, -1.6],
            },
            index=["MKT", "SMB", "HML", "MOM"],
        ),
        "no_trade_reasons": {
            "S1": {
                "traded": False,
                "reasons": [
                    {
                        "code": "vol_gate",
                        "detail": "realized vol below threshold",
                        "metric": 0.12,
                        "threshold": 0.15,
                    }
                ],
            }
        },
        "data_freshness": {"last_update": asof - pd.Timedelta(days=0)},
    }


# --------------------------------------------------------------------------- #
# 1. DailyOpsConfig defaults                                                  #
# --------------------------------------------------------------------------- #


def test_daily_ops_config_defaults(asof):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    assert cfg.portfolio_id is None
    assert cfg.output_format == ["md", "json"]
    assert cfg.include_regime is True
    assert cfg.include_attribution is True
    assert cfg.include_alerts is True
    assert cfg.include_no_trade_reasoning is True
    assert cfg.benchmark_symbol == "SPY"


def test_daily_ops_config_rejects_empty_strategies(asof):
    with pytest.raises(ValueError, match="strategies"):
        DailyOpsConfig(asof_date=asof, strategies=[])


def test_daily_ops_config_rejects_bad_format(asof):
    with pytest.raises(ValueError, match="output_format"):
        DailyOpsConfig(asof_date=asof, strategies=["S1"],
                       output_format=["pdf"])


# --------------------------------------------------------------------------- #
# 2. DailyOpsAlert immutability                                               #
# --------------------------------------------------------------------------- #


def test_daily_ops_alert_immutable():
    a = DailyOpsAlert(
        severity="warn", code="X", title="t", detail="d",
        suggested_action="act",
    )
    with pytest.raises(FrozenInstanceError):
        a.severity = "critical"


def test_daily_ops_alert_invalid_severity():
    with pytest.raises(ValueError):
        DailyOpsAlert(severity="emergency", code="X", title="t",
                      detail="d", suggested_action=None)


# --------------------------------------------------------------------------- #
# 3. has_critical_alerts                                                      #
# --------------------------------------------------------------------------- #


def test_has_critical_alerts_true_false():
    base = DailyOpsReport(
        asof_date=pd.Timestamp("2026-01-15"),
        strategies=["S1"], portfolio_id="P", sections=[],
        alerts=[
            DailyOpsAlert(severity="info", code="A", title="t",
                          detail="d", suggested_action=None),
        ],
        summary_one_line="ok",
        policy_hash="abc",
    )
    assert base.has_critical_alerts() is False
    crit = DailyOpsAlert(severity="critical", code="DD", title="t",
                         detail="d", suggested_action=None)
    base2 = DailyOpsReport(
        asof_date=pd.Timestamp("2026-01-15"), strategies=["S1"],
        portfolio_id="P", sections=[], alerts=[crit],
        summary_one_line="bad", policy_hash="abc",
    )
    assert base2.has_critical_alerts() is True


# --------------------------------------------------------------------------- #
# 4. Builder produces report with all sections                                #
# --------------------------------------------------------------------------- #


def test_builder_produces_all_sections(asof, policy):
    cfg = DailyOpsConfig(
        asof_date=asof, strategies=["S1"], portfolio_id="P",
    )
    report = DailyOpsBuilder(cfg, policy, _basic_inputs(asof)).build()
    titles = [s.title for s in report.sections]
    assert "Performance" in titles
    assert "Drawdown" in titles
    assert "Exposure" in titles
    assert "Signals" in titles
    assert "Regime" in titles
    assert "Attribution" in titles
    assert "No-Trade Reasoning" in titles
    assert "Alerts (summary)" in titles
    assert report.policy_hash == policy.policy_hash


# --------------------------------------------------------------------------- #
# 5. Performance section                                                      #
# --------------------------------------------------------------------------- #


def test_performance_section_has_window_metrics(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    report = DailyOpsBuilder(cfg, policy, _basic_inputs(asof)).build()
    perf = next(s for s in report.sections if s.title == "Performance")
    keys = perf.content_json.keys()
    for k in ("daily_pnl_bps", "weekly_pnl_pct", "mtd_pnl_pct",
              "ytd_pnl_pct", "itd_pnl_pct", "sharpe_60d", "sharpe_itd",
              "win_rate_last_20"):
        assert k in keys, f"missing {k}"


# --------------------------------------------------------------------------- #
# 6. Drawdown section                                                         #
# --------------------------------------------------------------------------- #


def test_drawdown_section_reports_current_dd(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["returns"] = _make_drawdown_returns(asof, dd_size=-0.10)
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    dd = next(s for s in report.sections if s.title == "Drawdown")
    cur = dd.content_json["current_drawdown"]
    assert cur < -0.05
    assert dd.content_json["max_dd_itd"] <= cur


# --------------------------------------------------------------------------- #
# 7. Exposure section                                                         #
# --------------------------------------------------------------------------- #


def test_exposure_section_sums_for_invested_book(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    exp = next(s for s in report.sections if s.title == "Exposure")
    payload = exp.content_json
    # Gross = sum |w| = 0.4 + 0.3 + 0.2 + 0.1 + 0.05 = 1.05
    assert payload["gross_exposure"] == pytest.approx(1.05, abs=1e-9)
    # Net = sum w = 0.4 + 0.3 + 0.2 + 0.1 - 0.05 = 0.95
    assert payload["net_exposure"] == pytest.approx(0.95, abs=1e-9)
    assert len(payload["top_5"]) == 5


# --------------------------------------------------------------------------- #
# 8. Signals section                                                          #
# --------------------------------------------------------------------------- #


def test_signals_section_reflects_strategy_state(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1", "S2"])
    inputs = _basic_inputs(asof)
    inputs["signals"] = {
        "S1": {"state": "long", "last_change": asof,
               "pending": ["enter_short"]},
        "S2": {"state": "flat", "last_change": asof - pd.Timedelta(days=10),
               "pending": []},
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    sig = next(s for s in report.sections if s.title == "Signals")
    rows = sig.content_json["strategies"]
    assert {r["strategy_id"] for r in rows} == {"S1", "S2"}
    s1 = next(r for r in rows if r["strategy_id"] == "S1")
    assert s1["state"] == "long"
    assert s1["pending"] == ["enter_short"]


# --------------------------------------------------------------------------- #
# 9. Regime section                                                           #
# --------------------------------------------------------------------------- #


def test_regime_section_returns_current_regime(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    reg = next(s for s in report.sections if s.title == "Regime")
    assert reg.content_json["label"] == "bull"
    assert reg.content_json["days_in_regime"] == 30
    assert "bull" in reg.content_json["probs"]


# --------------------------------------------------------------------------- #
# 10. Attribution section                                                     #
# --------------------------------------------------------------------------- #


def test_attribution_section_non_empty_when_configured(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    report = DailyOpsBuilder(cfg, policy, _basic_inputs(asof)).build()
    attr = next(s for s in report.sections if s.title == "Attribution")
    rows = attr.content_json["rows"]
    assert len(rows) == 4
    assert len(attr.content_json["top_contributors"]) > 0
    assert len(attr.content_json["top_detractors"]) > 0


# --------------------------------------------------------------------------- #
# 11-14. No-trade reasoning explanations                                      #
# --------------------------------------------------------------------------- #


def test_no_trade_reasoning_explains_vol_gate(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["no_trade_reasons"] = {
        "S1": {
            "traded": False,
            "reasons": [{
                "code": "vol_gate",
                "detail": "realized_vol=12% below threshold=15%",
                "metric": 0.12, "threshold": 0.15,
            }]
        }
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    nt = next(s for s in report.sections if s.title == "No-Trade Reasoning")
    assert "vol_gate" in nt.content_md
    assert "12%" in nt.content_md or "0.12" in nt.content_md


def test_no_trade_reasoning_explains_cooldown(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S2"])
    inputs = _basic_inputs(asof)
    inputs["no_trade_reasons"] = {
        "S2": {
            "traded": False,
            "reasons": [{
                "code": "cooldown",
                "detail": "last trade 2 days ago, min interval=5",
            }]
        }
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    nt = next(s for s in report.sections if s.title == "No-Trade Reasoning")
    assert "cooldown" in nt.content_md
    assert "5" in nt.content_md


def test_no_trade_reasoning_explains_regime_mismatch(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S3"])
    inputs = _basic_inputs(asof)
    inputs["no_trade_reasons"] = {
        "S3": {
            "traded": False,
            "reasons": [{
                "code": "regime_mismatch",
                "detail": "current regime=bear, strategy requires bull",
            }]
        }
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    nt = next(s for s in report.sections if s.title == "No-Trade Reasoning")
    assert "regime_mismatch" in nt.content_md
    assert "bear" in nt.content_md and "bull" in nt.content_md


def test_no_trade_reasoning_explains_validation_marker_stale(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S4"])
    inputs = _basic_inputs(asof)
    inputs["no_trade_reasons"] = {
        "S4": {
            "traded": False,
            "reasons": [{
                "code": "validation_marker_stale",
                "detail": "marker mtime=2025-01-01 > 365d threshold",
            }]
        }
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    nt = next(s for s in report.sections if s.title == "No-Trade Reasoning")
    assert "validation_marker_stale" in nt.content_md


# --------------------------------------------------------------------------- #
# 15. Drawdown breach alert                                                   #
# --------------------------------------------------------------------------- #


def test_alert_drawdown_breach_detected(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    # Fabricate a -50% drawdown to breach the 30% policy threshold.
    inputs["returns"] = _make_drawdown_returns(asof, dd_size=-0.50)
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    crits = [a for a in report.alerts if a.code == "DD_BREACH"]
    assert len(crits) == 1
    assert crits[0].severity == "critical"
    assert report.has_critical_alerts() is True


# --------------------------------------------------------------------------- #
# 16. Kill switch alert                                                       #
# --------------------------------------------------------------------------- #


def test_alert_kill_switch_triggered(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["kill_switch"] = {"triggered": True, "reason": "max_daily_loss"}
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    ks = [a for a in report.alerts if a.code == "KILL_SWITCH"]
    assert len(ks) == 1 and ks[0].severity == "critical"


# --------------------------------------------------------------------------- #
# 17. Data freshness alert                                                    #
# --------------------------------------------------------------------------- #


def test_alert_data_freshness_stale(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["data_freshness"] = {
        "last_update": asof - pd.Timedelta(days=5),
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    df = [a for a in report.alerts if a.code == "DATA_STALE"]
    assert len(df) == 1 and df[0].severity == "warn"


# --------------------------------------------------------------------------- #
# 18. Regime change alert                                                     #
# --------------------------------------------------------------------------- #


def test_alert_regime_change_detected(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["regime"]["last_transition"] = asof  # today
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    rc = [a for a in report.alerts if a.code == "REGIME_CHANGE"]
    assert len(rc) == 1 and rc[0].severity == "info"


# --------------------------------------------------------------------------- #
# 19. Drift alert                                                             #
# --------------------------------------------------------------------------- #


def test_alert_drift_breach_detected(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["drift"] = {
        "breached": True, "detector": "page_hinkley",
        "stat": 60.0, "threshold": 50.0,
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    d = [a for a in report.alerts if a.code == "DRIFT_DETECTED"]
    assert len(d) == 1 and d[0].severity == "warn"


# --------------------------------------------------------------------------- #
# 20. Validation marker stale alert                                           #
# --------------------------------------------------------------------------- #


def test_alert_validation_marker_stale(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"])
    inputs = _basic_inputs(asof)
    inputs["validation_marker"] = {
        "path": "/tmp/marker.json",
        "mtime": asof - pd.Timedelta(days=4000),  # very old
    }
    report = DailyOpsBuilder(cfg, policy, inputs).build()
    vm = [a for a in report.alerts if a.code == "VALIDATION_MARKER_STALE"]
    assert len(vm) == 1 and vm[0].severity == "critical"


# --------------------------------------------------------------------------- #
# 21. Markdown <-> JSON round-trip                                            #
# --------------------------------------------------------------------------- #


def test_to_markdown_and_to_json_roundtrip(asof, policy):
    cfg = DailyOpsConfig(asof_date=asof, strategies=["S1"], portfolio_id="P")
    report = DailyOpsBuilder(cfg, policy, _basic_inputs(asof)).build()

    md1 = report.to_markdown()
    js1 = report.to_json()
    parsed = json.loads(js1)

    # Markdown must contain the asof date.
    assert "2026-01-15" in md1
    # JSON has the same sections/alerts as the report.
    assert len(parsed["sections"]) == len(report.sections)
    assert len(parsed["alerts"]) == len(report.alerts)
    assert parsed["policy_hash"] == policy.policy_hash

    # Round-trip determinism: rebuild a report and compare its renderings.
    report2 = DailyOpsBuilder(cfg, policy, _basic_inputs(asof)).build()
    assert report2.to_markdown() == md1
    assert report2.to_json() == js1


# --------------------------------------------------------------------------- #
# 22. CLI smoke: forge ops daily / alerts / summary                           #
# --------------------------------------------------------------------------- #


def test_cli_ops_smoke(tmp_path, capsys):
    """Smoke test: forge ops daily / alerts / summary all run end-to-end."""
    from aurora.cli import forge as cli

    out_dir = tmp_path / "reports"
    rc_daily = cli.main([
        "ops", "daily",
        "--asof", "2026-01-15",
        "--strategies", "S1",
        "--portfolio", "P",
        "--format", "md,json",
        "--output-dir", str(out_dir),
    ])
    assert rc_daily in (0, 1)  # exit 1 only if a critical alert fires.
    out = capsys.readouterr().out
    assert "Daily Operations Report" in out
    # Wrote the artifacts to disk.
    md_files = list(out_dir.glob("daily_*.md"))
    json_files = list(out_dir.glob("daily_*.json"))
    assert md_files and json_files

    rc_alerts = cli.main([
        "ops", "alerts",
        "--asof", "2026-01-15",
        "--strategies", "S1",
        "--severity", "info",
        "--json",
    ])
    out_alerts = capsys.readouterr().out
    assert rc_alerts in (0, 1)
    # JSON output should be parseable.
    json.loads(out_alerts)

    rc_summary = cli.main([
        "ops", "summary",
        "--asof", "2026-01-15",
        "--strategies", "S1",
        "--portfolio", "P",
    ])
    assert rc_summary == 0
    out_summary = capsys.readouterr().out.strip()
    assert "2026-01-15" in out_summary
