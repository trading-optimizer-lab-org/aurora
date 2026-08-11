"""GitHub-only infrastructure smoke for official DEHB and ConfigSpace."""

from __future__ import annotations

import hashlib
import importlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
from typing import TYPE_CHECKING, Any, Mapping

from aurora.infra.sp500_megarun.dehb_configspace import (
    ETA,
    FIDELITIES,
    LaneConfigSpace,
    build_all_lane_configspaces,
    build_cross_manifest,
    build_dehb_space_manifest,
    build_lane_configspace,
)

if TYPE_CHECKING:
    from aurora.infra.sp500_megarun.feature_contract import FrozenFeatureContract


class OfficialDehbSmokeError(RuntimeError):
    """Raised when official DEHB cannot be proven safe for the campaign."""


_LOCK_DOMAIN = b"aurora-dehb-official-lock-v1\0"
_EXPECTED_LOCK_BYTES = 40742
_EXPECTED_LOCK_DOMAIN_SHA256 = (
    "89617c4ca6fe54739804e039177c61b8a62933b921cd65617d93fce634a06734"
)
_REQUIRED_LOCK_PINS = (
    b"dehb==0.1.2",
    b"configspace==1.2.2",
    b"numpy==1.26.4",
    b"pandas==2.2.3",
    b"pyarrow==16.1.0",
    b"dask==2024.7.1",
    b"distributed==2024.7.1",
    b"scipy==1.13.1",
)


def require_github_actions() -> None:
    """Forbid execution of this infrastructure campaign on a local machine."""

    if os.environ.get("GITHUB_ACTIONS", "").casefold() != "true":
        raise OfficialDehbSmokeError("GITHUB_ACTIONS_REQUIRED")


def require_empty_output_directory(output_dir: Path) -> None:
    """Never mix one smoke receipt with an earlier run."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise OfficialDehbSmokeError(f"OUTPUT_DIRECTORY_NOT_EMPTY:{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def verify_dependency_lock(path: Path) -> Mapping[str, Any]:
    """Bind the isolated lock bytes and every direct scientific runtime pin."""

    raw = path.read_bytes()
    digest = hashlib.sha256(_LOCK_DOMAIN + raw).hexdigest()
    missing_pins = [pin.decode("ascii") for pin in _REQUIRED_LOCK_PINS if pin not in raw]
    if len(raw) != _EXPECTED_LOCK_BYTES:
        raise OfficialDehbSmokeError(f"DEPENDENCY_LOCK_SIZE_MISMATCH:{len(raw)}")
    if digest != _EXPECTED_LOCK_DOMAIN_SHA256:
        raise OfficialDehbSmokeError(f"DEPENDENCY_LOCK_HASH_MISMATCH:{digest}")
    if missing_pins:
        raise OfficialDehbSmokeError(
            f"DEPENDENCY_LOCK_PIN_MISSING:{','.join(missing_pins)}"
        )
    return {
        "verified": True,
        "byte_count": len(raw),
        "domain_sha256": digest,
    }


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _configuration_dict(config: Any) -> Mapping[str, Any]:
    if isinstance(config, Mapping):
        raw = config
    else:
        try:
            raw = dict(config)
        except (TypeError, ValueError) as exc:
            raise OfficialDehbSmokeError("INVALID_DEHB_CONFIGURATION") from exc
    return {str(key): _json_value(value) for key, value in raw.items()}


def synthetic_objective(config: Any, fidelity: float, **_: Any) -> Mapping[str, Any]:
    """Deterministic data-free objective used only to test official DEHB wiring."""

    normalized = _configuration_dict(config)
    fidelity_value = int(float(fidelity))
    if fidelity_value not in FIDELITIES:
        raise OfficialDehbSmokeError(f"UNEXPECTED_FIDELITY:{fidelity_value}")
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    deterministic_component = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    fitness = deterministic_component / float(2**64) + 1.0 / fidelity_value
    return {
        "fitness": float(fitness),
        "cost": float(fidelity_value),
        "info": {
            "synthetic_only": True,
            "fidelity": fidelity_value,
            "config_sha256": hashlib.sha256(payload).hexdigest(),
        },
    }


def _runtime_versions() -> Mapping[str, str]:
    return {
        "DEHB": metadata.version("DEHB"),
        "ConfigSpace": metadata.version("ConfigSpace"),
        "python": platform.python_version(),
    }


def _load_official_dehb() -> Any:
    try:
        module = importlib.import_module("dehb")
    except ModuleNotFoundError as exc:
        raise OfficialDehbSmokeError("OFFICIAL_DEHB_DEPENDENCY_MISSING") from exc
    if not hasattr(module, "DEHB"):
        raise OfficialDehbSmokeError("OFFICIAL_DEHB_CLASS_MISSING")
    return module


def _new_dehb(
    dehb_module: Any,
    lane_space: LaneConfigSpace,
    *,
    n_workers: int,
    seed: int,
    output_path: Path,
    resume: bool = False,
) -> Any:
    return dehb_module.DEHB(
        cs=lane_space.configspace,
        f=synthetic_objective,
        min_fidelity=FIDELITIES[0],
        max_fidelity=FIDELITIES[-1],
        eta=ETA,
        seed=seed,
        n_workers=n_workers,
        output_path=output_path,
        save_freq="end",
        log_level="WARNING",
        resume=resume,
    )


def _close_dehb(instance: Any) -> None:
    client = getattr(instance, "client", None)
    if client is not None:
        client.close()
        instance.client = None


def _verify_exact_spaces(
    contract: FrozenFeatureContract,
    spaces: tuple[LaneConfigSpace, ...],
) -> None:
    if len(spaces) != 240:
        raise OfficialDehbSmokeError(f"EXPECTED_240_CONFIGSPACES:{len(spaces)}")
    for lane, row in zip(contract.lanes, spaces, strict=True):
        if row.lane_id != lane.lane_id or row.canonical_sha256 != lane.canonical_sha256:
            raise OfficialDehbSmokeError(f"CONFIGSPACE_LINEAGE_MISMATCH:{lane.lane_id}")
        if len(row.configspace) != len(lane.parameter_space):
            raise OfficialDehbSmokeError(f"CONFIGSPACE_DIMENSION_MISMATCH:{lane.lane_id}")
        default = _configuration_dict(row.configspace.get_default_configuration())
        for name, choices in lane.parameter_space.items():
            actual_choices = tuple(_json_value(value) for value in row.configspace[name].choices)
            expected_choices = tuple(_json_value(value) for value in choices)
            if actual_choices != expected_choices:
                raise OfficialDehbSmokeError(
                    f"CONFIGSPACE_CHOICES_MISMATCH:{lane.lane_id}:{name}"
                )
            if default[name] != expected_choices[0]:
                raise OfficialDehbSmokeError(
                    f"CONFIGSPACE_DEFAULT_MISMATCH:{lane.lane_id}:{name}"
                )


def _fixed_probe_configs(space: Any, *, count: int) -> list[Mapping[str, Any]]:
    space.seed(918273)
    rows = [_configuration_dict(space.get_default_configuration())]
    rows.extend(_configuration_dict(space.sample_configuration()) for _ in range(count - 1))
    return rows


def _verify_worker_equivalence(
    dehb_module: Any,
    contract: FrozenFeatureContract,
    *,
    output_dir: Path,
) -> bool:
    reference: list[Mapping[str, Any]] | None = None
    fidelities = [FIDELITIES[index % len(FIDELITIES)] for index in range(12)]
    for n_workers in (1, 2, 4):
        lane_space = build_lane_configspace(contract, "F001", seed=918273)
        configs = _fixed_probe_configs(lane_space.configspace, count=len(fidelities))
        instance = _new_dehb(
            dehb_module,
            lane_space,
            n_workers=n_workers,
            seed=918273,
            output_path=output_dir / f"worker_equivalence_n{n_workers}",
        )
        try:
            if n_workers == 1:
                results = [
                    synthetic_objective(config, fidelity)
                    for config, fidelity in zip(configs, fidelities, strict=True)
                ]
            else:
                futures = [
                    instance.client.submit(synthetic_objective, config, fidelity)
                    for config, fidelity in zip(configs, fidelities, strict=True)
                ]
                results = instance.client.gather(futures)
            normalized = [_json_value(result) for result in results]
            if reference is None:
                reference = normalized
            elif normalized != reference:
                return False
        finally:
            _close_dehb(instance)
    return reference is not None


def _job_result_signature(job: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    payload = {
        "config": _configuration_dict(job["config"]),
        "fidelity": int(float(job["fidelity"])),
        "fitness": result["fitness"],
        "cost": result["cost"],
        "info": result["info"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ask_tell(instance: Any, *, count: int) -> list[str]:
    signatures: list[str] = []
    for _ in range(count):
        job = instance.ask()
        result = synthetic_objective(job["config"], job["fidelity"])
        instance.tell(job, result)
        signatures.append(_job_result_signature(job, result))
    return signatures


def _verify_checkpoint_resume(
    dehb_module: Any,
    contract: FrozenFeatureContract,
    *,
    output_dir: Path,
) -> bool:
    seed = 412009
    control_space = build_lane_configspace(contract, "F021", seed=seed)
    control = _new_dehb(
        dehb_module,
        control_space,
        n_workers=1,
        seed=seed,
        output_path=output_dir / "checkpoint_control",
    )
    try:
        _ask_tell(control, count=32)
        expected_tail = _ask_tell(control, count=16)
    finally:
        _close_dehb(control)

    checkpoint_path = output_dir / "checkpoint_resume"
    checkpoint_space = build_lane_configspace(contract, "F021", seed=seed)
    checkpoint = _new_dehb(
        dehb_module,
        checkpoint_space,
        n_workers=1,
        seed=seed,
        output_path=checkpoint_path,
    )
    try:
        _ask_tell(checkpoint, count=32)
        checkpoint.save()
    finally:
        _close_dehb(checkpoint)

    resumed_space = build_lane_configspace(contract, "F021", seed=seed)
    resumed = _new_dehb(
        dehb_module,
        resumed_space,
        n_workers=1,
        seed=seed,
        output_path=checkpoint_path,
        resume=True,
    )
    try:
        actual_tail = _ask_tell(resumed, count=16)
    finally:
        _close_dehb(resumed)
    return actual_tail == expected_tail


def _verify_actual_four_worker_run(
    dehb_module: Any,
    contract: FrozenFeatureContract,
    *,
    output_dir: Path,
) -> Mapping[str, Any]:
    lane_space = build_lane_configspace(contract, "F003", seed=240403)
    instance = _new_dehb(
        dehb_module,
        lane_space,
        n_workers=4,
        seed=240403,
        output_path=output_dir / "actual_four_worker_run",
    )
    try:
        trajectory, runtime, history = instance.run(brackets=1)
        records = list(history)
        fidelities_seen = sorted({int(float(record[4])) for record in records})
        valid = (
            len(records) >= 40
            and len(trajectory) == len(records)
            and len(runtime) == len(records)
            and all(math.isfinite(float(record[2])) for record in records)
            and all(int(float(record[4])) in FIDELITIES for record in records)
            and all(bool(record[5].get("synthetic_only")) for record in records)
            and fidelities_seen == list(FIDELITIES)
        )
        return {
            "valid": valid,
            "n_workers": 4,
            "function_evaluations": len(records),
            "fidelities_seen": fidelities_seen,
            "incumbent_fitness": float(instance.inc_score),
        }
    finally:
        _close_dehb(instance)


def validate_official_smoke_report(report: Mapping[str, Any]) -> None:
    """Fail unless every technical and scientific gate is simultaneously true."""

    expected = {
        "ready": True,
        "official_dehb_version": "0.1.2",
        "configspace_version": "1.2.2",
        "lane_count": 240,
        "all_configspaces_exact": True,
        "fidelities": [1, 3, 9, 27],
        "eta": 3,
        "actual_four_worker_run": True,
        "worker_equivalence_1_2_4": True,
        "checkpoint_resume_exact": True,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "snapshot_mounted": False,
        "dependency_lock_verified": True,
    }
    failures = [key for key, value in expected.items() if report.get(key) != value]
    if failures:
        raise OfficialDehbSmokeError(f"SMOKE_GATE_FAILED:{','.join(failures)}")


def run_official_dehb_smoke(
    *,
    data_contract_path: Path,
    feature_contract_path: Path,
    dependency_lock_path: Path,
    output_dir: Path,
) -> Mapping[str, Any]:
    """Exercise the official packages without loading any market snapshot."""

    from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
    from aurora.infra.sp500_megarun.feature_contract import (
        load_and_validate_feature_contract,
    )

    require_github_actions()
    require_empty_output_directory(output_dir)
    data_contract = load_and_validate_contract(data_contract_path)
    contract = load_and_validate_feature_contract(feature_contract_path, data_contract)
    versions = _runtime_versions()
    if versions["DEHB"] != "0.1.2" or versions["ConfigSpace"] != "1.2.2":
        raise OfficialDehbSmokeError(
            f"UNEXPECTED_OFFICIAL_RUNTIME:{versions['DEHB']}:{versions['ConfigSpace']}"
        )
    dehb_module = _load_official_dehb()
    lock_receipt = verify_dependency_lock(dependency_lock_path)
    spaces = build_all_lane_configspaces(contract, base_seed=730000)
    _verify_exact_spaces(contract, spaces)

    runs_dir = output_dir / "dehb_runs"
    runs_dir.mkdir()
    worker_equivalence = _verify_worker_equivalence(
        dehb_module, contract, output_dir=runs_dir
    )
    checkpoint_resume = _verify_checkpoint_resume(
        dehb_module, contract, output_dir=runs_dir
    )
    four_worker = _verify_actual_four_worker_run(
        dehb_module, contract, output_dir=runs_dir
    )
    manifest = build_dehb_space_manifest(contract, runtime_versions=versions)
    cross_manifest = build_cross_manifest(contract)
    report: dict[str, Any] = {
        "ready": bool(worker_equivalence and checkpoint_resume and four_worker["valid"]),
        "official_dehb_version": versions["DEHB"],
        "configspace_version": versions["ConfigSpace"],
        "python_version": versions["python"],
        "dependency_lock_verified": lock_receipt["verified"],
        "dependency_lock_bytes": lock_receipt["byte_count"],
        "dependency_lock_domain_sha256": lock_receipt["domain_sha256"],
        "feature_contract_sha256": contract.sha256,
        "space_manifest_sha256": manifest["manifest_sha256"],
        "cross_manifest_sha256": cross_manifest["cross_manifest_sha256"],
        "lane_count": len(spaces),
        "all_configspaces_exact": True,
        "fidelities": list(FIDELITIES),
        "eta": ETA,
        "actual_four_worker_run": bool(four_worker["valid"]),
        "four_worker_details": four_worker,
        "worker_equivalence_1_2_4": worker_equivalence,
        "checkpoint_resume_exact": checkpoint_resume,
        "search_end": contract.search_end.isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "snapshot_mounted": False,
        "github_sha": os.environ.get("GITHUB_SHA", ""),
    }
    validate_official_smoke_report(report)
    (output_dir / "dehb_space_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "dehb_cross_manifest.json").write_text(
        json.dumps(cross_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "dehb_official_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


__all__ = [
    "OfficialDehbSmokeError",
    "require_empty_output_directory",
    "require_github_actions",
    "run_official_dehb_smoke",
    "synthetic_objective",
    "validate_official_smoke_report",
    "verify_dependency_lock",
]
