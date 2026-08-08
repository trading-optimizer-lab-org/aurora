"""Deterministic candidate and provenance registries for autonomous batches."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

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


def get_previous_trial_count() -> int:
    value = os.environ.get("AURORA_AUTONOMOUS_PREVIOUS_TRIAL_COUNT", str(PREVIOUS_TRIAL_COUNT))
    if not value.isdigit() or int(value) < PREVIOUS_TRIAL_COUNT:
        raise ValueError("INVALID_PREVIOUS_TRIAL_COUNT")
    return int(value)


def _numeric_mutation(value: Any, rng: random.Random) -> Any:
    if isinstance(value, list) and value and all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in value
    ):
        scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
        mutated = [
            max(1, int(round(item * scale)))
            if isinstance(item, int)
            else round(float(item) * scale, 8)
            for item in value
        ]
        return mutated
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
        template_offset = index + batch_id * 7
        for attempt in range(max(100, len(templates) * 20)):
            template = templates[(template_offset + attempt) % len(templates)]
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
    previous_trial_count: int | None = None,
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
    previous_trial_count = previous_trial_count if previous_trial_count is not None else get_previous_trial_count()
    new_ledger_rows = [
        {
            "batch_id": batch_id,
            "canonical_hash": str(candidate["canonical_hash"]),
            "global_trial_index": previous_trial_count + index + 1,
            "pre_registered_before_performance": True,
            "status": "registered",
            "strategy_id": str(candidate["strategy_id"]),
        }
        for index, candidate in enumerate(candidates)
    ]
    prior_ledger_value = os.environ.get("AURORA_PRIOR_TRIAL_LEDGER_PATH", "").strip()
    prior_ledger_path = Path(prior_ledger_value) if prior_ledger_value else None
    prior_ledger_rows = (
        read_jsonl(prior_ledger_path)
        if prior_ledger_path is not None and prior_ledger_path.is_file()
        else []
    )
    if previous_trial_count > PREVIOUS_TRIAL_COUNT and not prior_ledger_rows:
        raise ValueError("PRIOR_TRIAL_LEDGER_REQUIRED")
    if prior_ledger_rows:
        last_index = int(prior_ledger_rows[-1].get("global_trial_index", 0))
        if last_index != previous_trial_count:
            raise ValueError("PRIOR_TRIAL_LEDGER_COUNT_MISMATCH")
    ledger_rows = [*prior_ledger_rows, *new_ledger_rows]
    ledger_payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ledger_rows
    )
    (root / "trial_ledger.jsonl").write_text(ledger_payload, encoding="utf-8")
    pd.DataFrame(ledger_rows).to_parquet(root / "autonomous_trial_ledger.parquet", index=False)
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
        "trial_ledger_file": "trial_ledger.jsonl",
        "trial_ledger_rows": len(ledger_rows),
        "new_trial_ledger_rows": len(new_ledger_rows),
        "prior_trial_ledger_rows": len(prior_ledger_rows),
        "trial_ledger_sha256": hashlib.sha256(ledger_payload.encode("utf-8")).hexdigest(),
        "trial_indices": [row["global_trial_index"] for row in new_ledger_rows],
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
