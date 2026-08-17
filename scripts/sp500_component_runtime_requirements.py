"""List runtime datasets required by one immutable component shard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    RUNTIME_FRAGMENT_DATASET_IDS,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    runtime_dataset_ids_for_lane,
)
from aurora.infra.sp500_megarun.catalog_component_inventory import (
    collect_unique_components,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--selected-config", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--component-schedule", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_contract(args.data_contract)
    lane_datasets = {
        lane.lane_id: set(runtime_dataset_ids_for_lane(lane.lane_id))
        for lane in contract.lanes
    }
    catalog_rows = [
        json.loads(line)
        for line in args.catalog.read_text("utf-8").splitlines()
        if line
    ]
    selected_rows = json.loads(args.selected_config.read_text("utf-8"))
    components = {
        str(component["configuration_sha256"]): str(component["lane_id"])
        for component in collect_unique_components(catalog_rows, selected_rows)
    }
    schedule = json.loads(args.component_schedule.read_text("utf-8"))
    shards = schedule.get("shards")
    if not isinstance(shards, list) or not 0 <= args.shard_index < len(shards):
        raise SystemExit("COMPONENT_RUNTIME_SCHEDULE_INVALID")
    component_ids = shards[args.shard_index].get("component_ids")
    if not isinstance(component_ids, list):
        raise SystemExit("COMPONENT_RUNTIME_SHARD_INVALID")
    required: set[str] = set()
    for component_id in component_ids:
        lane_id = components.get(str(component_id))
        if lane_id is None or lane_id not in lane_datasets:
            raise SystemExit(f"COMPONENT_RUNTIME_LANE_UNKNOWN:{component_id}")
        required.update(lane_datasets[lane_id])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fragment_required = required.intersection(RUNTIME_FRAGMENT_DATASET_IDS)
    args.output.write_text(
        "\n".join(sorted(fragment_required))
        + ("\n" if fragment_required else ""),
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
