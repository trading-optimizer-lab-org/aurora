from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_proxy_real_correlation import (
    ProxyCorrelationError,
    audit_proxy_real,
    detect_panel_schema,
    load_proxy_names,
    read_panel_from_frame,
    validate_identity_bridge,
)


def _panel(multiplier: float = 1.0) -> pd.DataFrame:
    rows = []
    for month in pd.period_range("2020-01", periods=12, freq="M"):
        for index in range(10):
            value = float(index + month.month / 100.0)
            rows.append({"permno": index, "yyyymm": month.strftime("%Y%m"), "MetricA": value * multiplier})
    return pd.DataFrame(rows)


def test_wide_panel_is_normalized_without_positional_join() -> None:
    panel = read_panel_from_frame(_panel(), namespace="permno", signals=["MetricA"])
    assert set(panel.columns) == {"entity_id", "month", "signalname", "value"}
    assert panel["entity_id"].iloc[0].startswith("permno:")
    assert panel["month"].nunique() == 12


def test_proxy_real_audit_reports_high_spearman_for_same_signal() -> None:
    official = read_panel_from_frame(_panel(), namespace="permno", signals=["MetricA"])
    proxy = read_panel_from_frame(_panel(), namespace="permno", signals=["MetricA"])
    summary, monthly = audit_proxy_real(
        official,
        proxy,
        signal_names=["MetricA"],
        min_overlap_rows=60,
        min_overlap_months=12,
        correlation_threshold=0.95,
    )
    assert summary.loc[0, "status"] == "pass"
    assert summary.loc[0, "spearman_pooled"] == pytest.approx(1.0)
    assert len(monthly) == 12


def test_proxy_real_audit_rejects_low_correlation() -> None:
    official = read_panel_from_frame(_panel(), namespace="permno", signals=["MetricA"])
    proxy_frame = _panel()
    proxy_frame["MetricA"] = np.tile(np.arange(10, dtype=float)[::-1], 12)
    proxy = read_panel_from_frame(proxy_frame, namespace="permno", signals=["MetricA"])
    summary, _ = audit_proxy_real(
        official,
        proxy,
        signal_names=["MetricA"],
        min_overlap_rows=60,
        min_overlap_months=12,
        correlation_threshold=0.95,
    )
    assert summary.loc[0, "status"] == "fail_threshold"
    assert summary.loc[0, "spearman_pooled"] < 0


def test_missing_entity_or_month_fails_closed() -> None:
    with pytest.raises(ProxyCorrelationError):
        detect_panel_schema(pd.DataFrame({"signalname": ["A"], "value": [1.0]}))


def test_workflow_contract_is_github_only() -> None:
    config = Path("config/openap_proxy_real_correlation.yaml").read_text(encoding="utf-8")
    docs = Path("docs/OPENAP_PROXY_REAL_CORRELATION_AUDIT.md").read_text(encoding="utf-8")
    assert "execution_location: github_actions" in config
    assert "local_runs_allowed: false" in config
    assert "PERMNO" in docs
    assert "no fabrica correlaciones" in docs


def test_ticker_panel_is_rejected_for_historical_correlation() -> None:
    with pytest.raises(ProxyCorrelationError, match="PERMNO"):
        read_panel_from_frame(
            _panel().rename(columns={"permno": "ticker"}),
            namespace="permno",
            signals=["MetricA"],
            require_permno=True,
        )


def test_proxy_names_can_be_recovered_from_current_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.parquet"
    pd.DataFrame(
        {
            "signalname": ["ProxyA", "ProxyB", "ExactA"],
            "status": ["proxy", "proxy", "exact"],
        }
    ).to_parquet(snapshot)
    assert load_proxy_names(None, snapshot=snapshot) == ["ProxyA", "ProxyB"]


def test_identity_bridge_requires_ticker_and_permno(tmp_path: Path) -> None:
    bridge = tmp_path / "bridge.csv"
    pd.DataFrame({"ticker": ["AAA"], "permno": [1], "valid_from": ["2020-01-01"]}).to_csv(
        bridge, index=False
    )
    metadata = validate_identity_bridge(bridge)
    assert metadata["rows"] == 1
    assert metadata["has_valid_from"] is True
