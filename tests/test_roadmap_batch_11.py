"""Tests for R39, R44, R142 (Batch 11)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.ml.degradation_forecaster import (
    DegradationForecaster,
    StrategySnapshot,
)
from aurora.research.factory.spec_signing import (
    SpecSignature,
    canonical_spec_hash,
    sign_spec,
    verify_spec,
)
from aurora.research.graveyard import (
    GraveyardEntry,
    filter_graveyard,
    format_table,
    read_graveyard,
)


# --------------------------------------------------------------------------
# R39 graveyard
# --------------------------------------------------------------------------


def _write_archive(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_read_graveyard_filters_to_rejection_events(tmp_path: Path):
    p = tmp_path / "archive.jsonl"
    _write_archive(p, [
        {"event": "promoted", "strategy_id": "alpha", "version": "v1",
         "timestamp": "2026-01-01"},
        {"event": "rejected", "strategy_id": "beta", "version": "v1",
         "reason": "PBO too high", "timestamp": "2026-02-01"},
        {"event": "archived", "strategy_id": "gamma", "version": "v3",
         "reason": "SLA expired", "timestamp": "2026-03-01"},
    ])
    out = read_graveyard(p)
    assert len(out) == 2
    ids = {e.strategy_id for e in out}
    assert ids == {"beta", "gamma"}


def test_read_graveyard_missing_file_returns_empty():
    assert read_graveyard(Path("/nonexistent/archive.jsonl")) == []


def test_filter_graveyard_by_family(tmp_path: Path):
    entries = [
        GraveyardEntry(strategy_id="a", version="v1", rejection_reason="x",
                       rejected_at="2026-01-01", family="momentum"),
        GraveyardEntry(strategy_id="b", version="v1", rejection_reason="y",
                       rejected_at="2026-01-02", family="mean_rev"),
    ]
    out = filter_graveyard(entries, family="momentum")
    assert len(out) == 1
    assert out[0].strategy_id == "a"


def test_filter_graveyard_by_reason_substring():
    entries = [
        GraveyardEntry(strategy_id="a", version="v1",
                       rejection_reason="PBO above threshold",
                       rejected_at="2026-01-01"),
        GraveyardEntry(strategy_id="b", version="v1",
                       rejection_reason="SLA expired",
                       rejected_at="2026-01-02"),
    ]
    out = filter_graveyard(entries, reason_substring="pbo")
    assert len(out) == 1
    assert out[0].strategy_id == "a"


def test_format_table_includes_header():
    entries = [
        GraveyardEntry(strategy_id="alpha", version="v1",
                       rejection_reason="reason",
                       rejected_at="2026-01-01"),
    ]
    out = format_table(entries)
    assert "strategy_id" in out
    assert "alpha" in out


# --------------------------------------------------------------------------
# R44 spec signing
# --------------------------------------------------------------------------


def test_canonical_spec_hash_is_stable_across_key_order():
    a = canonical_spec_hash({"alpha": 1, "beta": 2})
    b = canonical_spec_hash({"beta": 2, "alpha": 1})
    assert a == b


def test_sign_and_verify_round_trip():
    key = b"dev-secret-1"
    payload = {"name": "alpha", "params": {"window": 20}}
    sig = sign_spec(signer_id="dev1", spec_payload=payload, operator_key=key)
    verify_spec(
        signature=sig,
        spec_payload=payload,
        key_registry={"dev1": key},
    )


def test_verify_spec_rejects_unknown_signer():
    payload = {"name": "alpha"}
    sig = sign_spec(signer_id="dev1", spec_payload=payload, operator_key=b"k")
    with pytest.raises(KeyError):
        verify_spec(
            signature=sig,
            spec_payload=payload,
            key_registry={"dev2": b"k"},
        )


def test_verify_spec_rejects_tampered_payload():
    key = b"k"
    payload = {"name": "alpha", "param": 10}
    sig = sign_spec(signer_id="dev1", spec_payload=payload, operator_key=key)
    tampered = {"name": "alpha", "param": 99}
    with pytest.raises(ValueError):
        verify_spec(
            signature=sig,
            spec_payload=tampered,
            key_registry={"dev1": key},
        )


def test_verify_spec_rejects_wrong_key():
    payload = {"name": "alpha"}
    sig = sign_spec(signer_id="dev1", spec_payload=payload, operator_key=b"k1")
    with pytest.raises(ValueError):
        verify_spec(
            signature=sig,
            spec_payload=payload,
            key_registry={"dev1": b"k2"},
        )


def test_sign_spec_empty_signer_raises():
    with pytest.raises(ValueError):
        sign_spec(signer_id="", spec_payload={}, operator_key=b"k")


def test_sign_spec_empty_key_raises():
    with pytest.raises(ValueError):
        sign_spec(signer_id="dev1", spec_payload={}, operator_key=b"")


# --------------------------------------------------------------------------
# R142 degradation forecaster
# --------------------------------------------------------------------------


def _labelled_snapshot(sid, sharpe, calmar, mdd, regime, n_params, label):
    return StrategySnapshot(
        strategy_id=sid,
        early_sharpe=sharpe,
        early_calmar=calmar,
        early_max_drawdown=mdd,
        regime_tag=regime,
        n_params=n_params,
        months_until_degradation=label,
    )


def test_forecaster_fit_predict_round_trip():
    snaps = [
        _labelled_snapshot(f"s{i}",
                           sharpe=1.0 + 0.1 * i,
                           calmar=0.5 + 0.05 * i,
                           mdd=-0.10 - 0.01 * i,
                           regime="trending",
                           n_params=5,
                           label=10.0 + i)
        for i in range(10)
    ]
    fc = DegradationForecaster()
    fc.fit(snaps)
    pred = fc.predict(snaps[0])
    # Predicted lifetime should be a finite number close to the labelled
    # range.
    assert 0.0 < pred < 100.0


def test_forecaster_too_few_snapshots_raises():
    snaps = [
        _labelled_snapshot("s1", 1.0, 0.5, -0.1, "trending", 5, 12.0),
        _labelled_snapshot("s2", 1.1, 0.6, -0.1, "trending", 5, 14.0),
    ]
    fc = DegradationForecaster()
    with pytest.raises(ValueError):
        fc.fit(snaps)


def test_forecaster_predict_before_fit_raises():
    fc = DegradationForecaster()
    with pytest.raises(RuntimeError):
        fc.predict(_labelled_snapshot("x", 1.0, 0.5, -0.1, "trending", 5, None))


def test_forecaster_rank_orders_by_predicted_lifetime():
    snaps = [
        _labelled_snapshot(f"s{i}",
                           sharpe=0.5 + 0.5 * i,
                           calmar=0.2 + 0.1 * i,
                           mdd=-0.20 + 0.01 * i,
                           regime="trending",
                           n_params=4,
                           label=5.0 + 2.0 * i)
        for i in range(10)
    ]
    fc = DegradationForecaster()
    fc.fit(snaps)
    ranked = fc.rank(snaps)
    # Highest-Sharpe snapshot should rank in the top half.
    top = [s.strategy_id for s in ranked[:5]]
    assert "s9" in top
