"""Spec-lineage graph utilities.

Tracks the parent->child relationship between
:class:`~aurora.research.factory.spec.StrategySpec` instances. A spec
that was mutated from another (e.g. by GA crossover, by a template
generator, or by a human edit) carries the parent's ``spec_id`` in
``parent_spec_id``. Walking that chain reconstructs the lineage DAG.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from aurora.research.factory.outcomes import CandidateRun


class LineageGraph:
    """In-memory DAG of spec_id -> child spec_ids.

    Build with :meth:`add` (one CandidateRun at a time) or :meth:`build`
    (an iterable of CandidateRuns). The graph deliberately tolerates
    cycles in the *input* by detecting them at traversal time -- a
    malformed JSONL archive should not crash the lineage CLI.
    """

    def __init__(self) -> None:
        self._children: dict[str, list[str]] = defaultdict(list)
        self._parents: dict[str, Optional[str]] = {}
        self._candidates: dict[str, CandidateRun] = {}

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def add(self, candidate: CandidateRun) -> None:
        """Add a single candidate to the graph.

        Idempotent on ``spec_id``: a re-add with the same spec is a no-op
        for the children lists but updates the latest-seen candidate
        record so query callers see the freshest stage.
        """
        spec = candidate.spec
        spec_id = spec.spec_id
        parent = spec.parent_spec_id
        # Record candidate (latest record wins so intermediate REVIEW vs
        # ARCHIVED states resolve to the final one).
        self._candidates[spec_id] = candidate
        # Parent pointer (None for roots).
        self._parents[spec_id] = parent
        if parent is not None:
            siblings = self._children[parent]
            if spec_id not in siblings:
                siblings.append(spec_id)

    def build(self, candidates: Iterable[CandidateRun]) -> None:
        for c in candidates:
            self.add(c)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def query_descendants(self, spec_id: str) -> list[CandidateRun]:
        """BFS over descendants of ``spec_id`` (excluding ``spec_id`` itself).

        Detects cycles (a spec_id revisited during traversal is dropped
        on the second visit) so a malformed input never loops forever.
        Order: breadth-first.
        """
        seen: set[str] = set()
        out: list[CandidateRun] = []
        frontier: list[str] = list(self._children.get(spec_id, []))
        while frontier:
            sid = frontier.pop(0)
            if sid in seen or sid == spec_id:
                continue
            seen.add(sid)
            cand = self._candidates.get(sid)
            if cand is not None:
                out.append(cand)
            frontier.extend(
                c for c in self._children.get(sid, []) if c not in seen
            )
        return out

    def query_ancestors(self, spec_id: str) -> list[CandidateRun]:
        """Walk parent pointers up to a root (excluding ``spec_id`` itself).

        Cycle-safe via a visited set.
        """
        seen: set[str] = set()
        out: list[CandidateRun] = []
        cur = self._parents.get(spec_id)
        while cur is not None and cur not in seen:
            seen.add(cur)
            cand = self._candidates.get(cur)
            if cand is not None:
                out.append(cand)
            cur = self._parents.get(cur)
        return out

    def lineage_chain(self, spec_id: str) -> list[CandidateRun]:
        """Return ancestors (root-first) + the candidate itself.

        Convenient for the ``forge research lineage`` CLI which prints
        the full chain root -> spec_id.
        """
        ancestors = list(reversed(self.query_ancestors(spec_id)))
        self_cand = self._candidates.get(spec_id)
        if self_cand is None:
            return ancestors
        return ancestors + [self_cand]

    def roots(self) -> list[str]:
        """Spec ids with no parent (or whose parent is unknown to us)."""
        return [
            sid for sid, p in self._parents.items()
            if p is None or p not in self._candidates
        ]

    def __contains__(self, spec_id: str) -> bool:
        return spec_id in self._candidates

    def __len__(self) -> int:
        return len(self._candidates)

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def dot_export(self) -> str:
        """Return a Graphviz DOT representation of the lineage.

        Each node is a spec_id with the spec's name as the label and the
        outcome stage colour-coded:

        * ``review_queue`` -> green
        * ``archived``     -> red
        * everything else  -> gray (in-flight)
        """
        lines = ["digraph lineage {", "  rankdir=LR;",
                 "  node [shape=box, style=filled];"]
        for sid, cand in self._candidates.items():
            label = cand.spec.name.replace('"', "'")
            stage = cand.stage.value if cand.stage else "?"
            color = "lightgray"
            if stage == "review_queue":
                color = "palegreen"
            elif stage == "archived":
                color = "lightcoral"
            lines.append(
                f'  "{sid}" [label="{label}\\n[{stage}]", fillcolor="{color}"];'
            )
        for parent, kids in self._children.items():
            for k in kids:
                lines.append(f'  "{parent}" -> "{k}";')
        lines.append("}")
        return "\n".join(lines)


__all__ = [
    "LineageGraph",
]
