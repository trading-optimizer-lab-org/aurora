"""Non-circular source catalogue for the historical PERMNO identity gate."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import yaml


class IdentitySourceError(ValueError):
    """Raised when identity-source evidence is incomplete or contradictory."""


@dataclass(frozen=True)
class IdentitySource:
    source_id: str
    evidence_url: str
    checked_at: str
    provides_permno: bool
    provides_public_identifier: bool
    historical_intervals: bool
    share_class_specific: bool
    broad_universe: bool
    public_zero_cost: bool
    authorized_for_internal_research: bool
    target_derived: bool


POSITIVE_REQUIREMENTS = (
    "provides_permno",
    "provides_public_identifier",
    "historical_intervals",
    "share_class_specific",
    "broad_universe",
    "public_zero_cost",
    "authorized_for_internal_research",
)


def _strict_bool(row: dict[str, object], field: str, source_id: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise IdentitySourceError(
            f"{source_id}: {field} debe ser booleano explícito"
        )
    return value


def load_identity_source_catalog(path: Path) -> list[IdentitySource]:
    """Load a dated catalogue and reject evidence gaps rather than infer them."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise IdentitySourceError("El catálogo de identidad no contiene sources")
    checked_at = str(payload.get("checked_at", ""))
    try:
        date.fromisoformat(checked_at)
    except ValueError as exc:
        raise IdentitySourceError("checked_at no es una fecha ISO válida") from exc

    result: list[IdentitySource] = []
    seen: set[str] = set()
    for raw in payload["sources"]:
        if not isinstance(raw, dict):
            raise IdentitySourceError("Cada fuente debe ser un mapa")
        source_id = str(raw.get("source_id", "")).strip()
        if not source_id:
            raise IdentitySourceError("Una fuente no tiene source_id")
        if source_id in seen:
            raise IdentitySourceError(f"source_id duplicado: {source_id}")
        seen.add(source_id)
        evidence_url = str(raw.get("evidence_url", "")).strip()
        parsed = urlparse(evidence_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise IdentitySourceError(f"{source_id}: evidence_url debe ser HTTPS")
        values = {
            field: _strict_bool(raw, field, source_id)
            for field in (*POSITIVE_REQUIREMENTS, "target_derived")
        }
        result.append(
            IdentitySource(
                source_id=source_id,
                evidence_url=evidence_url,
                checked_at=checked_at,
                **values,
            )
        )
    if not result:
        raise IdentitySourceError("El catálogo de identidad está vacío")
    return result


def evaluate_public_identity_routes(
    sources: Sequence[IdentitySource],
) -> pd.DataFrame:
    """Return one fail-closed decision per declared source route."""

    rows: list[dict[str, object]] = []
    for source in sources:
        record = asdict(source)
        missing = [field for field in POSITIVE_REQUIREMENTS if not record[field]]
        disqualifiers = ["target_derived"] if source.target_derived else []
        rows.append(
            {
                **record,
                "missing_requirements": "|".join(missing),
                "disqualifiers": "|".join(disqualifiers),
                "route_pass": not missing and not disqualifiers,
            }
        )
    return pd.DataFrame(rows).sort_values("source_id").reset_index(drop=True)


def load_default_identity_sources() -> list[IdentitySource]:
    return load_identity_source_catalog(Path("config/openap_149_identity_sources.yaml"))


__all__ = [
    "IdentitySource",
    "IdentitySourceError",
    "evaluate_public_identity_routes",
    "load_default_identity_sources",
    "load_identity_source_catalog",
]
