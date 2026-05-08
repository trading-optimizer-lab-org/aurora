"""Retrieval-augmented research assistant.

Combines a vector-DB retriever with an LLM answer step. The retriever default
is ChromaDB; if it is not installed, an in-memory cosine fallback is used so
tests and offline workflows remain functional. The LLM client default is the
official Anthropic SDK; a deterministic ``MockLLM`` is provided for tests.

Public API: ``RAGConfig`` + ``RAGResearchAssistant``.

All third-party deps (``chromadb``, ``anthropic``) are lazy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import chromadb  # type: ignore
    CHROMADB_AVAILABLE = True
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]
    CHROMADB_AVAILABLE = False

try:
    import anthropic  # type: ignore
    ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]
    ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RAGConfig:
    """Hyperparameters for :class:`RAGResearchAssistant`."""
    top_k: int = 3
    model: str = "claude-opus-4-7"
    max_tokens: int = 512
    embedding_dim: int = 64


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class _MockMessage:
    def __init__(self, text: str):
        self.content = [type("Block", (), {"text": text, "type": "text"})()]


class MockLLM:
    """Deterministic stub of an Anthropic ``messages.create`` client."""

    def __init__(self, reply_text: str = "MOCK ANSWER"):
        self.reply_text = reply_text
        self.call_log: List[Dict[str, Any]] = []
        self.messages = self  # mimic client.messages.create

    def create(self, **kwargs) -> _MockMessage:
        self.call_log.append(kwargs)
        return _MockMessage(self.reply_text)


# ---------------------------------------------------------------------------
# Hash-based embedder (fallback / tests)
# ---------------------------------------------------------------------------


def _hash_embed(text: str, dim: int) -> np.ndarray:
    """Deterministic bag-of-tokens embedding using Python ``hash``.

    Not for production retrieval quality; sufficient to test plumbing without
    pulling sentence-transformers or its torch dependency.
    """
    vec = np.zeros(dim, dtype=np.float32)
    for tok in text.lower().split():
        idx = (hash(tok) & 0xFFFFFFFF) % dim
        vec[idx] += 1.0
    n = float(np.linalg.norm(vec))
    if n > 0:
        vec /= n
    return vec


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------


class RAGResearchAssistant:
    """Vector-DB retrieval plus an LLM answer step.

    Workflow::

        rag = RAGResearchAssistant(client=MockLLM(reply_text="..."))
        rag.add_documents([("doc1", "Triple barrier..."), ...])
        answer = rag.ask("What is meta-labelling?")
    """

    def __init__(
        self,
        client: Any,
        config: Optional[RAGConfig] = None,
        embed_fn: Optional[Callable[[str], np.ndarray]] = None,
    ):
        if client is None:
            raise ValueError("client must not be None; pass MockLLM for tests")
        self.client = client
        self.config = config if config is not None else RAGConfig()
        if self.config.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if self.config.embedding_dim < 4:
            raise ValueError("embedding_dim must be >= 4")
        self._embed_fn = embed_fn or (
            lambda t: _hash_embed(t, self.config.embedding_dim)
        )
        # In-memory store: list of (id, text, vec)
        self._store: List[Tuple[str, str, np.ndarray]] = []

    # ------------------------------------------------------------------ data

    def add_documents(self, docs: Sequence[Tuple[str, str]]) -> None:
        if not isinstance(docs, (list, tuple)):
            raise TypeError("docs must be a sequence of (id, text) tuples")
        for d in docs:
            if not (isinstance(d, tuple) and len(d) == 2):
                raise ValueError("each document must be a (id, text) tuple")
            doc_id, text = d
            if not isinstance(doc_id, str) or not isinstance(text, str):
                raise TypeError("(id, text) must both be strings")
            vec = self._embed_fn(text)
            self._store.append((doc_id, text, vec))

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------ retrieve

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Tuple[str, str, float]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        k = top_k if top_k is not None else self.config.top_k
        if k < 1:
            raise ValueError("top_k must be >= 1")
        if not self._store:
            return []
        q_vec = self._embed_fn(query)
        scored: List[Tuple[str, str, float]] = []
        for doc_id, text, v in self._store:
            sim = float(np.dot(q_vec, v))
            scored.append((doc_id, text, sim))
        scored.sort(key=lambda r: r[2], reverse=True)
        return scored[:k]

    # ------------------------------------------------------------------ ask

    def ask(self, query: str, top_k: Optional[int] = None) -> Dict[str, Any]:
        hits = self.retrieve(query, top_k=top_k)
        context = "\n\n".join(f"[{i + 1}] {h[1]}" for i, h in enumerate(hits))
        prompt = (
            "Answer the question using ONLY the context below. "
            "Cite passages by their bracketed index.\n\n"
            f"Context:\n{context}\n\nQuestion: {query}"
        )
        msg = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        try:
            text = msg.content[0].text
        except Exception:  # pragma: no cover - defensive
            text = str(msg)
        return {
            "answer": text,
            "sources": [{"id": h[0], "score": h[2]} for h in hits],
            "n_hits": len(hits),
        }
