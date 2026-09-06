"""Build acceptance selections without changing catalog scientific identities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from pathlib import Path
import re
from typing import Any

from aurora.infra.sp500_megarun.strategy_catalog import (
    StrategyCatalogBuildV1, StrategyCatalogEntryV1, write_strategy_catalog,
)


def choose_canary_ids(
    single_ids: Iterable[str], combined_ids: Iterable[str]
) -> tuple[str, ...]:
    """Select four distinct, already eligible strategies from each family.

    Eligibility must be established against verified reference results and
    available components before calling this selector. This function does not
    grant source authority or validate a production preparation.
    """
    singles = sorted(set(single_ids))[:4]
    combined = sorted(set(combined_ids))[:4]
    chosen = singles + combined
    if len(singles) != 4 or len(combined) != 4 or len(set(chosen)) != 8:
        raise ValueError("CANARY_COVERAGE_UNAVAILABLE")
    return tuple(sorted(chosen))


def select_canary_rows(
    catalog_rows: Iterable[Mapping[str, object]],
    *,
    reference_recipe_hashes: Mapping[str, str],
    available_component_ids: Set[str],
) -> tuple[dict[str, object], ...]:
    """Select unchanged catalog rows with exact reference/component coverage.

    Callers establish the authority and freshness of both evidence inputs.
    Row identity and scientific-boundary validation use the production parser.
    """
    eligible: dict[str, dict[str, object]] = {}
    families: dict[str, list[str]] = {"single": [], "cross": []}
    observed: set[str] = set()
    for payload in catalog_rows:
        entry = StrategyCatalogEntryV1.from_payload(payload)
        if entry.strategy_id in observed:
            raise ValueError("CANARY_CATALOG_DUPLICATE_STRATEGY")
        observed.add(entry.strategy_id)
        expected_recipe = reference_recipe_hashes.get(entry.strategy_id)
        if expected_recipe is None:
            continue
        if expected_recipe != entry.scientific_recipe_sha256:
            raise ValueError("CANARY_REFERENCE_RECIPE_MISMATCH")
        if not all(
            component.configuration_sha256 in available_component_ids
            for component in entry.components
        ):
            continue
        eligible[entry.strategy_id] = dict(payload)
        families[entry.strategy_kind].append(entry.strategy_id)
    ids = choose_canary_ids(families["single"], families["cross"])
    return tuple(eligible[strategy_id] for strategy_id in ids)


def write_canary_catalog(
    catalog_rows: Iterable[Mapping[str, object]], *, output_dir: Path,
    reference_recipe_hashes: Mapping[str, str], available_component_ids: Set[str],
    data_contract_sha256: str, feature_contract_sha256: str,
    source_catalog_sha256: str,
) -> dict[str, Any]:
    """Export the selected acceptance subset through the production writer.

    Caller verifies provenance of source/evidence. Coverage applies only to this
    explicit eight-row selection, never to all lanes of the parent catalog.
    This metadata export does not publish PREPARED or authorize a run.
    """
    root = Path(output_dir)
    if root.exists() or root.is_symlink():
        raise ValueError('CANARY_OUTPUT_EXISTS')
    if any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in (
        data_contract_sha256, feature_contract_sha256, source_catalog_sha256,
    )):
        raise ValueError('CANARY_SOURCE_IDENTITY_INVALID')
    selected = select_canary_rows(
        catalog_rows, reference_recipe_hashes=reference_recipe_hashes,
        available_component_ids=available_component_ids,
    )
    entries = tuple(StrategyCatalogEntryV1.from_payload(row) for row in selected)
    if any(row['feature_contract_sha256'] != feature_contract_sha256 for row in selected):
        raise ValueError('CANARY_FEATURE_CONTRACT_MISMATCH')
    singles = tuple(entry for entry in entries if entry.strategy_kind == 'single')
    crosses = tuple(entry for entry in entries if entry.strategy_kind == 'cross')
    coverage = {
        'schema_version': 1,
        'scope': 'selected_canary_only',
        'source_catalog_sha256': source_catalog_sha256,
        'expected_strategy_ids': [entry.strategy_id for entry in entries],
        'individual': {
            'lane_count': len({component.lane_id for entry in singles for component in entry.components}),
            'selected_strategy_count': len(singles),
            'uncovered_requirements': [],
        },
        'cross': {
            'rule_count': len({rule for entry in crosses for rule in entry.cross_rule_ids}),
            'deduplicated_strategy_count': len(crosses),
            'uncovered_rule_composition_arities': [],
            'uncovered_authorized_left_right_pairs': [],
            'uncovered_parameter_values': [],
        },
    }
    build = StrategyCatalogBuildV1(
        entries=entries, coverage=coverage,
        data_contract_sha256=data_contract_sha256,
        feature_contract_sha256=feature_contract_sha256,
        search_end='2010-12-31', validation_opened=False, locked_opened=False,
    )
    # Reserve this new task-owned output so the existing writer cannot replace
    # a directory belonging to another process between our check and its write.
    root.mkdir(parents=True, exist_ok=False)
    return write_strategy_catalog(build, root)
