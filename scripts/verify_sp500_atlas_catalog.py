"""Fail-closed verifier for the prepared compact SP500_ATLAS_1 package."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_atlas_space import (
    AtlasSpaceV1,
    AtlasRangeV1,
    build_atlas_space,
    recipe_for_ordinal,
)
from aurora.infra.sp500_megarun.catalog_family_admission import FamilyAdmissionV1
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract
from aurora.infra.sp500_megarun.strategy_catalog import CatalogComponentV1
from aurora.infra.github_performance.contracts import canonical_sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_catalog(
    root: Path,
    *,
    data_contract_path: Path,
    feature_contract_path: Path,
) -> dict[str, object]:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("execution_authorized") is not False:
        raise ValueError("ATLAS_EXECUTION_NOT_LOCKED")
    if manifest.get("search_end") != "2010-12-31":
        raise ValueError("ATLAS_MANIFEST_SEARCH_END_INVALID")
    if manifest.get("validation_opened") is not False or manifest.get("locked_opened") is not False:
        raise ValueError("ATLAS_MANIFEST_BOUNDARY_OPEN")
    manifest_identity = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if canonical_sha256(manifest_identity) != manifest.get("manifest_sha256"):
        raise ValueError("ATLAS_MANIFEST_HASH_INVALID")
    for name, expected in manifest["artifacts_sha256"].items():
        if _sha256(root / name) != expected:
            raise ValueError(f"ATLAS_ARTIFACT_HASH_INVALID:{name}")

    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(
        Path(feature_contract_path), data_contract
    )
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_DATA_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_FEATURE_BOUNDARY_OPEN")
    if data_contract.sha256 != manifest["data_contract_sha256"]:
        raise ValueError("ATLAS_DATA_CONTRACT_HASH_MISMATCH")
    if feature_contract.sha256 != manifest["feature_contract_sha256"]:
        raise ValueError("ATLAS_FEATURE_CONTRACT_HASH_MISMATCH")

    family_payload = json.loads((root / "family_admission.json").read_text(encoding="utf-8"))
    family_identity = {key: value for key, value in family_payload.items() if key != "manifest_sha256"}
    if canonical_sha256(family_identity) != family_payload.get("manifest_sha256"):
        raise ValueError("ATLAS_FAMILY_MANIFEST_HASH_INVALID")
    families = [FamilyAdmissionV1.model_validate(row) for row in family_payload["families"]]
    if len(families) != 240 or any(row.status != "accepted" for row in families):
        raise ValueError("ATLAS_FAMILY_ADMISSION_INCOMPLETE")
    if any(row.available_through != "2010-12-31" for row in families):
        raise ValueError("ATLAS_FAMILY_BOUNDARY_INVALID")

    expected_space, expected_components = build_atlas_space(feature_contract)
    space_payload = json.loads((root / "recipe_space.json").read_text(encoding="utf-8"))
    space_identity = {key: value for key, value in space_payload.items() if key != "space_sha256"}
    if canonical_sha256(space_identity) != space_payload.get("space_sha256"):
        raise ValueError("ATLAS_SPACE_HASH_INVALID")
    if space_payload["canonical_recipe_count"] != expected_space.canonical_recipe_count:
        raise ValueError("ATLAS_SPACE_COUNT_INVALID")
    if space_payload["raw_requested_recipe_count"] != expected_space.raw_requested_recipe_count:
        raise ValueError("ATLAS_SPACE_RAW_COUNT_INVALID")
    if space_payload["validation_opened"] or space_payload["locked_opened"]:
        raise ValueError("ATLAS_SPACE_BOUNDARY_OPEN")

    counts: Counter[str] = Counter()
    component_count = 0
    with (root / "components.jsonl").open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            payload = json.loads(line)
            component = CatalogComponentV1.from_payload(payload)
            if component.lane_id not in expected_components:
                raise ValueError(f"ATLAS_COMPONENT_UNKNOWN_LANE:{line_number}")
            counts[component.lane_id] += 1
            component_count += 1
    if component_count != sum(expected_space.lane_component_counts.values()):
        raise ValueError("ATLAS_COMPONENT_COUNT_INVALID")
    if dict(counts) != dict(expected_space.lane_component_counts):
        raise ValueError("ATLAS_COMPONENT_LANE_COUNTS_INVALID")

    for ordinal in (0, expected_space.canonical_recipe_count - 1):
        recipe = recipe_for_ordinal(expected_space, expected_components, ordinal)
        if recipe["ordinal"] != ordinal or recipe["validation_opened"] or recipe["locked_opened"]:
            raise ValueError("ATLAS_RECIPE_SAMPLE_INVALID")
    return {
        "accepted": True,
        "catalog_id": manifest["catalog_id"],
        "component_count": component_count,
        "canonical_recipe_count": expected_space.canonical_recipe_count,
        "raw_requested_recipe_count": expected_space.raw_requested_recipe_count,
        "range_count": len(expected_space.ranges),
        "execution_authorized": False,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            verify_catalog(
                args.catalog_dir,
                data_contract_path=args.data_contract,
                feature_contract_path=args.feature_contract,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
