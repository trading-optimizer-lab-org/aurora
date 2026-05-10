"""Side-mapping that links atlas entries to paper claim ids (R174).

The strategy atlas is the platform's canonical "what we admit" list.
Paper claims are upstream evidence: a researcher reads a paper, asserts
"this claim from paper X looks relevant to atlas entry Y", and we want
to record that link without polluting the atlas dataclass.

The link is **metadata only**. It is *not* validation evidence:

* :func:`is_atlas_promotable_with_paper_evidence` always reflects the
  atlas entry's own status. Paper claims do not change it.
* The promotion gate -- in :class:`StrategyAtlas.is_promotable` and the
  validation pipeline -- never reads from this registry.

Why a side mapping rather than mutating ``StrategyAtlasEntry``:
``StrategyAtlasEntry`` is frozen and ships in golden tests. Adding a
mutable list of claim ids to the dataclass would break frozen-ness
guarantees and force a schema change. A separate registry keeps the
link discoverable for tooling without touching the atlas's contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.research.strategy_atlas import StrategyAtlas


@dataclass(frozen=True)
class AtlasPaperLink:
    """One link from an atlas entry to a paper claim id."""

    atlas_name: str
    claim_id: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.atlas_name or not self.atlas_name.strip():
            raise ValueError("AtlasPaperLink.atlas_name must be non-empty")
        if not self.claim_id or not self.claim_id.strip():
            raise ValueError("AtlasPaperLink.claim_id must be non-empty")


@dataclass
class AtlasPaperLinkRegistry:
    """In-memory registry of :class:`AtlasPaperLink` records.

    Stores links keyed by ``atlas_name``. One atlas entry can have
    multiple links to multiple paper claim ids; duplicate links
    (same atlas_name + claim_id) are silently ignored.
    """

    _by_atlas: dict[str, list[AtlasPaperLink]] = field(default_factory=dict)

    def link(self, atlas_name: str, claim_id: str, note: str = "") -> None:
        """Record a link from ``atlas_name`` to ``claim_id``."""
        bucket = self._by_atlas.setdefault(atlas_name, [])
        for existing in bucket:
            if existing.claim_id == claim_id:
                return  # Already linked.
        bucket.append(AtlasPaperLink(
            atlas_name=atlas_name,
            claim_id=claim_id,
            note=note,
        ))

    def claim_ids_for(self, atlas_name: str) -> list[str]:
        """Return the list of claim ids linked to ``atlas_name``."""
        return [link.claim_id for link in self._by_atlas.get(atlas_name, [])]

    def links_for(self, atlas_name: str) -> list[AtlasPaperLink]:
        """Return the list of :class:`AtlasPaperLink` for ``atlas_name``."""
        return list(self._by_atlas.get(atlas_name, []))

    def all_links(self) -> list[AtlasPaperLink]:
        """Flatten the registry into a single list ordered by atlas name."""
        out: list[AtlasPaperLink] = []
        for atlas_name in sorted(self._by_atlas.keys()):
            out.extend(self._by_atlas[atlas_name])
        return out

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_atlas.values())


def is_atlas_promotable_with_paper_evidence(
    atlas: "StrategyAtlas",
    atlas_name: str,
    *,
    link_registry: AtlasPaperLinkRegistry | None = None,
) -> bool:
    """Return True iff ``atlas_name`` is promotable on its OWN atlas status.

    The ``link_registry`` argument is intentionally accepted but ignored
    for the promotion decision. Paper claims are *upstream* evidence;
    they do not move an atlas entry from CANDIDATE to SUPPORTED on
    their own.

    The function exists so callers can pass the link registry through a
    single helper without that parameter accidentally weakening the
    gate.
    """
    if link_registry is not None:
        # Touch the registry so static analysers know the parameter is
        # used; the value never influences the return.
        _ = link_registry.claim_ids_for(atlas_name)
    if not atlas.has(atlas_name):
        return False
    return atlas.is_promotable(atlas_name)


__all__ = [
    "AtlasPaperLink",
    "AtlasPaperLinkRegistry",
    "is_atlas_promotable_with_paper_evidence",
]
