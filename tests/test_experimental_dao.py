"""Tests for DAOGovernance ledger."""
from __future__ import annotations

import pytest

from quantforge.experimental.dao_governance import DAOGovernance


def test_create_and_list_proposal(tmp_path):
    dao = DAOGovernance(db_path=tmp_path / "dao.db")
    pid = dao.create_proposal(title="Promote strategy X", body="...")
    proposals = dao.list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["id"] == pid
    assert proposals[0]["title"] == "Promote strategy X"
    dao.close()


def test_tally_passes_with_quorum_and_majority(tmp_path):
    dao = DAOGovernance(
        db_path=tmp_path / "dao.db", quorum=0.5, approval_threshold=0.5
    )
    pid = dao.create_proposal("p")
    dao.vote(pid, "alice", weight=1.0, approve=True)
    dao.vote(pid, "bob", weight=1.0, approve=True)
    dao.vote(pid, "carol", weight=1.0, approve=False)
    res = dao.tally(pid, total_weight=4.0)
    assert res["participation"] == 0.75
    assert res["yes_share"] == pytest.approx(2 / 3)
    assert res["passed"] is True
    dao.close()


def test_tally_fails_below_quorum(tmp_path):
    dao = DAOGovernance(db_path=tmp_path / "dao.db", quorum=0.8)
    pid = dao.create_proposal("p")
    dao.vote(pid, "alice", weight=1.0, approve=True)
    res = dao.tally(pid, total_weight=10.0)
    assert res["participation"] == 0.1
    assert res["passed"] is False
    dao.close()


def test_vote_replaces_existing_voter_record(tmp_path):
    dao = DAOGovernance(db_path=tmp_path / "dao.db")
    pid = dao.create_proposal("p")
    dao.vote(pid, "alice", weight=1.0, approve=False)
    dao.vote(pid, "alice", weight=1.0, approve=True)  # change of mind
    res = dao.tally(pid, total_weight=1.0)
    assert res["yes_share"] == 1.0
    assert res["n_votes"] == 1
    dao.close()


def test_vote_rejects_non_positive_weight(tmp_path):
    dao = DAOGovernance(db_path=tmp_path / "dao.db")
    pid = dao.create_proposal("p")
    with pytest.raises(ValueError):
        dao.vote(pid, "alice", weight=0.0, approve=True)
    dao.close()


def test_constructor_validates_thresholds(tmp_path):
    with pytest.raises(ValueError):
        DAOGovernance(db_path=tmp_path / "x.db", quorum=0.0)
    with pytest.raises(ValueError):
        DAOGovernance(db_path=tmp_path / "x.db", approval_threshold=1.5)
