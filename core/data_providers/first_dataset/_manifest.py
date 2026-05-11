"""R157 / R158 first-dataset manifest dataclasses + YAML loader.

Pure data model. No I/O beyond reading the YAML file at the path passed
to :func:`load_manifest`.

R158 extension: each section now carries optional ``trust_level``,
``asset_group``, ``expected_fields``, and ``notes`` metadata, and the
manifest itself records a ``frequency`` (default ``"1d"``). All new
fields default to safe values so the R157 ``config/first_dataset.yaml``
parses unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


__all__ = [
    "FirstDatasetManifest",
    "FirstDatasetSection",
    "load_manifest",
]


@dataclass(frozen=True)
class FirstDatasetSection:
    """One section of the manifest (equities / crypto / macro / fx / ...)."""

    name: str
    symbols: Tuple[str, ...]
    providers: Tuple[str, ...]
    library: str
    allow_fallback: bool
    trust_level: str = "research_seed"
    asset_group: str | None = None
    expected_fields: Tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class FirstDatasetManifest:
    """Parsed first-dataset manifest.

    Built from a YAML payload via :func:`load_manifest`. ``sections``
    is a tuple so the orchestrator iterates in declaration order.
    """

    name: str
    start: str
    end: str
    sections: Tuple[FirstDatasetSection, ...]
    frequency: str = "1d"


_KNOWN_TRUST_LEVELS: frozenset[str] = frozenset(
    {"research_seed", "reference_seed", "context_seed", "official_pit"}
)


def load_manifest(path: Path | str) -> FirstDatasetManifest:
    """Read ``path`` (YAML) and return a :class:`FirstDatasetManifest`."""
    import yaml  # PyYAML is already a declared dep.

    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"manifest at {path}: expected mapping at root")
    name = str(data.get("name", "first"))
    start = str(data.get("start", ""))
    # ``end: null`` (means "open-ended" -- newest available) round-trips
    # through PyYAML as None; coerce to empty string for the dataclass.
    raw_end = data.get("end", "")
    end = "" if raw_end is None else str(raw_end)
    frequency = str(data.get("frequency", "1d"))
    sections_raw = data.get("sections") or {}
    if not isinstance(sections_raw, dict):
        raise ValueError(
            f"manifest at {path}: 'sections' must be a mapping"
        )
    sections: list[FirstDatasetSection] = []
    for sec_name, body in sections_raw.items():
        if not isinstance(body, dict):
            raise ValueError(
                f"manifest at {path}: section {sec_name!r} body must be a mapping"
            )
        trust_level = str(body.get("trust_level", "research_seed"))
        if trust_level not in _KNOWN_TRUST_LEVELS:
            raise ValueError(
                f"manifest at {path}: section {sec_name!r} trust_level "
                f"{trust_level!r} not one of {sorted(_KNOWN_TRUST_LEVELS)}"
            )
        asset_group_val = body.get("asset_group")
        notes_val = body.get("notes")
        sections.append(
            FirstDatasetSection(
                name=str(sec_name),
                symbols=tuple(str(s) for s in body.get("symbols", ())),
                providers=tuple(str(p) for p in body.get("providers", ())),
                library=str(body.get("library", "")),
                allow_fallback=bool(body.get("allow_fallback", False)),
                trust_level=trust_level,
                asset_group=(
                    str(asset_group_val) if asset_group_val is not None else None
                ),
                expected_fields=tuple(
                    str(f) for f in body.get("expected_fields", ())
                ),
                notes=str(notes_val) if notes_val is not None else None,
            )
        )
    return FirstDatasetManifest(
        name=name,
        start=start,
        end=end,
        sections=tuple(sections),
        frequency=frequency,
    )
