"""Tests for aurora.ml.vector_db_papers."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.ml.vector_db_papers import (
    PapersVectorDB,
    PapersVectorDBConfig,
)


@pytest.fixture
def db():
    return PapersVectorDB(PapersVectorDBConfig(embedding_dim=32))


def _papers():
    return [
        {"id": "p1", "title": "Triple barrier", "abstract": "tp sl horizon labels triple barrier"},
        {"id": "p2", "title": "Meta-labelling", "abstract": "meta-labelling precision"},
        {"id": "p3", "title": "Microstructure", "abstract": "kyle lambda amihud illiquidity"},
    ]


def test_constructor_validates():
    with pytest.raises(ValueError):
        PapersVectorDB(PapersVectorDBConfig(embedding_dim=2))


def test_add_and_len(db):
    n = db.add_papers(_papers())
    assert n == 3
    assert len(db) == 3


def test_add_validates(db):
    with pytest.raises(TypeError):
        db.add_papers("not-a-list")
    with pytest.raises(TypeError):
        db.add_papers([1, 2, 3])
    with pytest.raises(ValueError):
        db.add_papers([{"id": "x"}])


def test_search_relevance(db):
    db.add_papers(_papers())
    hits = db.search("triple barrier method", k=2)
    ids = [h["id"] for h in hits]
    assert "p1" in ids
    # Each hit has a score
    for h in hits:
        assert "score" in h
        assert isinstance(h["score"], float)


def test_search_validates(db):
    db.add_papers(_papers())
    with pytest.raises(ValueError):
        db.search("")
    with pytest.raises(ValueError):
        db.search("a", k=0)


def test_search_empty():
    d = PapersVectorDB(PapersVectorDBConfig(embedding_dim=16))
    assert d.search("anything") == []


def test_get(db):
    db.add_papers(_papers())
    p = db.get("p2")
    assert p is not None and p["title"] == "Meta-labelling"
    assert db.get("missing") is None
