"""Deterministic candidate and provenance registries for autonomous batches."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable, Mapping

from aurora.infra.sp500_long_short_daily.contracts import CampaignPackage
from aurora.infra.sp500_long_short_daily.signals import IMPLEMENTED_FAMILIES

from .contracts import (
    LOCKED_START,
    PREVIOUS_TRIAL_COUNT,
    TRAIN_END,
    VALIDATION_END,
    VALIDATION_START,
    assert_contract,
    canonical_rule_hash,
)


def repo_root() -> Path:
    for candidate in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (candidate / "campaigns" / "sp500_long_short_daily" / "research_input").is_dir():
            return candidate.resolve()
    raise RuntimeError("AURORA_REPO_ROOT_NOT_FOUND")


def base_package() -> CampaignPackage:
    root = repo_root() / "campaigns" / "sp500_long_short_daily"
    return CampaignPackage.load(
        root / "research_input",
        root / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )


def _seed(batch_id: int) -> int:
    digest = hashlib.sha256(f"sp500-autonomous:{batch_id}".encode()).hexdigest()
    return int(digest[:16], 16)


def _numeric_mutation(value: Any, rng: random.Random) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if isinstance(value, int):
        scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
        return max(1, int(round(value * scale)))
    scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
    return round(float(value) * scale, 8)


def _mutate(template: Mapping[str, Any], batch_id: int, index: int, rng: random.Random) -> dict[str, Any]:
    candidate = json.loads(json.dumps(template))
    candidate.update(
        {
            "instrument": "SPY",
            "cash_allowed": False,
            "partial_exposure_allowed": False,
            "leverage_allowed": False,
            "volatility_scaling_allowed": False,
            "pyramiding_allowed": False,
            "multiple_assets_in_portfolio": False,
        }
    )
    candidate["strategy_id"] = f"AUTO-B{batch_id:04d}-{index:04d}"
    candidate["variant_label"] = f"autonomous_batch_{batch_id}_{index}"
    candidate["evidence_track"] = "pre_2011_evidence"
    candidate["selection_role"] = "autonomous_pre_registered_candidate"
    parameters = dict(candidate.get("parameters", {}))
    for key in sorted(parameters):
        if rng.random() < 0.85:
            parameters[key] = _numeric_mutation(parameters[key], rng)
    candidate["parameters"] = parameters
    candidate["priority_score"] = max(1, 100 - index)
    candidate["canonical_hash"] = canonical_rule_hash(candidate)
    assert_contract(candidate)
    return candidate


def generate_candidates(batch_id: int, *, count: int = 96) -> tuple[dict[str, Any], ...]:
    """Generate a reproducible, pre-registered batch from causal templates."""

    if batch_id < 0 or count < 1:
        raise ValueError("INVALID_BATCH_ARGUMENT")
    package = base_package()
    templates = [
        row for row in package.candidates
        if str(row.get("family")) in IMPLEMENTED_FAMILIES
        and set(row.get("required_datasets", ())).issubset({"DS001", "DS002"})
    ]
    if not templates:
        raise RuntimeError("NO_USABLE_CAUSAL_TEMPLATES")
    rng = random.Random(_seed(batch_id))
    candidates: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for index in range(count):
        template = templates[(index + batch_id * 7) % len(templates)]
        for attempt in range(100):
            candidate = _mutate(template, batch_id, index + attempt * count, rng)
            digest = str(candidate["canonical_hash"])
            if digest not in hashes:
                candidate["strategy_id"] = f"AUTO-B{batch_id:04d}-{index:04d}"
                candidate["canonical_hash"] = canonical_rule_hash(candidate)
                assert_contract(candidate)
                candidates.append(candidate)
                hashes.add(digest)
                break
        else:
            raise RuntimeError("CANDIDATE_HASH_COLLISION_LIMIT")
    return tuple(candidates)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_batch_registry(
    root: Path,
    *,
    batch_id: int,
    candidates: tuple[Mapping[str, Any], ...],
    previous_trial_count: int = PREVIOUS_TRIAL_COUNT,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_jsonl(root / "candidate_registry.jsonl", candidates)
    package = base_package()
    research_rows = list(package.research)
    feature_rows = list(package.features)
    dataset_rows = list(package.datasets)
    with (root / "research_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in research_rows for key in row}))
        writer.writeheader()
        writer.writerows(research_rows)
    with (root / "feature_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in feature_rows for key in row}))
        writer.writeheader()
        writer.writerows(feature_rows)
    with (root / "dataset_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in dataset_rows for key in row}))
        writer.writeheader()
        writer.writerows(dataset_rows)
    manifest = {
        "schema_version": "1",
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "previous_trial_count": previous_trial_count,
        "global_trial_count_after_batch": previous_trial_count + len(candidates),
        "pre_registered_before_performance": True,
        "canonical_hashes_unique": len({row["canonical_hash"] for row in candidates}) == len(candidates),
        "train_end": TRAIN_END,
        "validation_start": VALIDATION_START,
        "validation_end": VALIDATION_END,
        "locked_start": LOCKED_START,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (root / "candidate_registry_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_batch_registry(root: Path) -> tuple[dict[str, Any], ...]:
    rows = tuple(read_jsonl(Path(root) / "candidate_registry.jsonl"))
    if not rows:
        raise RuntimeError("EMPTY_CANDIDATE_REGISTRY")
    for row in rows:
        assert_contract(row)
    if len({row["strategy_id"] for row in rows}) != len(rows):
        raise RuntimeError("DUPLICATE_CANDIDATE_IDS")
    if len({row["canonical_hash"] for row in rows}) != len(rows):
        raise RuntimeError("DUPLICATE_CANDIDATE_HASHES")
    return rows
