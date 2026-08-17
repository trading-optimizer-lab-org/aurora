"""Run a bounded, train-only Atlas calibration in GitHub Actions.

The 20-minute wall-clock limit applies to the scientific sample itself.  Setup
and artifact upload are outside that receipt, so a clean timeout is a valid
calibration result rather than a failed campaign.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import pandas as pd

from aurora.infra.sp500_megarun.catalog_atlas_calibration import (
    AtlasCalibrationReceiptV1,
    target_minutes,
    target_recipe_count,
)
from aurora.infra.sp500_megarun.catalog_atlas_space import (
    AtlasSpaceV1,
    build_atlas_space,
    recipe_for_ordinal,
)
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    feature_frame_to_decisions,
    load_train_total_return_ledger,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
try:
    from scripts.run_sp500_strategy_catalog_shard import compose_signals
except ModuleNotFoundError:
    # Direct ``python scripts/...`` execution puts ``scripts`` rather than the
    # repository root on sys.path in GitHub Actions.
    from run_sp500_strategy_catalog_shard import compose_signals


_TRAIN_YEARS = tuple(range(1998, 2011))
_HARD_LIMIT_SECONDS = 1200.0
_SAFETY_FRACTION = 0.80
_MADRID = ZoneInfo("Europe/Madrid")


def _sample_ordinals(space: AtlasSpaceV1):
    """Yield every formal range once, then continue deterministically."""

    firsts = {item.start_ordinal for item in space.ranges}
    for ordinal in sorted(firsts):
        yield ordinal
    ordinal = 0
    while ordinal < space.canonical_recipe_count:
        if ordinal not in firsts:
            yield ordinal
        ordinal += 1


def calibrate(
    *,
    campaign_contract_path: Path,
    data_contract_path: Path,
    feature_contract_path: Path,
    runtime_input_pack: Path,
    catalog_dir: Path,
    output_dir: Path,
    target_end_iso: str,
    safety_fraction: float = _SAFETY_FRACTION,
) -> AtlasCalibrationReceiptV1:
    """Measure representative component and recipe throughput for 20 minutes."""

    numeric_runtime = verify_numeric_runtime_environment()
    campaign = load_and_validate_campaign_contract(Path(campaign_contract_path))
    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(
        Path(feature_contract_path), data_contract
    )
    verify_runtime_input_pack(
        Path(runtime_input_pack),
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(campaign),
    )
    if campaign.search_end != "2010-12-31":
        raise ValueError("ATLAS_CALIBRATION_SEARCH_END_INVALID")
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_CALIBRATION_DATA_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_CALIBRATION_FEATURE_BOUNDARY_OPEN")

    # The catalog directory is generated in the same job and is checked before
    # the scientific clock starts.
    manifest = json.loads((Path(catalog_dir) / "manifest.json").read_text("utf-8"))
    if manifest.get("validation_opened") or manifest.get("locked_opened"):
        raise ValueError("ATLAS_CALIBRATION_CATALOG_BOUNDARY_OPEN")
    catalog_sha256 = str(manifest.get("manifest_sha256", ""))
    space, components = build_atlas_space(feature_contract)
    component_by_hash = {
        component.configuration_sha256: component
        for rows in components.values()
        for component in rows
    }

    snapshot = Path(runtime_input_pack) / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    baselines = {
        name: Path(runtime_input_pack) / f"baseline_{name}"
        for name in ("price", "market", "macro")
    }
    evaluator = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs=baselines,
    )
    objective = FastTrainObjective(
        ledger,
        target_years=_TRAIN_YEARS,
        allowed_end=campaign.search_end,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    result_path = output_dir / "calibration_sample.jsonl"
    component_cache: dict[str, pd.Series] = {}
    physical_component_seconds = 0.0
    recipe_count = 0
    cache_hit_count = 0
    started_at = datetime.now(_MADRID)
    scientific_started = time.monotonic()
    timed_out_cleanly = False
    result_store_started = time.monotonic()
    with result_path.open("x", encoding="utf-8", newline="\n") as result_file:
        for ordinal in _sample_ordinals(space):
            elapsed = time.monotonic() - scientific_started
            if elapsed >= _HARD_LIMIT_SECONDS:
                timed_out_cleanly = True
                break
            recipe = recipe_for_ordinal(space, components, ordinal)
            signals = []
            for component_id in recipe["components"]:
                component = component_by_hash[str(component_id)]
                signal = component_cache.get(component.configuration_sha256)
                if signal is None:
                    component_started = time.monotonic()
                    frame = evaluator(component.lane_id, component.configuration)
                    signal = feature_frame_to_decisions(
                        frame,
                        allowed_end=campaign.search_end,
                    ).reindex(ledger.index)
                    component_cache[component.configuration_sha256] = signal
                    physical_component_seconds += time.monotonic() - component_started
                else:
                    cache_hit_count += 1
                signals.append(signal)
            recipe_started = time.monotonic()
            decisions = compose_signals(signals, recipe["composition"])
            direction = int(recipe["composition"].get("direction", 1))
            if direction == -1:
                decisions = -decisions
            scored = objective.score(decisions)
            result_file.write(
                json.dumps(
                    {
                        "ordinal": ordinal,
                        "strategy_id": recipe["strategy_id"],
                        "scientific_recipe_sha256": recipe["scientific_recipe_sha256"],
                        "positive_weeks": scored.weekly_calendar_metrics["positive_weeks"],
                        "position_count": len(scored.positions),
                        "validation_opened": False,
                        "locked_opened": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            recipe_count += 1
            # Include composition and objective time in the measured recipe rate.
            _ = time.monotonic() - recipe_started
            result_file.flush()
    result_store_seconds = time.monotonic() - result_store_started
    wall_seconds = min(_HARD_LIMIT_SECONDS, time.monotonic() - scientific_started)
    stopped_at = datetime.now(_MADRID)
    rate = recipe_count * 60.0 / wall_seconds if wall_seconds > 0 else 0.0
    available = target_minutes(
        now_iso=stopped_at.isoformat(),
        target_end_iso=target_end_iso,
    )
    receipt = AtlasCalibrationReceiptV1(
        schema_version="1",
        catalog_sha256=catalog_sha256,
        started_at_iso=started_at.isoformat(),
        stopped_at_iso=stopped_at.isoformat(),
        wall_seconds=wall_seconds,
        hard_limit_seconds=1200.0,
        timed_out_cleanly=timed_out_cleanly,
        physical_recipe_count=recipe_count,
        cache_hit_count=cache_hit_count,
        physical_component_count=len(component_cache),
        physical_component_seconds=physical_component_seconds,
        recipe_seconds=max(0.0, wall_seconds - physical_component_seconds),
        result_store_seconds=result_store_seconds,
        recipes_per_minute=rate,
        recommended_mode="component_warm",
        available_minutes_to_target=available,
        safety_fraction=safety_fraction,
        target_recipe_count_with_margin=target_recipe_count(
            available_minutes=available,
            recipes_per_minute=rate,
            safety_fraction=safety_fraction,
        ),
        validation_opened=False,
        locked_opened=False,
    )
    receipt_path = output_dir / "calibration_receipt.json"
    receipt_path.write_bytes((receipt.model_dump_json(indent=2) + "\n").encode("utf-8"))
    (output_dir / "runtime_profile.json").write_text(
        json.dumps(numeric_runtime, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-end-iso", required=True)
    parser.add_argument("--safety-fraction", type=float, default=_SAFETY_FRACTION)
    args = parser.parse_args()
    receipt = calibrate(
        campaign_contract_path=args.campaign_contract,
        data_contract_path=args.data_contract,
        feature_contract_path=args.feature_contract,
        runtime_input_pack=args.runtime_input_pack,
        catalog_dir=args.catalog_dir,
        output_dir=args.output_dir,
        target_end_iso=args.target_end_iso,
        safety_fraction=args.safety_fraction,
    )
    print(receipt.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
