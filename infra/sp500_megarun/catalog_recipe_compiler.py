"""Canonical recipe DAG compiler that preserves every catalog explanation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, canonical_sha256


_COMMUTATIVE = {"and", "vote"}


class CanonicalRecipeV1(FrozenModel):
    strategy_id: str = Field(min_length=1)
    scientific_recipe_sha256: str = Field(min_length=64, max_length=64)
    component_ids: tuple[str, ...]
    composition: Mapping[str, object]
    dag_sha256: str = Field(min_length=64, max_length=64)


class RecipeDAGV1(FrozenModel):
    schema_version: str = "1"
    recipes: tuple[CanonicalRecipeV1, ...]
    recipe_count: int = Field(ge=1)
    unique_dag_count: int = Field(ge=1)
    compiler_sha256: str = Field(min_length=64, max_length=64)


def _canonical_node(
    component_ids: tuple[str, ...],
    composition: Mapping[str, object],
) -> tuple[tuple[str, ...], dict[str, object]]:
    checked_composition = dict(composition)
    kind = str(checked_composition.get("kind"))
    checked_components = component_ids
    if kind in _COMMUTATIVE:
        checked_components = tuple(sorted(component_ids))
    return checked_components, checked_composition


def compile_recipes(rows: Sequence[Mapping[str, object]]) -> RecipeDAGV1:
    if not rows:
        raise ValueError("CATALOG_COMPILER_EMPTY")
    compiled: list[CanonicalRecipeV1] = []
    strategy_ids: set[str] = set()
    for row in sorted(rows, key=lambda item: str(item["strategy_id"])):
        strategy_id = str(row["strategy_id"])
        if strategy_id in strategy_ids:
            raise ValueError("CATALOG_COMPILER_STRATEGY_DUPLICATE")
        strategy_ids.add(strategy_id)
        components = row.get("components")
        composition = row.get("composition")
        if not isinstance(components, Sequence) or not isinstance(
            composition,
            Mapping,
        ):
            raise ValueError("CATALOG_COMPILER_ROW_INVALID")
        component_ids = tuple(
            str(component["configuration_sha256"])
            for component in components
            if isinstance(component, Mapping)
        )
        if len(component_ids) != len(components):
            raise ValueError("CATALOG_COMPILER_COMPONENT_INVALID")
        canonical_components, canonical_composition = _canonical_node(
            component_ids,
            composition,
        )
        dag_sha256 = canonical_sha256(
            {
                "components": canonical_components,
                "composition": canonical_composition,
            }
        )
        compiled.append(
            CanonicalRecipeV1(
                strategy_id=strategy_id,
                scientific_recipe_sha256=str(row["scientific_recipe_sha256"]),
                component_ids=component_ids,
                composition=dict(composition),
                dag_sha256=dag_sha256,
            )
        )
    identity = {
        "schema_version": "1",
        "recipes": compiled,
        "recipe_count": len(compiled),
        "unique_dag_count": len({item.dag_sha256 for item in compiled}),
    }
    return RecipeDAGV1(**identity, compiler_sha256=canonical_sha256(identity))


__all__ = ["CanonicalRecipeV1", "RecipeDAGV1", "compile_recipes"]
