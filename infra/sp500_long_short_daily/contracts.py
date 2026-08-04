"""Strict package and temporal contracts for the SPY daily campaign."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import yaml


EXPECTED_ZIP_SHA256 = (
    "a8db7fd9ab2422d81601104234a80185e317b6cc2fae07914c5bca6c7e421925"
)
EXPECTED_CANDIDATES = 168
EXPECTED_FEATURES = 168
EXPECTED_FAMILIES = 28
EXPECTED_BENCHMARKS = 5
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
VALIDATION_ACK = "OPEN_VALIDATION_2011_2020_ONCE"

RESULT_FILES_IN_ORDER = (
    "README_START_HERE.md",
    "executive_summary.md",
    "research_synthesis.md",
    "contradictions_and_negative_results.md",
    "research_library.csv",
    "bibliographic_verification_audit.csv",
    "data_source_inventory.csv",
    "data_acquisition_plan.md",
    "feature_catalog.csv",
    "strategy_family_ranking.csv",
    "candidate_strategy_pack.jsonl",
    "candidate_pack_manifest.json",
    "train_selection_protocol.md",
    "campaign_spec.yaml",
    "acceptance_gates.md",
    "aurora_implementation_handoff.md",
    "open_questions_and_risks.md",
    "source_links.md",
    "codex_run_inputs_manifest.json",
    "package_validation_report.md",
    "package_checksums.sha256",
    "CODEX_GITHUB_RUN_PROMPT.md",
)


class PackageContractError(ValueError):
    """Raised when the frozen research package is not exact."""


class LockedBoundaryError(RuntimeError):
    """Raised without exposing the forbidden observation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def candidate_canonical_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if key != "canonical_hash"
    }


def assert_before_locked(values: Iterable[Any], *, label: str) -> None:
    dates = pd.to_datetime(list(values), errors="coerce")
    if len(dates) and pd.DatetimeIndex(dates).max() >= LOCKED_START:
        raise LockedBoundaryError(
            f"TECHNICAL_FAILURE_LOCKED_BREACH:{label}"
        )


def assert_frame_before_locked(frame: pd.DataFrame, *, label: str) -> None:
    candidates: list[Any] = []
    if isinstance(frame.index, pd.DatetimeIndex):
        candidates.extend(frame.index.tolist())
    for column in frame.columns:
        lowered = str(column).lower()
        if "date" in lowered or "time" in lowered or lowered in {
            "period",
            "available_at",
            "release_time",
        }:
            candidates.extend(frame[column].tolist())
    assert_before_locked(candidates, label=label)


@dataclass(frozen=True)
class CampaignPackage:
    root: Path
    zip_path: Path
    spec: Mapping[str, Any]
    candidates: tuple[Mapping[str, Any], ...]
    features: tuple[Mapping[str, str], ...]
    datasets: tuple[Mapping[str, str], ...]
    research: tuple[Mapping[str, str], ...]

    @classmethod
    def load(cls, root: Path, zip_path: Path) -> "CampaignPackage":
        root = Path(root).resolve()
        zip_path = Path(zip_path).resolve()
        if sha256_file(zip_path) != EXPECTED_ZIP_SHA256:
            raise PackageContractError("ZIP_SHA256_MISMATCH")
        cls._validate_expected_files(root)
        cls._validate_internal_checksums(root)
        spec = yaml.safe_load((root / "campaign_spec.yaml").read_text("utf-8"))
        candidates = tuple(
            json.loads(line)
            for line in (root / "candidate_strategy_pack.jsonl")
            .read_text("utf-8")
            .splitlines()
            if line.strip()
        )
        features = cls._read_csv(root / "feature_catalog.csv")
        datasets = cls._read_csv(root / "data_source_inventory.csv")
        research = cls._read_csv(root / "research_library.csv")
        package = cls(
            root=root,
            zip_path=zip_path,
            spec=spec,
            candidates=candidates,
            features=features,
            datasets=datasets,
            research=research,
        )
        package.validate_semantics()
        return package

    @staticmethod
    def _read_csv(path: Path) -> tuple[Mapping[str, str], ...]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))

    @staticmethod
    def _validate_expected_files(root: Path) -> None:
        actual = {path.name for path in root.iterdir() if path.is_file()}
        expected = set(RESULT_FILES_IN_ORDER)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            raise PackageContractError(
                f"PACKAGE_FILE_SET_MISMATCH:missing={missing}:unexpected={unexpected}"
            )
        for name in RESULT_FILES_IN_ORDER:
            (root / name).read_text("utf-8")

    @staticmethod
    def _validate_internal_checksums(root: Path) -> None:
        seen: set[str] = set()
        for line in (root / "package_checksums.sha256").read_text("utf-8").splitlines():
            if not line.strip():
                continue
            expected, filename = line.split(maxsplit=1)
            filename = filename.lstrip("* ")
            if filename in seen:
                raise PackageContractError("DUPLICATE_CHECKSUM_ENTRY")
            seen.add(filename)
            path = root / filename
            if not path.is_file() or sha256_file(path) != expected:
                raise PackageContractError(f"INTERNAL_CHECKSUM_MISMATCH:{filename}")
        expected = set(RESULT_FILES_IN_ORDER) - {"package_checksums.sha256"}
        if seen != expected:
            raise PackageContractError("INTERNAL_CHECKSUM_COVERAGE_MISMATCH")

    def validate_semantics(self) -> None:
        if len(self.candidates) != EXPECTED_CANDIDATES:
            raise PackageContractError("CANDIDATE_COUNT_MISMATCH")
        if len(self.features) != EXPECTED_FEATURES:
            raise PackageContractError("FEATURE_COUNT_MISMATCH")
        family_counts: dict[str, int] = {}
        strategy_ids: set[str] = set()
        candidate_hashes: set[str] = set()
        feature_ids = {row["feature_id"] for row in self.features}
        dataset_ids = {row["dataset_id"] for row in self.datasets}
        source_ids = {row["source_id"] for row in self.research}
        for candidate in self.candidates:
            strategy_id = str(candidate["strategy_id"])
            if strategy_id in strategy_ids:
                raise PackageContractError("DUPLICATE_STRATEGY_ID")
            strategy_ids.add(strategy_id)
            observed_hash = str(candidate["canonical_hash"])
            expected_hash = canonical_json_hash(candidate_canonical_payload(candidate))
            if observed_hash != expected_hash:
                raise PackageContractError(f"CANONICAL_HASH_MISMATCH:{strategy_id}")
            if observed_hash in candidate_hashes:
                raise PackageContractError("DUPLICATE_CANONICAL_HASH")
            candidate_hashes.add(observed_hash)
            family = str(candidate["family"])
            family_counts[family] = family_counts.get(family, 0) + 1
            if list(candidate.get("position_values", ())) != [-1, 1]:
                raise PackageContractError(f"INVALID_POSITION_CONTRACT:{strategy_id}")
            if float(candidate.get("absolute_exposure")) != 1.0:
                raise PackageContractError(f"INVALID_EXPOSURE:{strategy_id}")
            for cost in (
                "commission_bps",
                "slippage_bps",
                "borrow_cost_bps",
                "financing_bps",
                "switching_cost_bps",
                "market_impact_bps",
            ):
                if float(candidate.get(cost, 0)) != 0.0:
                    raise PackageContractError(f"NON_ZERO_COST:{strategy_id}:{cost}")
            if not set(candidate["features"]).issubset(feature_ids):
                raise PackageContractError(f"UNKNOWN_FEATURE:{strategy_id}")
            if not set(candidate["required_datasets"]).issubset(dataset_ids):
                raise PackageContractError(f"UNKNOWN_DATASET:{strategy_id}")
            if not set(candidate["research_source_ids"]).issubset(source_ids):
                raise PackageContractError(f"UNKNOWN_SOURCE:{strategy_id}")
            if candidate["locked_boundary"] != ">=2021-01-01 unopened":
                raise PackageContractError(f"LOCKED_CONTRACT_MISMATCH:{strategy_id}")
        if len(family_counts) != EXPECTED_FAMILIES:
            raise PackageContractError("FAMILY_COUNT_MISMATCH")
        if set(family_counts.values()) != {6}:
            raise PackageContractError("FAMILY_VARIANT_COUNT_MISMATCH")
        if len(self.spec.get("benchmarks", ())) != EXPECTED_BENCHMARKS:
            raise PackageContractError("BENCHMARK_COUNT_MISMATCH")
        boundaries = self.spec["boundaries"]
        if boundaries != {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_opened": False,
        }:
            raise PackageContractError("BOUNDARY_CONTRACT_MISMATCH")

    def candidate_by_id(self) -> dict[str, Mapping[str, Any]]:
        return {str(row["strategy_id"]): row for row in self.candidates}

    def required_dataset_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(dataset_id)
                    for candidate in self.candidates
                    for dataset_id in candidate["required_datasets"]
                }
            )
        )

    def validate_dataset_classes(self) -> None:
        classifications = {
            row["dataset_id"]: row["classification"] for row in self.datasets
        }
        forbidden = {"not_free", "rejected_bias", "rejected_unverifiable"}
        for candidate in self.candidates:
            bad = [
                dataset_id
                for dataset_id in candidate["required_datasets"]
                if classifications[dataset_id] in forbidden
            ]
            if bad:
                raise PackageContractError(
                    f"FORBIDDEN_DATASET_DEPENDENCY:{candidate['strategy_id']}:{bad}"
                )


def validate_exact_coverage(
    expected: Sequence[str],
    completed: Sequence[str],
    rejected: Sequence[str],
) -> None:
    expected_set = set(expected)
    terminal = list(completed) + list(rejected)
    if len(terminal) != len(set(terminal)):
        raise PackageContractError("DUPLICATE_TERMINAL_UNIT")
    if set(terminal) != expected_set:
        raise PackageContractError("INCOMPLETE_TERMINAL_COVERAGE")
