"""Deterministic, train-bound strategy catalog definitions for the SP500 mega-run."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


CATALOG_ID_DOMAIN = b"AURORA-SP500-STRATEGY-CATALOG-V1\0"
CATALOG_RECIPE_DOMAIN = b"AURORA-SP500-STRATEGY-RECIPE-V1\0"
CATALOG_CONFIGURATION_DOMAIN = b"AURORA-SP500-STRATEGY-CONFIGURATION-V1\0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LANE_RE = re.compile(r"^F\d{3}$")


class CatalogBuildError(ValueError):
    """Raised when a catalog row or artifact violates the frozen contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Return stable strict JSON bytes for hashes and versioned artifacts."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CatalogBuildError("CATALOG_VALUE_NOT_CANONICAL_JSON") from exc


def _sha256(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    text = str(value)
    if _SHA256_RE.fullmatch(text) is None:
        raise CatalogBuildError(f"CATALOG_INVALID_SHA256:{label}")
    return text


def configuration_sha256(
    lane_id: str,
    configuration: Mapping[str, object],
) -> str:
    """Bind one canonical lane configuration to its lane identity."""

    if _LANE_RE.fullmatch(str(lane_id)) is None:
        raise CatalogBuildError(f"CATALOG_INVALID_LANE_ID:{lane_id}")
    payload = {"lane_id": str(lane_id), "configuration": dict(configuration)}
    return _sha256(CATALOG_CONFIGURATION_DOMAIN, payload)


@dataclass(frozen=True)
class CatalogComponentV1:
    """One exact lane configuration used by a catalog strategy."""

    lane_id: str
    configuration: Mapping[str, object]
    configuration_sha256: str

    @classmethod
    def create(
        cls,
        lane_id: str,
        configuration: Mapping[str, object],
    ) -> CatalogComponentV1:
        checked_lane = str(lane_id)
        checked_configuration = dict(configuration)
        return cls(
            lane_id=checked_lane,
            configuration=checked_configuration,
            configuration_sha256=configuration_sha256(
                checked_lane,
                checked_configuration,
            ),
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CatalogComponentV1:
        lane_id = str(payload.get("lane_id", ""))
        raw_configuration = payload.get("configuration")
        if not isinstance(raw_configuration, Mapping):
            raise CatalogBuildError("CATALOG_COMPONENT_CONFIGURATION_INVALID")
        component = cls.create(lane_id, raw_configuration)
        supplied = _require_sha256(
            payload.get("configuration_sha256"),
            "configuration_sha256",
        )
        if supplied != component.configuration_sha256:
            raise CatalogBuildError("CATALOG_COMPONENT_HASH_MISMATCH")
        return component

    def to_payload(self) -> dict[str, object]:
        return {
            "lane_id": self.lane_id,
            "configuration": dict(self.configuration),
            "configuration_sha256": self.configuration_sha256,
        }


def _scientific_recipe_payload(
    *,
    strategy_kind: str,
    components: Sequence[CatalogComponentV1],
    composition: Mapping[str, object],
    feature_contract_sha256: str,
    search_end: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "strategy_kind": strategy_kind,
        "components": [component.to_payload() for component in components],
        "composition": dict(composition),
        "feature_contract_sha256": feature_contract_sha256,
        "search_end": search_end,
        "position_contract": {
            "allowed_positions": [-1, 1],
            "zero_action": "carry_previous",
        },
    }


def scientific_recipe_sha256(recipe: Mapping[str, object]) -> str:
    """Hash a fully canonical scientific recipe."""

    return _sha256(CATALOG_RECIPE_DOMAIN, dict(recipe))


def strategy_id_for(recipe: Mapping[str, object]) -> str:
    """Return the stable human-visible ID for one scientific recipe."""

    return "SCV1-" + _sha256(CATALOG_ID_DOMAIN, dict(recipe))


@dataclass(frozen=True)
class StrategyCatalogEntryV1:
    """Validated catalog row with provenance kept outside scientific identity."""

    schema_version: int
    strategy_id: str
    scientific_recipe_sha256: str
    strategy_kind: str
    components: tuple[CatalogComponentV1, ...]
    composition: Mapping[str, object]
    cross_rule_ids: tuple[str, ...]
    economic_rationales: tuple[str, ...]
    feature_count: int
    initial_fidelity: int
    coverage_tags: tuple[str, ...]
    feature_contract_sha256: str
    search_end: str
    validation_opened: bool
    locked_opened: bool
    performance_status: str

    @classmethod
    def create(
        cls,
        *,
        strategy_kind: str,
        components: Sequence[CatalogComponentV1],
        composition: Mapping[str, object],
        cross_rule_ids: Sequence[str],
        economic_rationales: Sequence[str],
        coverage_tags: Sequence[str],
        feature_contract_sha256: str,
        search_end: str = "2010-12-31",
    ) -> StrategyCatalogEntryV1:
        checked_components = tuple(components)
        if strategy_kind not in {"single", "cross"}:
            raise CatalogBuildError("CATALOG_STRATEGY_KIND_INVALID")
        if not 1 <= len(checked_components) <= 5:
            raise CatalogBuildError("CATALOG_FEATURE_COUNT_INVALID")
        lane_ids = [component.lane_id for component in checked_components]
        if len(set(lane_ids)) != len(lane_ids):
            raise CatalogBuildError("CATALOG_COMPONENT_LANE_DUPLICATE")
        if strategy_kind == "single" and len(checked_components) != 1:
            raise CatalogBuildError("CATALOG_SINGLE_FEATURE_COUNT_INVALID")
        if strategy_kind == "cross" and len(checked_components) < 2:
            raise CatalogBuildError("CATALOG_CROSS_FEATURE_COUNT_INVALID")
        feature_hash = _require_sha256(
            feature_contract_sha256,
            "feature_contract_sha256",
        )
        if search_end != "2010-12-31":
            raise CatalogBuildError("CATALOG_SEARCH_END_INVALID")
        recipe = _scientific_recipe_payload(
            strategy_kind=strategy_kind,
            components=checked_components,
            composition=composition,
            feature_contract_sha256=feature_hash,
            search_end=search_end,
        )
        return cls(
            schema_version=1,
            strategy_id=strategy_id_for(recipe),
            scientific_recipe_sha256=scientific_recipe_sha256(recipe),
            strategy_kind=strategy_kind,
            components=checked_components,
            composition=dict(composition),
            cross_rule_ids=tuple(sorted({str(value) for value in cross_rule_ids})),
            economic_rationales=tuple(
                sorted({str(value) for value in economic_rationales})
            ),
            feature_count=len(checked_components),
            initial_fidelity=1,
            coverage_tags=tuple(sorted({str(value) for value in coverage_tags})),
            feature_contract_sha256=feature_hash,
            search_end=search_end,
            validation_opened=False,
            locked_opened=False,
            performance_status="not_evaluated",
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> StrategyCatalogEntryV1:
        if payload.get("validation_opened") is not False or payload.get(
            "locked_opened"
        ) is not False:
            raise CatalogBuildError("CATALOG_BOUNDARY_OPEN")
        if payload.get("schema_version") != 1:
            raise CatalogBuildError("CATALOG_SCHEMA_VERSION_INVALID")
        if payload.get("initial_fidelity") != 1:
            raise CatalogBuildError("CATALOG_INITIAL_FIDELITY_INVALID")
        if payload.get("performance_status") != "not_evaluated":
            raise CatalogBuildError("CATALOG_PERFORMANCE_STATUS_INVALID")
        raw_components = payload.get("components")
        if not isinstance(raw_components, list):
            raise CatalogBuildError("CATALOG_COMPONENTS_INVALID")
        raw_composition = payload.get("composition")
        if not isinstance(raw_composition, Mapping):
            raise CatalogBuildError("CATALOG_COMPOSITION_INVALID")
        raw_rules = payload.get("cross_rule_ids")
        raw_rationales = payload.get("economic_rationales")
        raw_coverage = payload.get("coverage_tags")
        if not all(
            isinstance(value, list)
            for value in (raw_rules, raw_rationales, raw_coverage)
        ):
            raise CatalogBuildError("CATALOG_PROVENANCE_INVALID")
        entry = cls.create(
            strategy_kind=str(payload.get("strategy_kind", "")),
            components=[
                CatalogComponentV1.from_payload(component)
                for component in raw_components
                if isinstance(component, Mapping)
            ],
            composition=raw_composition,
            cross_rule_ids=[str(value) for value in raw_rules],
            economic_rationales=[str(value) for value in raw_rationales],
            coverage_tags=[str(value) for value in raw_coverage],
            feature_contract_sha256=str(payload.get("feature_contract_sha256", "")),
            search_end=str(payload.get("search_end", "")),
        )
        if payload.get("feature_count") != entry.feature_count:
            raise CatalogBuildError("CATALOG_FEATURE_COUNT_MISMATCH")
        if payload.get("strategy_id") != entry.strategy_id:
            raise CatalogBuildError("CATALOG_STRATEGY_ID_MISMATCH")
        if payload.get("scientific_recipe_sha256") != entry.scientific_recipe_sha256:
            raise CatalogBuildError("CATALOG_RECIPE_HASH_MISMATCH")
        return entry

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "scientific_recipe_sha256": self.scientific_recipe_sha256,
            "strategy_kind": self.strategy_kind,
            "components": [component.to_payload() for component in self.components],
            "composition": dict(self.composition),
            "cross_rule_ids": list(self.cross_rule_ids),
            "economic_rationales": list(self.economic_rationales),
            "feature_count": self.feature_count,
            "initial_fidelity": self.initial_fidelity,
            "coverage_tags": list(self.coverage_tags),
            "feature_contract_sha256": self.feature_contract_sha256,
            "search_end": self.search_end,
            "validation_opened": self.validation_opened,
            "locked_opened": self.locked_opened,
            "performance_status": self.performance_status,
        }


__all__ = [
    "CatalogBuildError",
    "CatalogComponentV1",
    "StrategyCatalogEntryV1",
    "canonical_json_bytes",
    "configuration_sha256",
    "scientific_recipe_sha256",
    "strategy_id_for",
]
