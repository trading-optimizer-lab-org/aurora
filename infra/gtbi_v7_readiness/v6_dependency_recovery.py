"""Truthful recovery classification for the preserved GTBI V6 dependency chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, domain_digest, raw_sha256
from .scientific_assets import seal_asset_manifest

READINESS_ROOT = Path(__file__).resolve().parents[2] / "docs/readiness/gtbi-v7"
PRIMARY_VERIFICATION_PATH = (
    READINESS_ROOT / "v6_data_pack_primary_verification.json"
)
MIRROR_VERIFICATION_PATH = (
    READINESS_ROOT / "v6_data_pack_mirror_verification.json"
)
RECOVERY_REPORT_PATH = READINESS_ROOT / "v6_dependency_recovery_report.json"

CALCULATION_COMMIT_SHA = "e8186189fe52e879471941acdadd94004a0662f6"
DATA_PACK_IDENTITY = (
    "e0552ac354766a4af28fcb77a867f63f9da646fb4b89c8c11c36cd6071275c5e"
)
STRATEGY_PACK_DIGEST = (
    "b50d167c56e7d15e0e839638c216a4d8a115235594423b18b18836e3894e6bd8"
)
DEPENDENCY_LOCK_SHA256 = (
    "e0ebac1931c2cb66686b8adbf9262d89c177ad1e75af822f83a323199fa763e6"
)
CAMPAIGN_FINGERPRINT = (
    "0dc802ff6b053296868373b24c9fad5504a5cb0cfd97e47f3e537460071bc5fd"
)
CAMPAIGN_MANIFEST_SHA256 = (
    "5850261bb3ec0d1d4c4fb67c585ab73757f4f336935426c1c2f95b0b15b30be8"
)
SOURCE_BUNDLE_SHA256 = (
    "sha256:"
    "c0c3a4a7f27339667500dcdc267499c15ac3185992f492614a7587f2f0556417"
)
RESULT_ARCHIVE_SHA256 = (
    "sha256:"
    "870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
)
FROZEN_LAKE_ARCHIVE_SHA256 = (
    "sha256:"
    "5a77dc20ffcc8769e0dabe38811d50664f6f3ab6d8ac262c17d39dc7b86070b5"
)
EXPECTED_FILE_RECORDS = {
    "benchmark.parquet": {
        "size_bytes": 324_364,
        "sha256": (
            "sha256:"
            "eec0c4d26038af392d089396dd1493a724550c46b9707ceb9a540a2d67b86c97"
        ),
    },
    "gtbi-v6-data-pack-source-manifest.json": {
        "size_bytes": 1_386,
        "sha256": (
            "sha256:"
            "f3422932bf9fa5e97aa5e6ed422cb06b9460ab70f9f4812a288889745351dfd2"
        ),
    },
    "prices.parquet": {
        "size_bytes": 500_169_939,
        "sha256": (
            "sha256:"
            "0e226f53adeed4117cb95c50b831e640a7831dbc860323fe88c8dd50316b4e0e"
        ),
    },
}
EXPECTED_CUSTODIES = {
    "primary": {
        "repository": "trading-optimizer-lab-org/aurora-v7-assets",
        "workflow_run_id": 30_547_783_619,
        "workflow_commit_sha": "69333c0e2d41ad41a1a95172e60fc234b44a3145",
        "release_id": 362_451_830,
    },
    "mirror": {
        "repository": "trading-optimizer-lab-org/aurora-v7-assets-mirror",
        "workflow_run_id": 30_547_783_869,
        "workflow_commit_sha": "d3c13f91e7828c3732536a5e1828c177ca121da1",
        "release_id": 362_451_828,
    },
}
CAMPAIGN_INPUTS = {
    "code_sha": CALCULATION_COMMIT_SHA,
    "data_run_identity": DATA_PACK_IDENTITY,
    "dependency_lock_identity": DEPENDENCY_LOCK_SHA256,
    "execution_mode": "optimized_evaluation_v5_event_first",
    "locked_start": "2021-01-01",
    "min_market_cap": 2_000_000_000,
    "strategy_pack_digest": STRATEGY_PACK_DIGEST,
    "train_end": "2010-12-31",
    "universe_identity": (
        "long-cash-next-session-open-min-market-cap-2000000000"
    ),
    "validation_end": "2020-12-31",
    "validation_start": "2011-01-01",
}


class V6DependencyRecoveryError(ValueError):
    """Raised when preserved V6 dependency evidence is contradictory."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V6DependencyRecoveryError(f"JSON object required: {path}")
    return dict(value)


def _receipt_digest(receipt: dict[str, Any]) -> str:
    payload = {
        key: value for key, value in receipt.items() if key != "receipt_digest"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(
        b"GTBI_V6_DATA_PACK_GITHUB_VERIFICATION_V1\0" + encoded
    ).hexdigest()


def validate_data_pack_verification(
    receipt: dict[str, Any],
    *,
    custody: str,
) -> None:
    """Validate one clean-runner receipt against the frozen V6 identities."""

    expected = EXPECTED_CUSTODIES[custody]
    exact = {
        "schema_version": "gtbi_v6_data_pack_github_verification_v1",
        "workflow_repository": expected["repository"],
        "workflow_run_id": expected["workflow_run_id"],
        "workflow_commit_sha": expected["workflow_commit_sha"],
        "release_id": expected["release_id"],
        "release_tag": "gtbi-v6-data-pack-run-29148013009",
        "aurora_calculation_commit_sha": CALCULATION_COMMIT_SHA,
        "expected_data_pack_identity": DATA_PACK_IDENTITY,
        "identity_verified": True,
        "temporal_boundary_verified": True,
        "github_only": True,
        "requires_local_machine": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "locked_data_opened": False,
    }
    for field, value in exact.items():
        if receipt.get(field) != value:
            raise V6DependencyRecoveryError(
                f"{custody} verification field mismatch: {field}"
            )
    if receipt.get("receipt_digest") != _receipt_digest(receipt):
        raise V6DependencyRecoveryError(
            f"{custody} verification receipt digest mismatch"
        )

    assets = {
        str(record["name"]): {
            "size_bytes": int(record["size_bytes"]),
            "sha256": str(record["sha256"]),
        }
        for record in receipt.get("source_assets", [])
    }
    if assets != EXPECTED_FILE_RECORDS:
        raise V6DependencyRecoveryError(
            f"{custody} source asset inventory mismatch"
        )

    manifest = receipt.get("data_pack_manifest")
    if not isinstance(manifest, dict):
        raise V6DependencyRecoveryError(
            f"{custody} data-pack manifest missing"
        )
    if manifest.get("data_pack_identity") != DATA_PACK_IDENTITY:
        raise V6DependencyRecoveryError(
            f"{custody} data-pack identity mismatch"
        )
    for field, value in CAMPAIGN_INPUTS.items():
        manifest_field = {
            "data_run_identity": "data_pack_identity",
            "code_sha": None,
            "dependency_lock_identity": None,
            "execution_mode": None,
            "min_market_cap": None,
            "strategy_pack_digest": None,
        }.get(field, field)
        if manifest_field and str(manifest.get(manifest_field)) != str(value):
            raise V6DependencyRecoveryError(
                f"{custody} data-pack campaign field mismatch: {field}"
            )
    if float(manifest.get("min_market_cap", -1)) != 2_000_000_000:
        raise V6DependencyRecoveryError(
            f"{custody} data-pack market-cap boundary mismatch"
        )
    bounds = manifest.get("date_bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise V6DependencyRecoveryError(
            f"{custody} data-pack date bounds missing"
        )
    if max(str(record["max"])[:10] for record in bounds) != "2020-12-31":
        raise V6DependencyRecoveryError(
            f"{custody} data-pack cutoff mismatch"
        )

    source = receipt.get("source_identity")
    if not isinstance(source, dict):
        raise V6DependencyRecoveryError(
            f"{custody} source identity missing"
        )
    source_exact = {
        "calculation_commit_sha": CALCULATION_COMMIT_SHA,
        "strategy_pack_path": (
            "scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1"
        ),
        "strategy_pack_file_count": 368,
        "strategy_pack_digest": STRATEGY_PACK_DIGEST,
        "dependency_lock_path": "requirements/gtbi-fast-strict.lock",
        "dependency_lock_sha256": DEPENDENCY_LOCK_SHA256,
    }
    if source != source_exact:
        raise V6DependencyRecoveryError(
            f"{custody} source identity mismatch"
        )


def _layer(
    layer: str,
    *,
    found: bool,
    candidate_copy: str,
    copy_sha256: str,
    authenticated: bool,
    reproducible: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "found": found,
        "missing": not found,
        "candidate_copy": candidate_copy,
        "copy_sha256": copy_sha256,
        "authenticated": authenticated,
        "reproducible": reproducible,
        "reason": reason,
    }


def build_dependency_recovery_report(
    *,
    primary: dict[str, Any] | None = None,
    mirror: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical, intentionally incomplete V6 recovery report."""

    primary = primary or _load_json(PRIMARY_VERIFICATION_PATH)
    mirror = mirror or _load_json(MIRROR_VERIFICATION_PATH)
    validate_data_pack_verification(primary, custody="primary")
    validate_data_pack_verification(mirror, custody="mirror")
    if primary["data_pack_manifest"] != mirror["data_pack_manifest"]:
        raise V6DependencyRecoveryError(
            "primary and mirror data-pack manifests differ"
        )
    if primary["source_identity"] != mirror["source_identity"]:
        raise V6DependencyRecoveryError(
            "primary and mirror source identities differ"
        )

    data_manifest_digest = raw_sha256(
        canonical_bytes(primary["data_pack_manifest"])
    )
    source_identity_digest = raw_sha256(
        canonical_bytes(primary["source_identity"])
    )
    layers = [
        _layer(
            "C",
            found=True,
            candidate_copy=(
                "gtbi-v6-fast-strict-run-29162930823.source.bundle"
            ),
            copy_sha256=SOURCE_BUNDLE_SHA256,
            authenticated=True,
            reproducible=True,
            reason=(
                "Exact calculation commit, source tree, workflow, dependency "
                "lock and restorable Git bundle are preserved twice."
            ),
        ),
        _layer(
            "D0",
            found=False,
            candidate_copy="gtbi-v7-frozen-data-lake-v1",
            copy_sha256=FROZEN_LAKE_ARCHIVE_SHA256,
            authenticated=False,
            reproducible=False,
            reason=(
                "The frozen lake has a current static universe but lacks the "
                "complete point-in-time listing, delisting and market-cap "
                "knowledge history required to authenticate original D0."
            ),
        ),
        _layer(
            "D1",
            found=False,
            candidate_copy="gtbi-v7-frozen-data-lake-v1",
            copy_sha256=FROZEN_LAKE_ARCHIVE_SHA256,
            authenticated=False,
            reproducible=False,
            reason=(
                "Raw provider files survive, but no trusted original V6 D1 "
                "manifest binds every raw byte to the historical campaign."
            ),
        ),
        _layer(
            "D2",
            found=False,
            candidate_copy="gtbi-v7-frozen-data-lake-v1",
            copy_sha256=FROZEN_LAKE_ARCHIVE_SHA256,
            authenticated=False,
            reproducible=False,
            reason=(
                "Normalized files survive, but the complete original schema, "
                "adjustment, currency and calendar lineage is not authenticated."
            ),
        ),
        _layer(
            "D3",
            found=True,
            candidate_copy="gtbi-v6-data-pack-run-29148013009",
            copy_sha256="sha256:" + DATA_PACK_IDENTITY,
            authenticated=True,
            reproducible=True,
            reason=(
                "Two clean GitHub runners rebuilt the original manifest from "
                "byte-identical preserved Parquet files and matched e055."
            ),
        ),
        _layer(
            "S",
            found=True,
            candidate_copy=(
                "scripts/strategy_packs/"
                "gtbi_long_hold_fundamental_timing_v1@e8186189"
            ),
            copy_sha256="sha256:" + STRATEGY_PACK_DIGEST,
            authenticated=True,
            reproducible=True,
            reason=(
                "All 368 pack files are in the preserved source bundle and "
                "their V6 canonical pack digest matches the campaign."
            ),
        ),
        _layer(
            "R",
            found=True,
            candidate_copy=(
                "global-technical-buy-indicator-long-hold-fast-strict-v6-"
                "results.zip"
            ),
            copy_sha256=RESULT_ARCHIVE_SHA256,
            authenticated=True,
            reproducible=True,
            reason=(
                "The complete 47-member result archive is preserved twice and "
                "restored byte-for-byte on clean GitHub runners."
            ),
        ),
    ]
    missing_layers = [row["layer"] for row in layers if row["missing"]]
    report: dict[str, Any] = {
        "schema_version": "gtbi_v6_dependency_recovery_report_v1",
        "recorded_at_utc": "2026-07-30T13:38:29Z",
        "source_result_run_id": 29_162_930_823,
        "source_result_archive_sha256": RESULT_ARCHIVE_SHA256,
        "source_result_campaign_manifest_path": (
            "canonical_results/campaign_manifest.json"
        ),
        "source_result_campaign_manifest_sha256": (
            "sha256:" + CAMPAIGN_MANIFEST_SHA256
        ),
        "campaign_fingerprint": CAMPAIGN_FINGERPRINT,
        "campaign_inputs": CAMPAIGN_INPUTS,
        "data_manifest_digest": data_manifest_digest,
        "source_identity_digest": source_identity_digest,
        "custodies": {
            "primary": {
                **EXPECTED_CUSTODIES["primary"],
                "receipt_digest": primary["receipt_digest"],
            },
            "mirror": {
                **EXPECTED_CUSTODIES["mirror"],
                "receipt_digest": mirror["receipt_digest"],
            },
        },
        "layers": layers,
        "missing_layers": missing_layers,
        "reproducibility_classification": (
            "result_preserved_inputs_incomplete"
        ),
        "full_v6_reproduction_claim_allowed": False,
        "reuse_recovered_v6_inputs": False,
        "github_only_verification": True,
        "requires_local_machine": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "locked_data_opened": False,
        "formal_task_effects": {
            "PREV7-0005": "evidence_ready",
            "PREV7-0306": "input_ready",
        },
        "report_digest": "",
    }
    report["report_digest"] = domain_digest(
        "GTBI_V6_DEPENDENCY_RECOVERY_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    return report


def apply_recovery_to_scientific_manifest(
    manifest: dict[str, Any],
    *,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply only claims proved by the recovery report and reseal."""

    report = report or build_dependency_recovery_report()
    updated = dict(manifest)
    updated.update(
        {
            "reference_engine_code_sha": CALCULATION_COMMIT_SHA,
            "reference_dependency_lock_digest": (
                "sha256:" + DEPENDENCY_LOCK_SHA256
            ),
            "data_digest": "sha256:" + DATA_PACK_IDENTITY,
            "data_manifest_digest": report["data_manifest_digest"],
            "historical_execution_pack_digest": (
                "sha256:" + DATA_PACK_IDENTITY
            ),
            "recovery_objective_policy_digest": report["report_digest"],
            "missing_v6_dependency_layers": report["missing_layers"],
            "reproducibility_classification": (
                "result_preserved_inputs_incomplete"
            ),
            "reuse_recovered_v6_inputs": False,
            "oracle_b_status": "unavailable_missing_original_inputs",
            "v6_historical_reproduction_confirmed": False,
            "first_date": "1962-01-02",
            "last_date": "2020-12-31",
            "historical_post_validation_contaminated": False,
            "pristine_locked": True,
        }
    )
    return seal_asset_manifest(updated)
