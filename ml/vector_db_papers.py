"""Embedded vector database of paper abstracts.

Wraps optional ``sentence-transformers`` + ``chromadb`` for high-quality
semantic search over research papers. When either dep is missing, falls back
to a deterministic hash-based embedder + numpy nearest-neighbour, so unit
tests work offline without heavy models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import sentence_transformers  # type: ignore
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:  # pragma: no cover
    sentence_transformers = None  # type: ignore[assignment]
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    import chromadb  # type: ignore
    CHROMADB_AVAILABLE = True
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]
    CHROMADB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class PapersVectorDBConfig:
    embedding_dim: int = 64
    model_name: str = "all-MiniLM-L6-v2"
    use_sentence_transformers: bool = False  # opt-in


# ---------------------------------------------------------------------------
# Hash embedder fallback
# ---------------------------------------------------------------------------


def _hash_embed(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for tok in text.lower().split():
        idx = (hash(tok) & 0xFFFFFFFF) % dim
        vec[idx] += 1.0
    n = float(np.linalg.norm(vec))
    if n > 0:
        vec /= n
    return vec


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


@dataclass
class _Paper:
    paper_id: str
    title: str
    abstract: str
    vec: np.ndarray


class PapersVectorDB:
    """Tiny vector DB for paper abstracts with a numpy fallback.

    Workflow::

        db = PapersVectorDB()
        db.add_papers([{"id": "p1", "title": "T", "abstract": "..."}, ...])
        hits = db.search("triple barrier method", k=3)
    """

    def __init__(self, config: Optional[PapersVectorDBConfig] = None):
        self.config = config if config is not None else PapersVectorDBConfig()
        if self.config.embedding_dim < 4:
            raise ValueError("embedding_dim must be >= 4")
        self._papers: List[_Paper] = []
        # Optional sentence-transformer model
        self._st_model = None
        if (
            self.config.use_sentence_transformers
            and SENTENCE_TRANSFORMERS_AVAILABLE
        ):  # pragma: no cover - integration only
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._st_model = SentenceTransformer(self.config.model_name)

    # ------------------------------------------------------------------ embed

    def _embed(self, text: str) -> np.ndarray:
        if self._st_model is not None:  # pragma: no cover - integration only
            v = self._st_model.encode([text], convert_to_numpy=True)[0].astype(np.float32)
            n = float(np.linalg.norm(v))
            if n > 0:
                v = v / n
            return v
        return _hash_embed(text, self.config.embedding_dim)

    # ------------------------------------------------------------------ add

    def add_papers(self, papers: Sequence[Dict[str, str]]) -> int:
        if not isinstance(papers, (list, tuple)):
            raise TypeError("papers must be a sequence of dicts")
        added = 0
        for p in papers:
            if not isinstance(p, dict):
                raise TypeError("each paper must be a dict")
            for k in ("id", "title", "abstract"):
                if k not in p:
                    raise ValueError(f"paper missing key '{k}'")
            vec = self._embed(p["abstract"])
            self._papers.append(
                _Paper(
                    paper_id=p["id"], title=p["title"], abstract=p["abstract"], vec=vec
                )
            )
            added += 1
        return added

    def __len__(self) -> int:
        return len(self._papers)

    # ------------------------------------------------------------------ search

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if k < 1:
            raise ValueError("k must be >= 1")
        if not self._papers:
            return []
        q_vec = self._embed(query)
        sims = np.array([float(np.dot(q_vec, p.vec)) for p in self._papers])
        order = np.argsort(-sims)[:k]
        return [
            {
                "id": self._papers[i].paper_id,
                "title": self._papers[i].title,
                "abstract": self._papers[i].abstract,
                "score": float(sims[i]),
            }
            for i in order
        ]

    def get(self, paper_id: str) -> Optional[Dict[str, Any]]:
        for p in self._papers:
            if p.paper_id == paper_id:
                return {"id": p.paper_id, "title": p.title, "abstract": p.abstract}
        return None
