"""Tests for R182 registry aliases."""
from __future__ import annotations

from pathlib import Path

import pytest

from aurora.registry.aliases import (
    AliasMoveBlocked,
    AliasName,
    AliasRegistry,
)


# ---------------------------------------------------------------------------
# Move + audit
# ---------------------------------------------------------------------------


def test_move_creates_history_entry(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    move = reg.move(
        alias=AliasName.PAPER,
        artefact_kind="strategy",
        to_version="alpha-v1",
        actor="op",
        reason="initial promotion",
    )
    assert move.from_version is None
    assert move.to_version == "alpha-v1"
    assert reg.resolve(artefact_kind="strategy", alias=AliasName.PAPER) == "alpha-v1"


def test_move_records_previous_pointer(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    move2 = reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v2", actor="op", reason="r2",
    )
    assert move2.from_version == "alpha-v1"
    assert reg.resolve(artefact_kind="strategy", alias=AliasName.PAPER) == "alpha-v2"


def test_move_persists_across_instances(tmp_path: Path):
    reg1 = AliasRegistry(tmp_path / "aliases.jsonl")
    reg1.move(
        alias=AliasName.LATEST, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    reg2 = AliasRegistry(tmp_path / "aliases.jsonl")
    assert reg2.resolve(artefact_kind="strategy", alias=AliasName.LATEST) == "alpha-v1"


def test_move_blocks_when_already_points_to_target(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    with pytest.raises(AliasMoveBlocked):
        reg.move(
            alias=AliasName.PAPER, artefact_kind="strategy",
            to_version="alpha-v1", actor="op", reason="r",
        )


def test_move_rejects_empty_to_version(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    with pytest.raises(AliasMoveBlocked):
        reg.move(
            alias=AliasName.PAPER, artefact_kind="strategy",
            to_version="", actor="op", reason="r",
        )


def test_live_promotion_requires_evidence_pack(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    with pytest.raises(AliasMoveBlocked):
        reg.move(
            alias=AliasName.LIVE, artefact_kind="strategy",
            to_version="alpha-v1", actor="op", reason="r",
        )
    move = reg.move(
        alias=AliasName.LIVE, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
        evidence_pack_id="ep-123",
    )
    assert move.evidence_pack_id == "ep-123"


def test_canary_promotion_requires_evidence_pack(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    with pytest.raises(AliasMoveBlocked):
        reg.move(
            alias=AliasName.CANARY, artefact_kind="strategy",
            to_version="alpha-v1", actor="op", reason="r",
        )


# ---------------------------------------------------------------------------
# Multi-kind / state
# ---------------------------------------------------------------------------


def test_state_returns_pointers_for_kind(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.move(
        alias=AliasName.LATEST, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    state = reg.state("strategy")
    assert state.pointers[AliasName.LATEST] == "alpha-v1"
    assert state.pointers[AliasName.PAPER] == "alpha-v1"


def test_kinds_isolated_in_state(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r",
    )
    reg.move(
        alias=AliasName.PAPER, artefact_kind="model",
        to_version="model-v3", actor="op", reason="r",
    )
    assert reg.resolve(artefact_kind="strategy", alias=AliasName.PAPER) == "alpha-v1"
    assert reg.resolve(artefact_kind="model", alias=AliasName.PAPER) == "model-v3"
    assert reg.all_artefact_kinds() == ["model", "strategy"]


def test_history_is_immutable_and_audited(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v1", actor="op", reason="r1",
    )
    reg.move(
        alias=AliasName.PAPER, artefact_kind="strategy",
        to_version="alpha-v2", actor="op", reason="r2",
    )
    history = reg.history(artefact_kind="strategy")
    assert len(history) == 2
    assert [m.to_version for m in history] == ["alpha-v1", "alpha-v2"]
    assert history[1].from_version == "alpha-v1"
    assert history[0].reason == "r1"


def test_retire_helper(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    reg.retire(
        artefact_kind="strategy", version="alpha-v1",
        actor="op", reason="superseded",
    )
    assert reg.resolve(artefact_kind="strategy", alias=AliasName.RETIRED) == "alpha-v1"


def test_resolve_returns_none_when_unset(tmp_path: Path):
    reg = AliasRegistry(tmp_path / "aliases.jsonl")
    assert reg.resolve(artefact_kind="strategy", alias=AliasName.LIVE) is None
