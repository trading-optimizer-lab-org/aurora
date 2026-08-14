"""Immutable identities and result envelopes for continuous SP500 DEHB."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping

from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    _canonical_bytes,
    _json_value,
    normalize_scientific_result,
    scientific_result_sha256,
)


_LANE_PATTERN = re.compile(r"F(?:00[1-9]|0[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)")
_EVALUATION_DOMAIN = b"SP500-DEHB-EVALUATION-V2\0"
_STRATEGY_DOMAIN = b"SP500-DEHB-STRATEGY-V1\0"


class ContinuousModelError(ValueError):
    """Raised when a continuous-campaign identity or result is invalid."""


def _require_sha256(value: object, message: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ContinuousModelError(message)
    return text


def _require_positive_integer(value: object, message: str) -> int:
    try:
        integer = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ContinuousModelError(message) from exc
    if float(value) != float(integer) or integer < 1:
        raise ContinuousModelError(message)
    return integer


@dataclass(frozen=True)
class EvaluationCacheKeyV2:
    """Complete scientific identity for one proposal evaluation."""

    sha256: str
    payload: Mapping[str, Any]
    schema_version: int = 2

    @classmethod
    def build(
        cls,
        *,
        evaluator_sha256: str,
        numeric_profile_sha256: str,
        train_manifest_sha256: str,
        train_spy_sha256: str,
        campaign_contract_sha256: str,
        lane_id: str,
        configuration: Mapping[str, Any],
        fidelity: int | float,
        fidelity_recipe_sha256: str,
        robustness_identity: str,
        execution_contract_version: int = 2,
        return_interval_contract_version: int = 1,
    ) -> "EvaluationCacheKeyV2":
        lane = str(lane_id)
        if _LANE_PATTERN.fullmatch(lane) is None:
            raise ContinuousModelError("CONTINUOUS_KEY_LANE_INVALID")
        normalized_configuration = _json_value(configuration)
        if not isinstance(normalized_configuration, Mapping):
            raise ContinuousModelError("CONTINUOUS_KEY_CONFIGURATION_INVALID")
        robustness = str(robustness_identity)
        if not robustness:
            raise ContinuousModelError("CONTINUOUS_KEY_ROBUSTNESS_IDENTITY_INVALID")
        payload = {
            "schema_version": 2,
            "evaluator_sha256": _require_sha256(
                evaluator_sha256, "CONTINUOUS_KEY_EVALUATOR_SHA256_INVALID"
            ),
            "numeric_profile_sha256": _require_sha256(
                numeric_profile_sha256, "CONTINUOUS_KEY_NUMERIC_SHA256_INVALID"
            ),
            "train_manifest_sha256": _require_sha256(
                train_manifest_sha256, "CONTINUOUS_KEY_TRAIN_SHA256_INVALID"
            ),
            "train_spy_sha256": _require_sha256(
                train_spy_sha256, "CONTINUOUS_KEY_SPY_SHA256_INVALID"
            ),
            "campaign_contract_sha256": _require_sha256(
                campaign_contract_sha256, "CONTINUOUS_KEY_CAMPAIGN_SHA256_INVALID"
            ),
            "lane_id": lane,
            "configuration": normalized_configuration,
            "fidelity": _require_positive_integer(
                fidelity, "CONTINUOUS_KEY_FIDELITY_INVALID"
            ),
            "fidelity_recipe_sha256": _require_sha256(
                fidelity_recipe_sha256, "CONTINUOUS_KEY_FIDELITY_RECIPE_SHA256_INVALID"
            ),
            "robustness_identity": robustness,
            "execution_contract_version": _require_positive_integer(
                execution_contract_version,
                "CONTINUOUS_KEY_EXECUTION_CONTRACT_VERSION_INVALID",
            ),
            "return_interval_contract_version": _require_positive_integer(
                return_interval_contract_version,
                "CONTINUOUS_KEY_RETURN_INTERVAL_CONTRACT_VERSION_INVALID",
            ),
        }
        digest = hashlib.sha256(_EVALUATION_DOMAIN + _canonical_bytes(payload)).hexdigest()
        return cls(sha256=digest, payload=payload)


@dataclass(frozen=True)
class StrategyEvaluationKeyV1:
    """Identity for the expensive evaluation of an already generated position path."""

    sha256: str
    payload: Mapping[str, Any]
    schema_version: int = 1

    @classmethod
    def build(
        cls,
        *,
        evaluation_key: EvaluationCacheKeyV2,
        positions_sha256: str,
    ) -> "StrategyEvaluationKeyV1":
        source = evaluation_key.payload
        payload = {
            "schema_version": 1,
            "evaluator_sha256": source["evaluator_sha256"],
            "numeric_profile_sha256": source["numeric_profile_sha256"],
            "train_manifest_sha256": source["train_manifest_sha256"],
            "train_spy_sha256": source["train_spy_sha256"],
            "campaign_contract_sha256": source["campaign_contract_sha256"],
            "fidelity": source["fidelity"],
            "fidelity_recipe_sha256": source["fidelity_recipe_sha256"],
            "robustness_identity": source["robustness_identity"],
            "execution_contract_version": source["execution_contract_version"],
            "return_interval_contract_version": source[
                "return_interval_contract_version"
            ],
            "positions_sha256": _require_sha256(
                positions_sha256, "CONTINUOUS_STRATEGY_POSITIONS_SHA256_INVALID"
            ),
        }
        digest = hashlib.sha256(_STRATEGY_DOMAIN + _canonical_bytes(payload)).hexdigest()
        return cls(sha256=digest, payload=payload)


@dataclass(frozen=True)
class EvaluationResultV2:
    """Hash-bound train-only result accepted by the continuous registry."""

    key: EvaluationCacheKeyV2
    result: Mapping[str, Any]
    result_sha256: str
    schema_version: int = 2

    @classmethod
    def build(
        cls,
        *,
        key: EvaluationCacheKeyV2,
        result: Mapping[str, Any],
    ) -> "EvaluationResultV2":
        if not isinstance(result, Mapping):
            raise ContinuousModelError("CONTINUOUS_RESULT_NOT_MAPPING")
        info = result.get("info")
        if not isinstance(info, Mapping):
            raise ContinuousModelError("CONTINUOUS_RESULT_INFO_NOT_MAPPING")
        validation_opened = info.get("validation_opened")
        if validation_opened is True:
            raise ContinuousModelError("CONTINUOUS_RESULT_OPENED_VALIDATION")
        if validation_opened is not False:
            raise ContinuousModelError("CONTINUOUS_RESULT_VALIDATION_FLAG_INVALID")
        locked_opened = info.get("locked_opened")
        if locked_opened is True:
            raise ContinuousModelError("CONTINUOUS_RESULT_OPENED_LOCKED")
        if locked_opened is not False:
            raise ContinuousModelError("CONTINUOUS_RESULT_LOCKED_FLAG_INVALID")
        normalized = normalize_scientific_result(result)
        return cls(
            key=key,
            result=normalized,
            result_sha256=scientific_result_sha256(normalized),
        )


__all__ = [
    "ContinuousModelError",
    "EvaluationCacheKeyV2",
    "EvaluationResultV2",
    "StrategyEvaluationKeyV1",
]
