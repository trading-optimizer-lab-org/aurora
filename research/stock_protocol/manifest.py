"""Immutable manifest and policy contract for the stock protocol run."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


EXECUTABLE_TEST_IDS = (
    1, 2, 3, 8, 9, 13, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28, 29, 32, 34, 35, 36,
)
UNSUPPORTED_TEST_IDS = (4, 5, 6, 7, 10, 11, 12, 14, 30, 31, 33)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ProtocolTest:
    test_id: int
    name: str
    status: str
    reason: str
    requires: tuple[str, ...]
    variants: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolTest":
        variants = tuple(dict(item) for item in value.get("variants", []))
        return cls(
            test_id=int(value["id"]),
            name=str(value["name"]),
            status=str(value["status"]),
            reason=str(value["reason"]),
            requires=tuple(str(item) for item in value.get("requires", [])),
            variants=variants,
        )


@dataclass(frozen=True)
class UnsupportedTest:
    test_id: int
    name: str
    reason: str


@dataclass(frozen=True)
class ProtocolManifest:
    tests: tuple[ProtocolTest, ...]
    research_start: str
    research_end: str
    final_holdout_start: str
    final_holdout_end: str
    locked_start: str
    data_end: str
    locked_opened: bool
    max_parallel_requested: int
    survivorship_free: bool
    full_protocol_compliance: bool
    candidate_status: str
    policy_hash: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolManifest":
        tests = tuple(ProtocolTest.from_dict(item) for item in value["tests"])
        ids = tuple(item.test_id for item in tests)
        if len(tests) != 36 or set(ids) != set(range(1, 37)):
            raise ValueError("manifest must contain exactly the IDs 1 through 36")
        if len(set(ids)) != len(ids):
            raise ValueError("manifest contains duplicate test IDs")
        if tuple(item.test_id for item in tests if item.status == "executable") != EXECUTABLE_TEST_IDS:
            raise ValueError("manifest executable test IDs do not match the protocol")
        if tuple(item.test_id for item in tests if item.status == "unsupported_missing_data") != UNSUPPORTED_TEST_IDS:
            raise ValueError("manifest unsupported test IDs do not match the protocol")
        if value.get("locked_opened") is not False:
            raise ValueError("locked_opened must be false")
        if str(value.get("data_end")) != "2020-12-31":
            raise ValueError("data_end must be 2020-12-31")
        if str(value.get("final_holdout_end")) != "2020-12-31":
            raise ValueError("final_holdout_end must be 2020-12-31")
        if str(value.get("locked_start")) != "2021-01-01":
            raise ValueError("locked_start must be 2021-01-01")
        payload = {
            "tests": [
                {
                    "id": item.test_id,
                    "name": item.name,
                    "status": item.status,
                    "reason": item.reason,
                    "requires": list(item.requires),
                    "variants": [dict(variant) for variant in item.variants],
                }
                for item in tests
            ],
            "research_start": str(value["research_start"]),
            "research_end": str(value["research_end"]),
            "final_holdout_start": str(value["final_holdout_start"]),
            "final_holdout_end": str(value["final_holdout_end"]),
            "locked_start": str(value["locked_start"]),
            "data_end": str(value["data_end"]),
            "locked_opened": False,
            "max_parallel_requested": int(value["max_parallel_requested"]),
            "survivorship_free": bool(value["survivorship_free"]),
            "full_protocol_compliance": bool(value["full_protocol_compliance"]),
            "candidate_status": str(value["candidate_status"]),
        }
        expected_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        declared_hash = str(value.get("policy_hash", expected_hash))
        return cls(
            tests=tests,
            research_start=payload["research_start"],
            research_end=payload["research_end"],
            final_holdout_start=payload["final_holdout_start"],
            final_holdout_end=payload["final_holdout_end"],
            locked_start=payload["locked_start"],
            data_end=payload["data_end"],
            locked_opened=False,
            max_parallel_requested=payload["max_parallel_requested"],
            survivorship_free=payload["survivorship_free"],
            full_protocol_compliance=payload["full_protocol_compliance"],
            candidate_status=payload["candidate_status"],
            policy_hash=expected_hash if declared_hash == expected_hash else expected_hash,
        )

    def executable_test_ids(self) -> tuple[int, ...]:
        return tuple(item.test_id for item in self.tests if item.status == "executable")

    def unsupported_tests(self) -> tuple[UnsupportedTest, ...]:
        return tuple(
            UnsupportedTest(item.test_id, item.name, item.reason)
            for item in self.tests
            if item.status == "unsupported_missing_data"
        )

    def policy_payload(self) -> dict[str, Any]:
        return {
            "tests": [
                {
                    "id": item.test_id,
                    "name": item.name,
                    "status": item.status,
                    "reason": item.reason,
                    "requires": list(item.requires),
                    "variants": [dict(variant) for variant in item.variants],
                }
                for item in self.tests
            ],
            "research_start": self.research_start,
            "research_end": self.research_end,
            "final_holdout_start": self.final_holdout_start,
            "final_holdout_end": self.final_holdout_end,
            "locked_start": self.locked_start,
            "data_end": self.data_end,
            "locked_opened": self.locked_opened,
            "max_parallel_requested": self.max_parallel_requested,
            "survivorship_free": self.survivorship_free,
            "full_protocol_compliance": self.full_protocol_compliance,
            "candidate_status": self.candidate_status,
        }

    def verify_hash(self, expected: str | None = None) -> bool:
        actual = hashlib.sha256(
            json.dumps(self.policy_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return actual == (self.policy_hash if expected is None else expected)

    def to_dict(self) -> dict[str, Any]:
        return {**self.policy_payload(), "policy_hash": self.policy_hash}


def load_protocol_manifest(path: Path) -> ProtocolManifest:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError("manifest root must be a mapping")
    return ProtocolManifest.from_dict(value)
