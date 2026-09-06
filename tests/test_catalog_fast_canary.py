"""Acceptance-campaign selection must not silently change its coverage."""

from __future__ import annotations

import pytest
import json

from aurora.infra.sp500_megarun.strategy_catalog import (
    CatalogComponentV1,
    StrategyCatalogEntryV1,
)
from scripts.build_catalog_fast_canary import choose_canary_ids


def test_canary_selects_first_four_eligible_ids_in_each_family() -> None:
    assert choose_canary_ids(
        ["s5", "s2", "s4", "s1", "s3"],
        ["c5", "c2", "c4", "c1", "c3"],
    ) == ("c1", "c2", "c3", "c4", "s1", "s2", "s3", "s4")


def test_repeated_ids_do_not_count_as_independent_strategies() -> None:
    with pytest.raises(ValueError, match="CANARY_COVERAGE_UNAVAILABLE"):
        choose_canary_ids(["s1", "s1", "s2", "s3"], ["c1", "c2", "c3", "c4"])


@pytest.mark.parametrize("short_family", ("single", "cross"))
def test_canary_cannot_shrink_a_missing_family(short_family: str) -> None:
    singles = ["s1", "s2", "s3", "s4"]
    crosses = ["c1", "c2", "c3", "c4"]
    if short_family == "single":
        singles.pop()
    else:
        crosses.pop()
    with pytest.raises(ValueError, match="CANARY_COVERAGE_UNAVAILABLE"):
        choose_canary_ids(singles, crosses)


def test_one_strategy_cannot_belong_to_both_families() -> None:
    with pytest.raises(ValueError, match="CANARY_COVERAGE_UNAVAILABLE"):
        choose_canary_ids(["a", "b", "c", "shared"], ["d", "e", "f", "shared"])


def _catalog_rows() -> list[dict[str, object]]:
    rows = []
    for kind in ("single", "cross"):
        for window in (10, 20, 30, 40):
            components = [CatalogComponentV1.create("F001", {"window": window})]
            if kind == "cross":
                components.append(CatalogComponentV1.create("F002", {"window": window}))
            rows.append(StrategyCatalogEntryV1.create(
                strategy_kind=kind,
                components=components,
                composition={"kind": "identity" if kind == "single" else "gate"},
                cross_rule_ids=(),
                economic_rationales=(),
                coverage_tags=(),
                feature_contract_sha256="a" * 64,
            ).to_payload())
    return rows


def _eligible_evidence(rows):
    reference = {row["strategy_id"]: row["scientific_recipe_sha256"] for row in rows}
    components = frozenset(component["configuration_sha256"]
                           for row in rows for component in row["components"])
    return reference, components


def test_selected_recipes_keep_their_scientific_payloads() -> None:
    from scripts.build_catalog_fast_canary import select_canary_rows

    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    selected = select_canary_rows(reversed(rows), reference_recipe_hashes=reference,
                                  available_component_ids=components)
    assert len(selected) == 8
    assert {row["strategy_id"] for row in selected} == set(reference)
    original = {row["strategy_id"]: row for row in rows}
    for row in selected:
        assert row == original[row["strategy_id"]]


@pytest.mark.parametrize("missing", ("reference", "component"))
def test_missing_evidence_cannot_be_replaced_by_a_smaller_canary(missing: str) -> None:
    from scripts.build_catalog_fast_canary import select_canary_rows

    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    if missing == "reference":
        reference.pop(rows[0]["strategy_id"])
    else:
        row_components = rows[0]["components"]
        assert isinstance(row_components, list)
        first_component = row_components[0]
        assert isinstance(first_component, dict)
        components = components - {first_component["configuration_sha256"]}
    with pytest.raises(ValueError, match="CANARY_COVERAGE_UNAVAILABLE"):
        select_canary_rows(rows, reference_recipe_hashes=reference,
                           available_component_ids=components)


def test_reference_must_describe_the_exact_scientific_recipe() -> None:
    from scripts.build_catalog_fast_canary import select_canary_rows

    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    reference[rows[0]["strategy_id"]] = "f" * 64
    with pytest.raises(ValueError, match="CANARY_REFERENCE_RECIPE_MISMATCH"):
        select_canary_rows(rows, reference_recipe_hashes=reference,
                           available_component_ids=components)


def test_opened_scientific_boundary_cannot_enter_the_acceptance_catalog() -> None:
    from scripts.build_catalog_fast_canary import select_canary_rows

    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    rows[0]["validation_opened"] = True
    with pytest.raises(ValueError, match="CATALOG_BOUNDARY_OPEN"):
        select_canary_rows(rows, reference_recipe_hashes=reference,
                           available_component_ids=components)


def test_canary_export_is_readable_by_production_and_keeps_exact_rows(tmp_path):
    from scripts import build_catalog_fast_canary as canary
    from aurora.infra.sp500_megarun.strategy_catalog import verify_strategy_catalog_directory

    # Omitting the official writer, changing rows or copying full-catalog counts
    # must fail this producer-to-consumer contract test.
    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    for name in ('first', 'second'):
        canary.write_canary_catalog(
            rows, output_dir=tmp_path / name, reference_recipe_hashes=reference,
            available_component_ids=components, data_contract_sha256='b' * 64,
            feature_contract_sha256='a' * 64, source_catalog_sha256='c' * 64,
        )
    first = tmp_path / 'first'
    verified = verify_strategy_catalog_directory(first)
    assert verified['strategy_count'] == 8
    assert verified['individual_strategy_count'] == 4
    assert verified['cross_strategy_count'] == 4
    exported = [json.loads(line) for line in (first / 'catalog.jsonl').read_text().splitlines()]
    assert exported == sorted(rows, key=lambda row: row['strategy_id'])
    coverage = json.loads((first / 'coverage.json').read_text())
    assert coverage['scope'] == 'selected_canary_only'
    assert coverage['source_catalog_sha256'] == 'c' * 64
    assert coverage['expected_strategy_ids'] == [row['strategy_id'] for row in exported]
    for path in first.iterdir():
        assert path.read_bytes() == (tmp_path / 'second' / path.name).read_bytes()


def test_canary_export_never_overwrites_existing_directory(tmp_path):
    from scripts import build_catalog_fast_canary as canary

    original = tmp_path / 'original.txt'
    original.write_text('preserve')
    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    with pytest.raises(ValueError, match='CANARY_OUTPUT_EXISTS'):
        canary.write_canary_catalog(
            rows, output_dir=tmp_path, reference_recipe_hashes=reference,
            available_component_ids=components, data_contract_sha256='b' * 64,
            feature_contract_sha256='a' * 64, source_catalog_sha256='c' * 64,
        )
    assert original.read_text() == 'preserve'
    assert list(tmp_path.iterdir()) == [original]


@pytest.mark.parametrize('field,value,error', [
    ('source_catalog_sha256', 'bad', 'CANARY_SOURCE_IDENTITY_INVALID'),
    ('feature_contract_sha256', 'd' * 64, 'CANARY_FEATURE_CONTRACT_MISMATCH'),
])
def test_canary_export_rejects_incompatible_source_before_writing(tmp_path, field, value, error):
    from scripts import build_catalog_fast_canary as canary

    rows = _catalog_rows()
    reference, components = _eligible_evidence(rows)
    kwargs = dict(data_contract_sha256='b' * 64,
                  feature_contract_sha256='a' * 64, source_catalog_sha256='c' * 64)
    kwargs[field] = value
    target = tmp_path / 'invalid'
    with pytest.raises(ValueError, match=error):
        canary.write_canary_catalog(rows, output_dir=target,
            reference_recipe_hashes=reference, available_component_ids=components, **kwargs)
    assert not target.exists()
