"""Fail-closed package, novelty, and temporal contracts for SPY V2."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import yaml


EXPECTED_ZIP_SHA256 = (
    "8bea83aef0cae530e7da96ec0910fdef96f0e70430ffc19685b93d63e6917e5c"
)
EXPECTED_ZIP_BYTES = 1_691_467
EXPECTED_V1_RESEARCH_SHA256 = (
    "a8db7fd9ab2422d81601104234a80185e317b6cc2fae07914c5bca6c7e421925"
)
EXPECTED_V1_RESULTS_SHA256 = (
    "164ce2d50909c5224e5260fa185516e9ecee368d948201852f35a72fa0780775"
)
EXPECTED_CANDIDATES = 144
EXPECTED_FEATURES = 144
EXPECTED_FAMILIES = 24
EXPECTED_BENCHMARKS = 5
EXPECTED_TERMINAL_UNITS = 149
EXPECTED_V1_DECLARED = 168
EXPECTED_V1_EVALUATED = 65
EXPECTED_V1_REJECTED = 103
EXPECTED_CUMULATIVE_TRIALS = 312
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
VALIDATION_ACK = "OPEN_VALIDATION_2011_2020_ONCE_V2"

ROOT_TEXT_FILES = (
    "README_START_HERE.md",
    "acceptance_gates.md",
    "aurora_implementation_handoff.md",
    "bibliographic_verification_audit.csv",
    "campaign_spec.yaml",
    "candidate_pack_manifest.json",
    "candidate_strategy_pack.jsonl",
    "canonical_novelty_audit.csv",
    "CODEX_GITHUB_RUN_PROMPT.md",
    "codex_run_inputs_manifest.json",
    "contradictions_and_negative_results.md",
    "data_acquisition_plan.md",
    "data_source_inventory.csv",
    "executive_summary.md",
    "family_formula_contract.md",
    "feature_catalog.csv",
    "incremental_research_library.csv",
    "open_questions_and_risks.md",
    "package_build_receipt.json",
    "package_checksums.sha256",
    "package_validation_report.md",
    "prior_campaign_reference.json",
    "research_library.csv",
    "research_synthesis.md",
    "source_links.md",
    "strategy_family_ranking.csv",
    "train_selection_protocol.md",
)
PRIOR_FILES = (
    "prior_campaign/SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    "prior_campaign/sp500-ls-train-yahoo-fallback-r8-results.zip",
)
EXPECTED_PACKAGE_FILES = (*ROOT_TEXT_FILES, *PRIOR_FILES)


class PackageContractError(ValueError):
    """The frozen package is not the exact authorized input."""


class LockedBoundaryError(RuntimeError):
    """A forbidden date was observed without revealing its market value."""


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
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_NON_ECONOMIC_FIELDS = frozenset(
    {
        "strategy_id",
        "canonical_hash",
        "economic_signature",
        "canonicalization",
        "campaign_id",
        "cumulative_declared_trial_index",
        "priority_basis",
        "priority_score",
        "research_source_ids",
        "known_failure_modes",
        "overfitting_risk",
        "parameter_provenance",
        "prior_campaign_artifact_sha256",
        "prior_campaign_included_in_multiplicity",
    }
)


def economic_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields capable of changing positions or realized returns."""

    return {
        key: value
        for key, value in candidate.items()
        if key not in _NON_ECONOMIC_FIELDS
    }


def recomputed_economic_signature(candidate: Mapping[str, Any]) -> str:
    return canonical_json_hash(economic_identity(candidate))


def assert_before_locked(values: Iterable[Any], *, label: str) -> None:
    dates = pd.to_datetime(list(values), errors="coerce")
    if len(dates) and pd.DatetimeIndex(dates).max() >= LOCKED_START:
        raise LockedBoundaryError(f"TECHNICAL_FAILURE_LOCKED_BREACH:{label}")


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


def _read_csv(path: Path) -> tuple[Mapping[str, str], ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


@dataclass(frozen=True)
class CampaignPackage:
    root: Path
    zip_path: Path
    spec: Mapping[str, Any]
    manifest: Mapping[str, Any]
    prior_reference: Mapping[str, Any]
    candidates: tuple[Mapping[str, Any], ...]
    features: tuple[Mapping[str, str], ...]
    datasets: tuple[Mapping[str, str], ...]
    research: tuple[Mapping[str, str], ...]
    novelty: tuple[Mapping[str, str], ...]
    v1_candidate_hashes: frozenset[str]

    @classmethod
    def load_zip(cls, zip_path: Path) -> "CampaignPackage":
        """Load the exact frozen package bytes, independent of checkout line endings."""

        zip_path = Path(zip_path).resolve()
        if not zip_path.is_file() or zip_path.stat().st_size != EXPECTED_ZIP_BYTES:
            raise PackageContractError("ZIP_SIZE_MISMATCH")
        digest = sha256_file(zip_path)
        if digest != EXPECTED_ZIP_SHA256:
            raise PackageContractError("ZIP_SHA256_MISMATCH")
        root = Path(tempfile.gettempdir()) / f"aurora-sp500-v2-{digest[:16]}"
        expected = set(EXPECTED_PACKAGE_FILES)
        with zipfile.ZipFile(zip_path) as archive:
            actual = {name for name in archive.namelist() if not name.endswith("/")}
            if actual != expected:
                raise PackageContractError("ZIP_FILE_SET_MISMATCH")
            for relative in sorted(expected):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(relative))
        return cls.load(root, zip_path)

    @classmethod
    def load(cls, root: Path, zip_path: Path) -> "CampaignPackage":
        root = Path(root).resolve()
        zip_path = Path(zip_path).resolve()
        if not zip_path.is_file() or zip_path.stat().st_size != EXPECTED_ZIP_BYTES:
            raise PackageContractError("ZIP_SIZE_MISMATCH")
        if sha256_file(zip_path) != EXPECTED_ZIP_SHA256:
            raise PackageContractError("ZIP_SHA256_MISMATCH")
        cls._validate_expected_files(root)
        cls._validate_internal_checksums(root)
        cls._validate_nested_zip_crc(root)
        spec = yaml.safe_load((root / "campaign_spec.yaml").read_text("utf-8"))
        manifest = json.loads((root / "candidate_pack_manifest.json").read_text("utf-8"))
        prior_reference = json.loads(
            (root / "prior_campaign_reference.json").read_text("utf-8")
        )
        candidates = tuple(
            json.loads(line)
            for line in (root / "candidate_strategy_pack.jsonl")
            .read_text("utf-8")
            .splitlines()
            if line.strip()
        )
        package = cls(
            root=root,
            zip_path=zip_path,
            spec=spec,
            manifest=manifest,
            prior_reference=prior_reference,
            candidates=candidates,
            features=_read_csv(root / "feature_catalog.csv"),
            datasets=_read_csv(root / "data_source_inventory.csv"),
            research=_read_csv(root / "research_library.csv"),
            novelty=_read_csv(root / "canonical_novelty_audit.csv"),
            v1_candidate_hashes=cls._read_v1_candidate_hashes(root),
        )
        package.validate_semantics()
        return package

    @staticmethod
    def _validate_expected_files(root: Path) -> None:
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        }
        expected = set(EXPECTED_PACKAGE_FILES)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            raise PackageContractError(
                f"PACKAGE_FILE_SET_MISMATCH:missing={missing}:unexpected={unexpected}"
            )
        for name in ROOT_TEXT_FILES:
            (root / name).read_text("utf-8")

    @staticmethod
    def _validate_internal_checksums(root: Path) -> None:
        seen: set[str] = set()
        lines = (root / "package_checksums.sha256").read_text("utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            expected_digest, filename = line.split(maxsplit=1)
            filename = filename.lstrip("* ")
            if filename in seen:
                raise PackageContractError("DUPLICATE_CHECKSUM_ENTRY")
            seen.add(filename)
            path = root / filename
            if not path.is_file() or sha256_file(path) != expected_digest:
                raise PackageContractError(f"INTERNAL_CHECKSUM_MISMATCH:{filename}")
        expected = set(EXPECTED_PACKAGE_FILES) - {"package_checksums.sha256"}
        if seen != expected:
            raise PackageContractError("INTERNAL_CHECKSUM_COVERAGE_MISMATCH")

    @staticmethod
    def _validate_nested_zip_crc(root: Path) -> None:
        for relative in PRIOR_FILES:
            with zipfile.ZipFile(root / relative) as archive:
                bad = archive.testzip()
                if bad is not None:
                    raise PackageContractError(f"NESTED_ZIP_CRC_FAILURE:{relative}:{bad}")

    @staticmethod
    def _read_v1_candidate_hashes(root: Path) -> frozenset[str]:
        path = root / PRIOR_FILES[0]
        with zipfile.ZipFile(path) as archive:
            payload = archive.read("candidate_strategy_pack.jsonl").decode("utf-8")
        rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
        if len(rows) != EXPECTED_V1_DECLARED:
            raise PackageContractError("V1_CANDIDATE_COUNT_MISMATCH")
        return frozenset(str(row["canonical_hash"]) for row in rows)

    def validate_semantics(self) -> None:
        if len(self.candidates) != EXPECTED_CANDIDATES:
            raise PackageContractError("CANDIDATE_COUNT_MISMATCH")
        if len(self.features) != EXPECTED_FEATURES:
            raise PackageContractError("FEATURE_COUNT_MISMATCH")
        if len(self.spec.get("benchmarks", ())) != EXPECTED_BENCHMARKS:
            raise PackageContractError("BENCHMARK_COUNT_MISMATCH")
        if int(self.manifest["cumulative_declared_trials"]["total"]) != 312:
            raise PackageContractError("CUMULATIVE_TRIAL_COUNT_MISMATCH")

        prior_research = self.root / PRIOR_FILES[0]
        prior_results = self.root / PRIOR_FILES[1]
        if sha256_file(prior_research) != EXPECTED_V1_RESEARCH_SHA256:
            raise PackageContractError("V1_RESEARCH_SHA256_MISMATCH")
        if sha256_file(prior_results) != EXPECTED_V1_RESULTS_SHA256:
            raise PackageContractError("V1_RESULTS_SHA256_MISMATCH")

        feature_ids = {row["feature_id"] for row in self.features}
        dataset_ids = {row["dataset_id"] for row in self.datasets}
        source_ids = {row["source_id"] for row in self.research}
        novelty_by_id = {row["strategy_id"]: row for row in self.novelty}
        strategy_ids: set[str] = set()
        declared_hashes: set[str] = set()
        recomputed_hashes: set[str] = set()
        family_counts: dict[str, int] = {}
        track_counts: dict[str, int] = {}
        for index, candidate in enumerate(self.candidates, start=1):
            strategy_id = str(candidate["strategy_id"])
            if strategy_id != f"V2STRAT{index:04d}":
                raise PackageContractError(f"STRATEGY_ID_SEQUENCE_MISMATCH:{strategy_id}")
            if strategy_id in strategy_ids:
                raise PackageContractError("DUPLICATE_STRATEGY_ID")
            strategy_ids.add(strategy_id)

            declared_hash = str(candidate["canonical_hash"])
            if declared_hash != str(candidate["economic_signature"]):
                raise PackageContractError(f"DECLARED_SIGNATURE_MISMATCH:{strategy_id}")
            novelty = novelty_by_id.get(strategy_id)
            if novelty is None or novelty["v2_economic_signature"] != declared_hash:
                raise PackageContractError(f"NOVELTY_SIGNATURE_MISMATCH:{strategy_id}")
            if novelty["exact_collision_with_v1"].strip().lower() not in {"false", "0", "no"}:
                raise PackageContractError(f"DECLARED_V1_COLLISION:{strategy_id}")
            if declared_hash in self.v1_candidate_hashes:
                raise PackageContractError(f"EXACT_V1_HASH_COLLISION:{strategy_id}")
            declared_hashes.add(declared_hash)
            recomputed_hashes.add(recomputed_economic_signature(candidate))

            family = str(candidate["family"])
            family_counts[family] = family_counts.get(family, 0) + 1
            track = str(candidate["evidence_track"])
            track_counts[track] = track_counts.get(track, 0) + 1
            if list(candidate.get("position_values", ())) != [-1, 1]:
                raise PackageContractError(f"INVALID_POSITION_CONTRACT:{strategy_id}")
            if float(candidate.get("absolute_exposure", 0)) != 1.0:
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
            if candidate.get("locked_opened") is not False:
                raise PackageContractError(f"LOCKED_CONTRACT_MISMATCH:{strategy_id}")
            if candidate.get("validation_used_for_design") is not False:
                raise PackageContractError(f"VALIDATION_DESIGN_BREACH:{strategy_id}")
            if int(candidate["cumulative_declared_trial_count"]) != 312:
                raise PackageContractError(f"TRIAL_COUNT_MISMATCH:{strategy_id}")
            if not set(candidate["features"]).issubset(feature_ids):
                raise PackageContractError(f"UNKNOWN_FEATURE:{strategy_id}")
            if not set(candidate["required_datasets"]).issubset(dataset_ids):
                raise PackageContractError(f"UNKNOWN_DATASET:{strategy_id}")
            if not set(candidate["research_source_ids"]).issubset(source_ids):
                raise PackageContractError(f"UNKNOWN_SOURCE:{strategy_id}")

        if len(family_counts) != EXPECTED_FAMILIES or set(family_counts.values()) != {6}:
            raise PackageContractError("FAMILY_24_X_6_MISMATCH")
        if len(declared_hashes) != EXPECTED_CANDIDATES:
            raise PackageContractError("DUPLICATE_DECLARED_ECONOMIC_SIGNATURE")
        if len(recomputed_hashes) != EXPECTED_CANDIDATES:
            raise PackageContractError("DUPLICATE_RECOMPUTED_ECONOMIC_SIGNATURE")
        if track_counts != {"pre_2011_evidence": 132, "post_2010_research": 12}:
            raise PackageContractError("EVIDENCE_TRACK_COUNT_MISMATCH")

        boundaries = self.spec["boundaries"]
        expected_boundaries = {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_opened": False,
        }
        if boundaries != expected_boundaries:
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


def validate_exact_coverage(
    expected: Sequence[str],
    completed: Sequence[str],
    rejected: Sequence[str],
) -> None:
    terminal = list(completed) + list(rejected)
    if len(terminal) != len(set(terminal)):
        raise PackageContractError("DUPLICATE_TERMINAL_UNIT")
    if set(terminal) != set(expected):
        raise PackageContractError("INCOMPLETE_TERMINAL_COVERAGE")
