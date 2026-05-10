"""Tests for R166 reproducible evidence pack."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.reporting.evidence_pack import (
    ArtefactReference,
    build_dataset_pack,
    build_strategy_pack,
    compute_pack_hash,
    load_pack,
    verify_artefact_files,
    verify_pack,
    write_pack,
)


def _dataset_pack():
    return build_dataset_pack(
        dataset_name="seed_universe_v1",
        policy_hash="p1",
        snapshot_hash="s1",
        manifest={"asset_class": "etf"},
        requested_symbols=["SPY", "IEF"],
        persisted_symbols=["SPY"],
        provider_provenance=[{"provider": "yahoo", "asof": "2026-01-01"}],
        data_contract_results=[{"name": "ohlcv_v1", "passed": True}],
        quality_decisions=[{"symbol": "SPY", "decision": "approved"}],
        identity_resolved=["SPY"],
        identity_unresolved=["IEF"],
        identity_ambiguous=[],
        corporate_action_status={"SPY": "no events"},
        snapshots=[{"path": "snap.parquet", "hash": "abc"}],
        warnings=["IEF missing identity record"],
        reproduce_commands=["aurora data fetch yahoo SPY --output spy.parquet"],
    )


def _strategy_pack():
    return build_strategy_pack(
        strategy_id="alpha",
        policy_hash="p1",
        snapshot_hash="s1",
        validation_report={"sharpe": 1.2, "passes_gates": True},
        benchmark_pack={"primary_baseline": "buy_and_hold", "verdict": "beats"},
        manifest={"strategy_version": "v1"},
        research_ledger_excerpt=[{"event": "validation_run"}],
        quality_decisions=[{"symbol": "SPY", "decision": "approved"}],
        provider_provenance=[{"provider": "yahoo"}],
        requested_symbols=["SPY"],
        persisted_symbols=["SPY"],
        identity_resolved=["SPY"],
        warnings=[],
        reproduce_commands=["aurora validate alpha"],
    )


# ---------------------------------------------------------------------------
# Build + serialise
# ---------------------------------------------------------------------------


def test_dataset_pack_includes_required_sections():
    pack = _dataset_pack()
    assert pack.pack_kind == "dataset"
    assert pack.subject_id == "seed_universe_v1"
    assert pack.policy_hash == "p1"
    assert pack.requested_vs_persisted["missing"] == ["IEF"]
    assert pack.identity_status["unresolved"] == ["IEF"]
    assert pack.pack_hash != ""


def test_strategy_pack_carries_validation_and_benchmark_blocks():
    pack = _strategy_pack()
    assert pack.pack_kind == "strategy"
    assert pack.validation_report["sharpe"] == 1.2
    assert pack.benchmark_pack["verdict"] == "beats"


def test_pack_hash_is_deterministic():
    a = build_dataset_pack(
        dataset_name="x", policy_hash="p", snapshot_hash="s",
        manifest={}, requested_symbols=[], persisted_symbols=[],
        provider_provenance=[], data_contract_results=[],
        quality_decisions=[], identity_resolved=[], identity_unresolved=[],
        identity_ambiguous=[], corporate_action_status={}, snapshots=[],
        pack_id="fixed",
    )
    b = build_dataset_pack(
        dataset_name="x", policy_hash="p", snapshot_hash="s",
        manifest={}, requested_symbols=[], persisted_symbols=[],
        provider_provenance=[], data_contract_results=[],
        quality_decisions=[], identity_resolved=[], identity_unresolved=[],
        identity_ambiguous=[], corporate_action_status={}, snapshots=[],
        pack_id="fixed",
    )
    # The generated_at timestamps differ; recompute deterministic core hash
    # by zeroing them out.
    a_payload = a.to_dict()
    b_payload = b.to_dict()
    a_payload["generated_at"] = "0"
    b_payload["generated_at"] = "0"
    a_payload.pop("pack_hash")
    b_payload.pop("pack_hash")
    assert json.dumps(a_payload, sort_keys=True) == json.dumps(b_payload, sort_keys=True)


def test_to_markdown_mentions_subject_and_pack_hash():
    pack = _dataset_pack()
    md = pack.to_markdown()
    assert "seed_universe_v1" in md
    assert "pack_hash" in md


def test_compute_pack_hash_excludes_stored_pack_hash():
    pack = _dataset_pack()
    h1 = compute_pack_hash(pack)
    # Replace pack_hash with a different stored value -- recompute should
    # remain stable because it ignores the stored hash field.
    from dataclasses import replace
    altered = replace(pack, pack_hash="deadbeef")
    h2 = compute_pack_hash(altered)
    assert h1 == h2


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verify_pack_passes_for_clean_pack():
    pack = _dataset_pack()
    ok, problems = verify_pack(pack)
    assert ok is True
    assert problems == []


def test_verify_pack_detects_tampered_pack_hash():
    from dataclasses import replace
    pack = _dataset_pack()
    tampered = replace(pack, pack_hash="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
    ok, problems = verify_pack(tampered)
    assert ok is False
    assert "mismatch" in problems[0]


def test_verify_artefact_files_detects_missing(tmp_path: Path):
    pack = _dataset_pack()
    # Inject an artefact pointing at a non-existent file.
    from dataclasses import replace
    art = ArtefactReference(
        role="snapshot",
        location=str(tmp_path / "missing.bin"),
        content_hash="0" * 64,
    )
    pack = replace(pack, artefacts=(art,))
    out = verify_artefact_files(pack)
    assert any("missing" in p for p in out)


def test_verify_artefact_files_detects_hash_mismatch(tmp_path: Path):
    payload = b"hello"
    file_path = tmp_path / "data.bin"
    file_path.write_bytes(payload)
    real_hash = hashlib.sha256(payload).hexdigest()
    # Reference with a deliberately wrong hash.
    art = ArtefactReference(
        role="snapshot", location=str(file_path), content_hash="0" * 64,
    )
    from dataclasses import replace
    pack = replace(_dataset_pack(), artefacts=(art,))
    out = verify_artefact_files(pack)
    assert out
    assert "hash mismatch" in out[0]
    # Now flip to the real hash and confirm clean.
    art2 = ArtefactReference(
        role="snapshot", location=str(file_path), content_hash=real_hash,
    )
    pack2 = replace(_dataset_pack(), artefacts=(art2,))
    assert verify_artefact_files(pack2) == []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_write_and_load_round_trip(tmp_path: Path):
    pack = _strategy_pack()
    paths = write_pack(pack, tmp_path)
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    loaded = load_pack(paths["json"])
    assert loaded.subject_id == pack.subject_id
    assert loaded.pack_hash == pack.pack_hash
    assert loaded.benchmark_pack["verdict"] == "beats"


def test_load_pack_round_trips_artefacts(tmp_path: Path):
    payload = b"some bytes"
    file_path = tmp_path / "snap.bin"
    file_path.write_bytes(payload)
    art = ArtefactReference(
        role="snapshot",
        location=str(file_path),
        content_hash=hashlib.sha256(payload).hexdigest(),
    )
    from dataclasses import replace
    pack = replace(_dataset_pack(), artefacts=(art,))
    paths = write_pack(pack, tmp_path)
    loaded = load_pack(paths["json"])
    assert loaded.artefacts[0].role == "snapshot"
    assert loaded.artefacts[0].content_hash == art.content_hash
