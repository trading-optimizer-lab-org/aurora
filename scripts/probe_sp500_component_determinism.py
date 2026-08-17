"""Rebuild one train-only catalog component on an isolated GitHub runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy

from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    PreparedLaneCandidate,
    candidate_fingerprints,
    feature_frame_to_decisions,
    load_train_total_return_ledger,
    score_prepared_lane_candidate,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    verify_strategy_catalog_directory,
)


def _sha256(domain: bytes, *payloads: bytes) -> str:
    digest = hashlib.sha256(domain)
    for payload in payloads:
        digest.update(payload)
    return digest.hexdigest()


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text("utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.partition(":")[2].strip()
    return platform.processor() or platform.machine()


def _feature_sha256(frame: pd.DataFrame) -> str:
    values = pd.to_numeric(frame["value"], errors="raise").to_numpy(np.float64)
    finite = np.isfinite(values)
    canonical = np.where(finite, values, 0.0).astype("<f8", copy=False)
    return _sha256(
        b"catalog-feature-probe-v1\0",
        np.packbits(finite, bitorder="little").tobytes(),
        canonical.tobytes(),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-config", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--target-index", type=int, required=True)
    parser.add_argument("--repeat-index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    numeric_runtime = verify_numeric_runtime_environment()
    verify_catalog_plan_token(
        args.run_plan,
        admission_token_sha256=args.admission_token,
    )
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract,
        data_contract,
    )
    receipt = verify_strategy_catalog_directory(args.catalog_dir)
    if receipt["validation_opened"] or receipt["locked_opened"]:
        raise SystemExit("COMPONENT_PROBE_CATALOG_BOUNDARY_OPEN")
    verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            campaign
        ),
    )
    config = json.loads(args.diagnostic_config.read_text("utf-8"))
    strategy_ids = tuple(str(value) for value in config["strategy_ids"])
    if not 0 <= args.target_index < len(strategy_ids) or args.repeat_index < 0:
        raise SystemExit("COMPONENT_PROBE_INDEX_INVALID")
    target_id = strategy_ids[args.target_index]
    catalog = {
        str(row["strategy_id"]): row
        for row in (
            json.loads(line)
            for line in (args.catalog_dir / "catalog.jsonl")
            .read_text("utf-8")
            .splitlines()
            if line
        )
    }
    target = catalog[target_id]
    if target["strategy_kind"] != "single" or len(target["components"]) != 1:
        raise SystemExit("COMPONENT_PROBE_TARGET_NOT_SINGLE")
    component: dict[str, Any] = target["components"][0]
    snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end=campaign.search_end,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
    )
    evaluator = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs={
            name: args.runtime_input_pack / f"baseline_{name}"
            for name in ("price", "market", "macro")
        },
    )
    started = time.perf_counter()
    frame = evaluator(component["lane_id"], component["configuration"])
    decisions = feature_frame_to_decisions(
        frame,
        allowed_end=campaign.search_end,
    ).reindex(ledger.index)
    compute_seconds = time.perf_counter() - started
    signal = decisions.fillna(0.0).to_numpy(np.int8)
    values = pd.to_numeric(frame["value"], errors="raise").to_numpy(np.float64)
    finite_absolute = np.abs(values[np.isfinite(values)])
    recipe_configuration = {
        "scientific_recipe_sha256": target["scientific_recipe_sha256"]
    }
    strategy_fingerprint, position_fingerprint = candidate_fingerprints(
        target_id,
        recipe_configuration,
        decisions,
    )
    prepared = PreparedLaneCandidate(
        lane_id=target_id,
        configuration=recipe_configuration,
        fidelity=27,
        target_years=tuple(range(1998, 2011)),
        decisions=decisions,
        strategy_fingerprint=strategy_fingerprint,
        position_fingerprint=position_fingerprint,
    )
    result = score_prepared_lane_candidate(
        prepared,
        ledger=ledger,
        fidelity_years={27: tuple(range(1998, 2011))},
        allowed_end=campaign.search_end,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output.parent / "feature_values.npy", values, allow_pickle=False)
    np.save(args.output.parent / "decisions.npy", signal, allow_pickle=False)
    payload = {
        "schema_version": 1,
        "target_index": args.target_index,
        "repeat_index": args.repeat_index,
        "strategy_id": target_id,
        "lane_id": component["lane_id"],
        "configuration_sha256": component["configuration_sha256"],
        "feature_sha256": _feature_sha256(frame),
        "signal_sha256": _sha256(
            b"catalog-component-probe-v1\0",
            signal.tobytes(),
        ),
        "position_fingerprint": position_fingerprint,
        "strategy_fingerprint": strategy_fingerprint,
        "result": result,
        "positive_decisions": int(np.count_nonzero(signal == 1)),
        "negative_decisions": int(np.count_nonzero(signal == -1)),
        "flat_decisions": int(np.count_nonzero(signal == 0)),
        "near_zero_counts": {
            f"le_{threshold:g}": int(np.count_nonzero(finite_absolute <= threshold))
            for threshold in (1e-12, 1e-10, 1e-8, 1e-6)
        },
        "minimum_nonzero_absolute_value": (
            float(finite_absolute[finite_absolute > 0.0].min())
            if np.any(finite_absolute > 0.0)
            else None
        ),
        "compute_seconds": compute_seconds,
        "cpu_model": _cpu_model(),
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "openblas_coretype": os.environ.get("OPENBLAS_CORETYPE"),
        "numpy_disabled_cpu_features": os.environ.get("NPY_DISABLE_CPU_FEATURES"),
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "numeric_runtime_profile_sha256": numeric_runtime_profile_sha256(),
        "numeric_runtime_verified": numeric_runtime["passed"],
        "train_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
