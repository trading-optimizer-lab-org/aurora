"""Tests for quantforge.ml.rag_research."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.ml.rag_research import (
    RAGConfig,
    RAGResearchAssistant,
    MockLLM,
)


@pytest.fixture
def assistant():
    return RAGResearchAssistant(
        client=MockLLM(reply_text="meta-labels boost precision."),
        config=RAGConfig(top_k=2, embedding_dim=32),
    )


def test_constructor_requires_client():
    with pytest.raises(ValueError):
        RAGResearchAssistant(client=None)


def test_constructor_validates():
    with pytest.raises(ValueError):
        RAGResearchAssistant(client=MockLLM(), config=RAGConfig(top_k=0))
    with pytest.raises(ValueError):
        RAGResearchAssistant(client=MockLLM(), config=RAGConfig(embedding_dim=2))


def test_add_documents(assistant):
    assistant.add_documents(
        [
            ("a", "Triple barrier method labels with profit and stop targets"),
            ("b", "Meta-labelling improves precision over primary models"),
            ("c", "Volatility scaling stabilises position sizing"),
        ]
    )
    assert len(assistant) == 3


def test_add_documents_validates(assistant):
    with pytest.raises(TypeError):
        assistant.add_documents("not-a-list")
    with pytest.raises(ValueError):
        assistant.add_documents([("only-one",)])
    with pytest.raises(TypeError):
        assistant.add_documents([(1, "text")])


def test_retrieve_returns_sorted(assistant):
    assistant.add_documents(
        [
            ("a", "triple barrier method tp sl horizon"),
            ("b", "kelly sizing for long-only equity"),
            ("c", "meta labelling primary secondary"),
        ]
    )
    hits = assistant.retrieve("triple barrier")
    assert len(hits) == 2
    # Highest score first
    assert hits[0][2] >= hits[1][2]


def test_retrieve_empty_store(assistant):
    assert assistant.retrieve("anything") == []


def test_retrieve_validates(assistant):
    with pytest.raises(ValueError):
        assistant.retrieve("")
    assistant.add_documents([("a", "any text")])
    with pytest.raises(ValueError):
        assistant.retrieve("query", top_k=0)


def test_ask_calls_client_and_returns_payload(assistant):
    assistant.add_documents(
        [
            ("a", "meta labelling primary secondary models precision"),
            ("b", "unrelated about commodities"),
        ]
    )
    out = assistant.ask("What is meta-labelling?")
    assert "answer" in out
    assert "sources" in out
    assert out["n_hits"] == 2
    assert isinstance(out["answer"], str)
    assert assistant.client.call_log  # at least one call
