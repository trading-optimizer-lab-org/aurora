"""Build and qualify measured GitHub hot-path profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import deep_thaw_json
from aurora.infra.github_performance.engines import EngineTrial
from aurora.infra.github_performance.native import (
    HotPathQualificationContract,
    HotPathProfile,
    OptimizationStageEvidence,
    build_hot_path_profile,
    qualify_native_candidate,
    write_native_qualification_artifacts,
)


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _profile(args: argparse.Namespace) -> int:
    contract = HotPathQualificationContract.model_validate(
        _read_json(args.qualification_contract)
    )
    table = pq.read_table(
        args.runtime_breakdown,
        columns=["phase", "duration_seconds"],
    )
    profile = build_hot_path_profile(
        table.to_pylist(),
        node_name=args.node_name,
        phase_names=args.phase,
        invocation_count=args.invocation_count,
        pure_bounded_io=contract.pure_bounded_io,
        network_access=contract.network_access,
        mutable_external_state=contract.mutable_external_state,
        python_reference_available=contract.python_reference_available,
        frequently_changing_experimental_code=(
            contract.frequently_changing_experimental_code
        ),
    )
    _write_json(args.output, profile)
    return 0


def _qualify(args: argparse.Namespace) -> int:
    profile = HotPathProfile.model_validate(_read_json(args.hot_path_profile))
    trial_payload = _read_json(args.engine_trials)
    trial_rows = (
        trial_payload["trials"]
        if isinstance(trial_payload, dict)
        else trial_payload
    )
    trials = tuple(EngineTrial.model_validate(row) for row in trial_rows)
    evidence_payload = _read_json(args.optimization_evidence)
    evidence_rows = (
        evidence_payload["optimization_evidence"]
        if isinstance(evidence_payload, dict)
        and "optimization_evidence" in evidence_payload
        else evidence_payload
    )
    evidence = tuple(
        OptimizationStageEvidence.model_validate(row)
        for row in evidence_rows
    )
    qualification = qualify_native_candidate(
        profile,
        trials,
        candidate_engine=args.candidate_engine,
        optimization_evidence=evidence,
        hot_path_min_fraction=args.hot_path_min_fraction,
        projected_gain_minimum=args.projected_gain_minimum,
        invocation_count_minimum=args.invocation_count_minimum,
    )
    write_native_qualification_artifacts(
        profile,
        qualification,
        trials,
        args.output_dir,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile")
    profile.add_argument("--runtime-breakdown", required=True, type=Path)
    profile.add_argument("--node-name", required=True)
    profile.add_argument("--phase", action="append", required=True)
    profile.add_argument("--invocation-count", required=True, type=int)
    profile.add_argument(
        "--qualification-contract",
        required=True,
        type=Path,
    )
    profile.add_argument("--output", required=True, type=Path)
    profile.set_defaults(handler=_profile)

    qualify = subparsers.add_parser("qualify")
    qualify.add_argument("--hot-path-profile", required=True, type=Path)
    qualify.add_argument("--engine-trials", required=True, type=Path)
    qualify.add_argument("--optimization-evidence", required=True, type=Path)
    qualify.add_argument(
        "--candidate-engine",
        required=True,
        choices=(
            "numpy",
            "numba",
            "arrow",
            "duckdb",
            "rust",
            "processes",
            "threads",
        ),
    )
    qualify.add_argument(
        "--hot-path-min-fraction",
        type=float,
        default=0.10,
    )
    qualify.add_argument(
        "--projected-gain-minimum",
        type=float,
        default=0.05,
    )
    qualify.add_argument(
        "--invocation-count-minimum",
        type=int,
        default=2,
    )
    qualify.add_argument("--output-dir", required=True, type=Path)
    qualify.set_defaults(handler=_qualify)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
