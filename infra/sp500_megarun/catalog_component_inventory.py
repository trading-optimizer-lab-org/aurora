"""Deterministic inventory of the physical components of a catalog run."""

from __future__ import annotations

from typing import Any

from aurora.infra.sp500_megarun.strategy_catalog import configuration_sha256


def collect_unique_components(
    catalog_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return every exact component once, including selected configurations.

    The selected configurations are part of the physical workload even when
    they are not present as recipes in the catalog. Keeping this inventory in
    one module prevents the admission contract, scheduler and component store
    from silently disagreeing about the amount of work.
    """

    components: dict[str, dict[str, Any]] = {}
    for row in catalog_rows:
        for component in row["components"]:
            key = str(component["configuration_sha256"])
            checked = {
                "lane_id": str(component["lane_id"]),
                "configuration": dict(component["configuration"]),
                "configuration_sha256": key,
            }
            previous = components.get(key)
            if previous is not None and previous != checked:
                raise ValueError("COMPONENT_DEFINITION_CONFLICT")
            components[key] = checked

    for row in selected_rows:
        lane_id = str(row["lane_id"])
        configuration = dict(row["configuration"])
        key = configuration_sha256(lane_id, configuration)
        checked = {
            "lane_id": lane_id,
            "configuration": configuration,
            "configuration_sha256": key,
        }
        previous = components.get(key)
        if previous is not None and previous != checked:
            raise ValueError("COMPONENT_DEFINITION_CONFLICT")
        components[key] = checked

    return tuple(components[key] for key in sorted(components))


__all__ = ["collect_unique_components"]
