"""Hash-bound deterministic evaluation cache for the SP500 DEHB campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Callable, Mapping


_LANE_PATTERN = re.compile(r"F(?:00[1-9]|0[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)")
_RUNTIME_ONLY_INFO_FIELDS = {
    "objective_runtime_seconds",
    "physical_runtime_seconds",
}
_SCIENTIFIC_SIGNIFICANT_DIGITS = 12


class EvaluationCacheError(ValueError):
    """Raised when cache evidence is malformed or scientifically incompatible."""


class EvaluationCacheConflictError(EvaluationCacheError):
    """Raised when one deterministic key has two different scientific results."""


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvaluationCacheError("EVALUATION_CACHE_NONFINITE_VALUE")
        return value
    raise EvaluationCacheError(f"EVALUATION_CACHE_NON_JSON_VALUE:{type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvaluationCacheError("EVALUATION_CACHE_VALUE_NOT_CANONICAL") from exc


def _normalize_scientific_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_scientific_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_scientific_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvaluationCacheError("EVALUATION_CACHE_NONFINITE_VALUE")
        normalized = float(format(value, f".{_SCIENTIFIC_SIGNIFICANT_DIGITS}g"))
        return 0.0 if normalized == 0.0 else normalized
    return value


def normalize_scientific_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Put hardware-level float noise on one stable scientific grid."""

    if not isinstance(result, Mapping):
        raise EvaluationCacheError("EVALUATION_CACHE_RESULT_NOT_MAPPING")
    raw = _json_value(result)
    normalized = _normalize_scientific_value(raw)
    if not isinstance(normalized, Mapping):  # pragma: no cover - guarded above
        raise EvaluationCacheError("EVALUATION_CACHE_RESULT_NOT_MAPPING")
    raw_info = raw.get("info") if isinstance(raw, Mapping) else None
    normalized_info = normalized.get("info")
    if isinstance(raw_info, Mapping) and isinstance(normalized_info, Mapping):
        normalized = dict(normalized)
        normalized["info"] = dict(normalized_info)
        if "config" in raw_info:
            normalized["info"]["config"] = raw_info["config"]
        for key in _RUNTIME_ONLY_INFO_FIELDS:
            if key in raw_info:
                normalized["info"][key] = raw_info[key]
    return normalized


def _scientific_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = normalize_scientific_result(result)
    if not isinstance(normalized, Mapping):  # pragma: no cover - guarded by caller
        raise EvaluationCacheError("EVALUATION_CACHE_RESULT_NOT_MAPPING")
    info = normalized.get("info")
    if isinstance(info, Mapping):
        normalized = dict(normalized)
        normalized["info"] = {
            key: value for key, value in info.items() if key not in _RUNTIME_ONLY_INFO_FIELDS
        }
    return normalized


def scientific_result_sha256(result: Mapping[str, Any]) -> str:
    """Hash scientific output while excluding runtime-only measurements."""

    if not isinstance(result, Mapping):
        raise EvaluationCacheError("EVALUATION_CACHE_RESULT_NOT_MAPPING")
    return hashlib.sha256(_canonical_bytes(_scientific_result(result))).hexdigest()


def scientific_evaluator_binding_sha256(
    *,
    code_commit_sha: str,
    campaign_contract_sha256: str,
    runtime_scientific_input_binding_sha256: str,
    numeric_runtime_profile_sha256: str,
) -> str:
    """Bind cache reuse to the exact frozen code, campaign and training inputs."""

    commit = str(code_commit_sha).lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise EvaluationCacheError("EVALUATION_CACHE_CODE_COMMIT_SHA_INVALID")
    if not _is_sha256(campaign_contract_sha256):
        raise EvaluationCacheError("EVALUATION_CACHE_CAMPAIGN_SHA256_INVALID")
    if not _is_sha256(runtime_scientific_input_binding_sha256):
        raise EvaluationCacheError("EVALUATION_CACHE_RUNTIME_BINDING_SHA256_INVALID")
    if not _is_sha256(numeric_runtime_profile_sha256):
        raise EvaluationCacheError("EVALUATION_CACHE_NUMERIC_RUNTIME_SHA256_INVALID")
    payload = {
        "schema_version": 2,
        "code_commit_sha": commit,
        "campaign_contract_sha256": str(campaign_contract_sha256),
        "runtime_scientific_input_binding_sha256": str(runtime_scientific_input_binding_sha256),
        "numeric_runtime_profile_sha256": str(numeric_runtime_profile_sha256),
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def audit_multiprocess_determinism(
    objective: Callable[[Any, float], Mapping[str, Any]],
    *,
    lane_id: str,
    configuration: Mapping[str, Any],
    fidelity: int,
    executor_factory: Any,
) -> Mapping[str, Any]:
    """Evaluate one fixed point twice in separate slots and require exact science."""

    with executor_factory(max_workers=2) as executor:
        futures = [
            executor.submit(objective, dict(configuration), float(fidelity)) for _ in range(2)
        ]
        results = [future.result() for future in futures]
    hashes = [scientific_result_sha256(result) for result in results]
    for result in results:
        info = result.get("info")
        if not isinstance(info, Mapping):
            raise EvaluationCacheError("EVALUATION_DETERMINISM_INFO_INVALID")
        if info.get("validation_opened") is not False:
            raise EvaluationCacheError("EVALUATION_DETERMINISM_OPENED_VALIDATION")
        if info.get("locked_opened") is not False:
            raise EvaluationCacheError("EVALUATION_DETERMINISM_OPENED_LOCKED")
    if len(set(hashes)) != 1:
        raise EvaluationCacheConflictError(f"EVALUATION_DETERMINISM_AUDIT_CONFLICT:{lane_id}")
    return {
        "schema_version": 1,
        "lane_id": str(lane_id),
        "fidelity": int(fidelity),
        "configuration_sha256": hashlib.sha256(_canonical_bytes(configuration)).hexdigest(),
        "result_sha256": hashes[0],
        "independent_process_evaluations": 2,
        "passed": True,
        "validation_opened": False,
        "locked_opened": False,
    }


@dataclass(frozen=True)
class EvaluationCacheKeyV1:
    """Stable identity for one deterministic lane/configuration/fidelity result."""

    scientific_evaluator_sha256: str
    train_snapshot_manifest_sha256: str
    lane_id: str
    configuration: Mapping[str, Any]
    fidelity: int
    sha256: str
    schema_version: int = 1

    @classmethod
    def build(
        cls,
        *,
        scientific_evaluator_sha256: str,
        train_snapshot_manifest_sha256: str,
        lane_id: str,
        configuration: Mapping[str, Any],
        fidelity: int | float,
    ) -> "EvaluationCacheKeyV1":
        if not _is_sha256(scientific_evaluator_sha256):
            raise EvaluationCacheError("EVALUATION_CACHE_EVALUATOR_SHA256_INVALID")
        if not _is_sha256(train_snapshot_manifest_sha256):
            raise EvaluationCacheError("EVALUATION_CACHE_TRAIN_SHA256_INVALID")
        if _LANE_PATTERN.fullmatch(str(lane_id)) is None:
            raise EvaluationCacheError("EVALUATION_CACHE_LANE_INVALID")
        try:
            normalized_fidelity = int(float(fidelity))
        except (TypeError, ValueError) as exc:
            raise EvaluationCacheError("EVALUATION_CACHE_FIDELITY_INVALID") from exc
        if float(fidelity) != float(normalized_fidelity) or normalized_fidelity < 1:
            raise EvaluationCacheError("EVALUATION_CACHE_FIDELITY_INVALID")
        normalized_configuration = _json_value(configuration)
        if not isinstance(normalized_configuration, Mapping):
            raise EvaluationCacheError("EVALUATION_CACHE_CONFIGURATION_INVALID")
        payload = {
            "schema_version": 1,
            "scientific_evaluator_sha256": str(scientific_evaluator_sha256),
            "train_snapshot_manifest_sha256": str(train_snapshot_manifest_sha256),
            "lane_id": str(lane_id),
            "configuration": normalized_configuration,
            "fidelity": normalized_fidelity,
        }
        return cls(
            scientific_evaluator_sha256=str(scientific_evaluator_sha256),
            train_snapshot_manifest_sha256=str(train_snapshot_manifest_sha256),
            lane_id=str(lane_id),
            configuration=normalized_configuration,
            fidelity=normalized_fidelity,
            sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        )


@dataclass(frozen=True)
class EvaluationCacheEntryV1:
    """One reusable result plus immutable physical-source provenance."""

    key: EvaluationCacheKeyV1
    result: Mapping[str, Any]
    result_sha256: str
    source_run_id: int
    source_wave: int
    source_island_id: str
    source_evaluation: int
    schema_version: int = 1

    @classmethod
    def build(
        cls,
        *,
        key: EvaluationCacheKeyV1,
        result: Mapping[str, Any],
        source_run_id: int,
        source_wave: int,
        source_island_id: str,
        source_evaluation: int,
    ) -> "EvaluationCacheEntryV1":
        if not isinstance(result, Mapping):
            raise EvaluationCacheError("EVALUATION_CACHE_RESULT_NOT_MAPPING")
        info = result.get("info")
        if not isinstance(info, Mapping):
            raise EvaluationCacheError("EVALUATION_CACHE_INFO_NOT_MAPPING")
        if info.get("validation_opened") is not False:
            raise EvaluationCacheError("EVALUATION_CACHE_OPENED_VALIDATION")
        if info.get("locked_opened") is not False:
            raise EvaluationCacheError("EVALUATION_CACHE_OPENED_LOCKED")
        if (
            int(source_run_id) < 1
            or int(source_wave) < 0
            or int(source_evaluation) < 1
            or not str(source_island_id)
        ):
            raise EvaluationCacheError("EVALUATION_CACHE_SOURCE_INVALID")
        normalized_result = _json_value(result)
        return cls(
            key=key,
            result=normalized_result,
            result_sha256=scientific_result_sha256(normalized_result),
            source_run_id=int(source_run_id),
            source_wave=int(source_wave),
            source_island_id=str(source_island_id),
            source_evaluation=int(source_evaluation),
        )


class EvaluationCacheRegistry:
    """Fail-closed in-memory registry used by one isolated DEHB island."""

    def __init__(self) -> None:
        self._entries: dict[str, EvaluationCacheEntryV1] = {}

    def add(self, entry: EvaluationCacheEntryV1) -> EvaluationCacheEntryV1:
        existing = self._entries.get(entry.key.sha256)
        if existing is not None and existing.result_sha256 != entry.result_sha256:
            raise EvaluationCacheConflictError(
                f"EVALUATION_CACHE_RESULT_CONFLICT:{entry.key.sha256}"
            )
        if existing is None:
            self._entries[entry.key.sha256] = entry
            return entry
        return existing

    def get(self, key_sha256: str) -> EvaluationCacheEntryV1 | None:
        return self._entries.get(str(key_sha256))

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> tuple[EvaluationCacheEntryV1, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))


__all__ = [
    "EvaluationCacheConflictError",
    "EvaluationCacheEntryV1",
    "EvaluationCacheError",
    "EvaluationCacheKeyV1",
    "EvaluationCacheRegistry",
    "audit_multiprocess_determinism",
    "normalize_scientific_result",
    "scientific_evaluator_binding_sha256",
    "scientific_result_sha256",
]
