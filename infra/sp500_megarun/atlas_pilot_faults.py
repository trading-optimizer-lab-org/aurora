"""Small deterministic fault fixtures used by the Atlas pilot gate."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import hashlib
from typing import Any, TypeVar


T = TypeVar("T")


def run_fail_once_then_success(operation: Callable[[], T]) -> T:
    """Retry exactly once for the controlled pilot failure fixture."""

    try:
        return operation()
    except Exception:
        return operation()


def verify_artifact_hash(payload: bytes, expected_sha256: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("ATLAS_PILOT_ARTIFACT_HASH_INVALID")


def deduplicate_receipts(
    receipts: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    selected: dict[int, dict[str, Any]] = {}
    redundant = 0
    for value in receipts:
        receipt = dict(value)
        index = int(receipt.get("shard_index", -1))
        prior = selected.get(index)
        if prior is None:
            selected[index] = receipt
            continue
        if (
            prior.get("plan_sha256") != receipt.get("plan_sha256")
            or prior.get("result_sha256") != receipt.get("result_sha256")
        ):
            raise ValueError("ATLAS_PILOT_CONFLICTING_DUPLICATE")
        redundant += 1
    return list(selected.values()), redundant


@dataclass
class ControllerLedger:
    _successes: dict[str, str] = field(default_factory=dict)

    def record_success(self, segment_id: str, run_id: str) -> bool:
        if segment_id in self._successes:
            if self._successes[segment_id] != run_id:
                raise ValueError("ATLAS_PILOT_CONFLICTING_SEGMENT_SUCCESS")
            return False
        self._successes[segment_id] = run_id
        return True

    def successful_run(self, segment_id: str) -> str | None:
        return self._successes.get(segment_id)


__all__ = [
    "ControllerLedger",
    "deduplicate_receipts",
    "run_fail_once_then_success",
    "verify_artifact_hash",
]
