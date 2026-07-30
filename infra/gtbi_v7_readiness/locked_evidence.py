"""Fail-closed public contract for preserved GTBI locked evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical import domain_digest

READINESS_ROOT = Path(__file__).resolve().parents[2] / "docs/readiness/gtbi-v7"
PRIMARY_VERIFICATION_PATH = (
    READINESS_ROOT / "locked_evidence_primary_verification.json"
)
MIRROR_VERIFICATION_PATH = (
    READINESS_ROOT / "locked_evidence_mirror_verification.json"
)
PRESERVATION_REPORT_PATH = (
    READINESS_ROOT / "locked_evidence_preservation_report.json"
)

ARCHIVE_NAME = "gtbi-v7-locked-evidence-v1.zip"
ARCHIVE_SHA256 = (
    "sha256:"
    "ef2ab6c86cf64fb299c32f0e2116ee4824b78873ebc4bbbc0e68c285a08b0692"
)
ARCHIVE_SIZE_BYTES = 12_759_399
PRIVATE_MANIFEST_SHA256 = (
    "sha256:"
    "3f2cca1dac4cac58602e7a4ede94cca15cc95b5f554a310b8d65b9fe8142af78"
)
PAYLOAD_FILE_COUNT = 343
PAYLOAD_BYTES = 29_347_076
REMOTE_ARTIFACT_COUNT = 15
LOCAL_SURVIVOR_ROOT_COUNT = 10

SOURCE_RUN_IDS = [
    27_615_096_617,
    27_621_450_798,
    27_621_713_161,
    27_902_014_212,
    27_902_069_984,
    27_902_085_161,
    27_902_873_467,
    27_903_102_264,
    27_904_216_358,
    28_521_769_739,
    28_523_867_574,
    28_525_003_185,
    28_531_253_383,
    28_534_550_861,
    28_535_785_007,
    28_539_779_128,
    29_197_104_777,
]
FAILED_RUNS_WITHOUT_ARTIFACT = [27_621_450_798, 27_902_873_467]

EXPECTED_CUSTODIES = {
    "primary": {
        "repository": "trading-optimizer-lab-org/aurora-v7-assets",
        "workflow_run_id": 30_550_156_880,
        "workflow_commit_sha": (
            "9cc6292bea452db16de89a2bbf0f8b9d83acfda2"
        ),
        "release_id": 362_474_510,
        "asset_node_id": "RA_kwDOTn_eds4dh6XD",
    },
    "mirror": {
        "repository": "trading-optimizer-lab-org/aurora-v7-assets-mirror",
        "workflow_run_id": 30_550_164_808,
        "workflow_commit_sha": (
            "ed35d539383d937858fb3b1ff4f7069fc7083160"
        ),
        "release_id": 362_474_511,
        "asset_node_id": "RA_kwDOToEVz84dh6XC",
    },
}


def _run(
    run_id: int,
    name: str,
    workflow_path: str,
    head_sha: str,
    event: str,
    conclusion: str,
    created_at: str,
    completed_at: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "name": name,
        "workflow_path": workflow_path,
        "head_sha": head_sha,
        "event": event,
        "status": "completed",
        "conclusion": conclusion,
        "created_at_utc": created_at,
        "completed_at_utc": completed_at,
        "first_observed_at_utc": created_at,
        "url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            f"actions/runs/{run_id}"
        ),
    }


RUN_RECORDS = [
    _run(
        27_615_096_617,
        "SP500 26 Paper Locked Strategy Report",
        ".github/workflows/sp500-26-paper-locked-strategy-report.yml",
        "a670b09fe60810aed5dda6c0961ac5f4afac5f4b",
        "workflow_dispatch",
        "success",
        "2026-06-16T11:44:17Z",
        "2026-06-16T11:52:46Z",
    ),
    _run(
        27_621_450_798,
        "SPY Weekly LongShort Locked Strategy Report",
        ".github/workflows/spy-weekly-longshort-locked-strategy-report.yml",
        "bb51a994f419efe1ac1dd26183ab2764684e4c91",
        "workflow_dispatch",
        "failure",
        "2026-06-16T13:35:04Z",
        "2026-06-16T13:37:49Z",
    ),
    _run(
        27_621_713_161,
        "SPY Weekly LongShort Locked Strategy Report",
        ".github/workflows/spy-weekly-longshort-locked-strategy-report.yml",
        "f16f5deffb16647eead6b641698a7b2c8381ff3f",
        "workflow_dispatch",
        "success",
        "2026-06-16T13:39:30Z",
        "2026-06-16T13:42:25Z",
    ),
    _run(
        27_902_014_212,
        "SPY Monthly TF21 MA10 Locked Table",
        ".github/workflows/spy-monthly-tf21-ma10-locked-table.yml",
        "3725ffd33f3170817d079289fd0e7c6b4674efe6",
        "workflow_dispatch",
        "success",
        "2026-06-21T10:52:44Z",
        "2026-06-21T10:53:33Z",
    ),
    _run(
        27_902_069_984,
        "SPY Monthly TF21 MA10 Locked Table",
        ".github/workflows/spy-monthly-tf21-ma10-locked-table.yml",
        "3725ffd33f3170817d079289fd0e7c6b4674efe6",
        "workflow_dispatch",
        "success",
        "2026-06-21T10:55:11Z",
        "2026-06-21T10:56:02Z",
    ),
    _run(
        27_902_085_161,
        "SPY Monthly TF21 MA10 Locked Table",
        ".github/workflows/spy-monthly-tf21-ma10-locked-table.yml",
        "3da2c095b99312293825bfa0db91b242618882a5",
        "workflow_dispatch",
        "success",
        "2026-06-21T10:55:52Z",
        "2026-06-21T10:56:50Z",
    ),
    _run(
        27_902_873_467,
        "SP500 26 Paper Locked Strategy Report",
        ".github/workflows/sp500-26-paper-locked-strategy-report.yml",
        "3da2c095b99312293825bfa0db91b242618882a5",
        "workflow_dispatch",
        "failure",
        "2026-06-21T11:29:13Z",
        "2026-06-21T11:37:52Z",
    ),
    _run(
        27_903_102_264,
        "SP500 26 Paper Locked Strategy Report",
        ".github/workflows/sp500-26-paper-locked-strategy-report.yml",
        "3da2c095b99312293825bfa0db91b242618882a5",
        "workflow_dispatch",
        "success",
        "2026-06-21T11:38:40Z",
        "2026-06-21T11:46:52Z",
    ),
    _run(
        27_904_216_358,
        "SP500 26 Paper Locked Strategy Report",
        ".github/workflows/sp500-26-paper-locked-strategy-report.yml",
        "3da2c095b99312293825bfa0db91b242618882a5",
        "workflow_dispatch",
        "success",
        "2026-06-21T12:23:50Z",
        "2026-06-21T12:30:22Z",
    ),
    _run(
        28_521_769_739,
        "Global Technical Buy Indicator External Pack 7200 Jobs",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-external-pack-360jobs.yml"
        ),
        "13f59f7caed920be4df73b5aa5516f51c7175183",
        "workflow_dispatch",
        "success",
        "2026-07-01T13:38:39Z",
        "2026-07-01T13:49:01Z",
    ),
    _run(
        28_523_867_574,
        "Global Technical Buy Indicator External Pack 7200 Jobs",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-external-pack-360jobs.yml"
        ),
        "13f59f7caed920be4df73b5aa5516f51c7175183",
        "workflow_dispatch",
        "success",
        "2026-07-01T14:11:17Z",
        "2026-07-01T14:22:42Z",
    ),
    _run(
        28_525_003_185,
        "Global Technical Buy Indicator V5 Event First Smoke",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-v5-smoke.yml"
        ),
        "f4b7b6d077c6d70b0db902fcc5d267b754b87642",
        "push",
        "success",
        "2026-07-01T14:29:02Z",
        "2026-07-01T14:46:22Z",
    ),
    _run(
        28_531_253_383,
        "Global Technical Buy Indicator V5 Event First Smoke",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-v5-smoke.yml"
        ),
        "27ad5e49661e2fd285f7b2e036266c5c254e596a",
        "push",
        "success",
        "2026-07-01T16:08:39Z",
        "2026-07-01T16:24:39Z",
    ),
    _run(
        28_534_550_861,
        "Global Technical Buy Indicator V5 Event First Smoke",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-v5-smoke.yml"
        ),
        "8a9b690e9412b555588846b0c1631566226fc596",
        "workflow_dispatch",
        "success",
        "2026-07-01T17:06:39Z",
        "2026-07-01T17:24:27Z",
    ),
    _run(
        28_535_785_007,
        "Global Technical Buy Indicator V5 Event First Smoke",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-v5-smoke.yml"
        ),
        "deda977d4de765cb7d743325850f105ae6e871a1",
        "workflow_dispatch",
        "success",
        "2026-07-01T17:28:47Z",
        "2026-07-01T17:46:44Z",
    ),
    _run(
        28_539_779_128,
        "Global Technical Buy Indicator V5 Event First Smoke",
        (
            ".github/workflows/"
            "global-technical-buy-indicator-v5-smoke.yml"
        ),
        "59afd2688bde71290a7f6311e31b0173d49026f0",
        "push",
        "success",
        "2026-07-01T18:40:56Z",
        "2026-07-01T18:58:33Z",
    ),
    _run(
        29_197_104_777,
        (
            "GTBI V6=false mode=clean_portfolio_v7_locked_only "
            "timeout=300 partition=0/0 recovery=false"
        ),
        (
            ".github/workflows/"
            "global-technical-buy-indicator-external-pack-360jobs.yml"
        ),
        "c4df224a2ff4f04e83963ab357c01e2d79048936",
        "workflow_dispatch",
        "success",
        "2026-07-12T14:53:03Z",
        "2026-07-12T15:03:26Z",
    ),
]


def _artifact(
    run_id: int,
    artifact_id: int,
    name: str,
    size_bytes: int,
    sha256: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "artifact_id": artifact_id,
        "name": name,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "created_at_utc": created_at,
        "first_observed_at_utc": created_at,
        "preserved_as_exact_zip": True,
    }


ARTIFACT_RECORDS = [
    _artifact(
        27_615_096_617,
        7_665_922_538,
        "sp500-26-paper-locked-strategy-report-rl_evt_tail_risk",
        3_200,
        (
            "sha256:"
            "cf091f8431bcfbebbef6f119f1f03a6d443c34c5480ee3f80feea6672c386382"
        ),
        "2026-06-16T11:52:44Z",
    ),
    _artifact(
        27_621_713_161,
        7_668_643_230,
        (
            "spy-weekly-longshort-locked-strategy-report-"
            "spy_weekly_longshort_sharpe2_s090_a5615dfb8ffc7479"
        ),
        16_710,
        (
            "sha256:"
            "80565775fa7d17e1d538ae0f71d7f7eeb3e88b2fc48963e45ebc65d0cc7908b4"
        ),
        "2026-06-16T13:42:18Z",
    ),
    _artifact(
        27_902_014_212,
        7_774_567_840,
        "spy-monthly-tf21-ma10-locked-table",
        2_575,
        (
            "sha256:"
            "0e79faa70d73f85f7e41cbc21e4a2e17fc591aaf516693c11b60b15beb3ff0c7"
        ),
        "2026-06-21T10:53:30Z",
    ),
    _artifact(
        27_902_069_984,
        7_774_583_980,
        "spy-monthly-tf21-ma10-locked-table",
        2_570,
        (
            "sha256:"
            "987cb2c27ab1af3fe034205af734b8cf6416241a97ad823e00e68c66196eea3d"
        ),
        "2026-06-21T10:55:59Z",
    ),
    _artifact(
        27_902_085_161,
        7_774_589_086,
        "spy-monthly-tf21-ma10-locked-table",
        2_572,
        (
            "sha256:"
            "597cc502162d7e94efaaa1b272dc3f03bd13827fb0610b839d5d28d476636dcb"
        ),
        "2026-06-21T10:56:47Z",
    ),
    _artifact(
        27_903_102_264,
        7_774_958_073,
        (
            "sp500-26-paper-locked-strategy-report-"
            "avoid_equity_bear_markets_trendycmacro"
        ),
        3_412,
        (
            "sha256:"
            "4ba7de102f78a312ffb12fdaa24b38343645401b553ce73323e58481460df90c"
        ),
        "2026-06-21T11:46:50Z",
    ),
    _artifact(
        27_904_216_358,
        7_775_282_535,
        "sp500-26-paper-locked-strategy-report-ep_short_rate_spread",
        3_766,
        (
            "sha256:"
            "0145c3bcd7213fe20fc7ac30d85140e3a07e28e961bca8a6da89d357df70f5c8"
        ),
        "2026-06-21T12:30:18Z",
    ),
    _artifact(
        28_521_769_739,
        8_012_006_308,
        "global-technical-buy-indicator-external-pack-72000-results",
        6_849,
        (
            "sha256:"
            "a948e622bae02968a1d8f1f3335db47b54810abbb8d063b97912fb5186e301ee"
        ),
        "2026-07-01T13:48:58Z",
    ),
    _artifact(
        28_523_867_574,
        8_012_947_836,
        "global-technical-buy-indicator-external-pack-72000-results",
        8_866,
        (
            "sha256:"
            "848ea001d10a2f52903defd4a9747d97da53578c76a0e4b47bf1fb257f9e3341"
        ),
        "2026-07-01T14:22:38Z",
    ),
    _artifact(
        28_525_003_185,
        8_013_603_151,
        "global-technical-buy-indicator-external-pack-72000-results",
        335_576,
        (
            "sha256:"
            "34891482af7a1a4752968323e070b3a7c9d46c0dbb7b0ef7cd24ee0226ae616a"
        ),
        "2026-07-01T14:46:13Z",
    ),
    _artifact(
        28_531_253_383,
        8_016_252_119,
        "global-technical-buy-indicator-external-pack-72000-results",
        322_427,
        (
            "sha256:"
            "d08c2152122359c9673d261fd1835800710b2bd6f29e1b536adba7e029fb434b"
        ),
        "2026-07-01T16:24:34Z",
    ),
    _artifact(
        28_534_550_861,
        8_017_679_234,
        "global-technical-buy-indicator-external-pack-72000-results",
        323_250,
        (
            "sha256:"
            "8bedc0ef8caeaa07e33ec528df0fde15db42fc255d82ca67b17fd18ca82097fd"
        ),
        "2026-07-01T17:24:25Z",
    ),
    _artifact(
        28_535_785_007,
        8_018_192_209,
        "global-technical-buy-indicator-external-pack-72000-results",
        1_659_825,
        (
            "sha256:"
            "819f3f03790be704d1512f6297627a1738c70de95c9615b64c21e9fceff5662e"
        ),
        "2026-07-01T17:46:41Z",
    ),
    _artifact(
        28_539_779_128,
        8_019_787_403,
        "global-technical-buy-indicator-external-pack-72000-results",
        1_676_248,
        (
            "sha256:"
            "631d9b97a2f93909854b860e74a85a83bb62239d98ea4c9c0019fde2381112d3"
        ),
        "2026-07-01T18:58:30Z",
    ),
    _artifact(
        29_197_104_777,
        8_261_387_370,
        "gtbi-clean-portfolio-v7-results",
        1_101_716,
        (
            "sha256:"
            "dba2c337184f88162c36d7f53e8db856fc8d2bd3aee0eceb608316250d7bfea2"
        ),
        "2026-07-12T15:03:21Z",
    ),
]


class LockedEvidenceError(ValueError):
    """Raised when locked-evidence preservation claims are contradictory."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LockedEvidenceError(f"JSON object required: {path}")
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
        b"GTBI_V7_LOCKED_EVIDENCE_GITHUB_VERIFICATION_V1\0" + encoded
    ).hexdigest()


def validate_locked_evidence_verification(
    receipt: dict[str, Any],
    *,
    custody: str,
) -> None:
    """Validate one clean-runner verification receipt exactly."""

    expected = EXPECTED_CUSTODIES[custody]
    exact = {
        "schema_version": (
            "gtbi_v7_locked_evidence_github_verification_v1"
        ),
        "workflow_repository": expected["repository"],
        "workflow_run_id": expected["workflow_run_id"],
        "workflow_commit_sha": expected["workflow_commit_sha"],
        "release_id": expected["release_id"],
        "release_tag": "gtbi-v7-locked-evidence-v1",
        "asset_node_id": expected["asset_node_id"],
        "asset_name": ARCHIVE_NAME,
        "archive_size_bytes": ARCHIVE_SIZE_BYTES,
        "archive_sha256": ARCHIVE_SHA256,
        "private_manifest_sha256": PRIVATE_MANIFEST_SHA256,
        "payload_file_count": PAYLOAD_FILE_COUNT,
        "payload_bytes": PAYLOAD_BYTES,
        "source_run_ids": SOURCE_RUN_IDS,
        "failed_runs_without_artifact": FAILED_RUNS_WITHOUT_ARTIFACT,
        "historical_post_validation_contaminated": True,
        "pristine_locked": False,
        "byte_identity_verified": True,
        "github_only_verification": True,
        "requires_local_machine": False,
        "locked_data_opened_during_verification": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
    }
    for field, value in exact.items():
        if receipt.get(field) != value:
            raise LockedEvidenceError(
                f"{custody} verification field mismatch: {field}"
            )
    if receipt.get("receipt_digest") != _receipt_digest(receipt):
        raise LockedEvidenceError(
            f"{custody} verification receipt digest mismatch"
        )


def build_locked_evidence_preservation_report(
    *,
    primary: dict[str, Any] | None = None,
    mirror: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the public, non-scientific locked-evidence preservation report."""

    primary = primary or _load_json(PRIMARY_VERIFICATION_PATH)
    mirror = mirror or _load_json(MIRROR_VERIFICATION_PATH)
    validate_locked_evidence_verification(primary, custody="primary")
    validate_locked_evidence_verification(mirror, custody="mirror")
    shared_fields = [
        "archive_sha256",
        "archive_size_bytes",
        "private_manifest_sha256",
        "payload_file_count",
        "payload_bytes",
        "source_run_ids",
        "failed_runs_without_artifact",
    ]
    for field in shared_fields:
        if primary[field] != mirror[field]:
            raise LockedEvidenceError(
                f"primary and mirror verification differ: {field}"
            )

    report: dict[str, Any] = {
        "schema_version": "gtbi_v7_locked_evidence_preservation_report_v1",
        "recorded_at_utc": "2026-07-30T14:07:40Z",
        "repository": "trading-optimizer-lab-org/aurora",
        "archive": {
            "name": ARCHIVE_NAME,
            "sha256": ARCHIVE_SHA256,
            "size_bytes": ARCHIVE_SIZE_BYTES,
            "private_manifest_sha256": PRIVATE_MANIFEST_SHA256,
            "payload_file_count": PAYLOAD_FILE_COUNT,
            "payload_bytes": PAYLOAD_BYTES,
            "remote_artifact_count": REMOTE_ARTIFACT_COUNT,
            "local_survivor_root_count": LOCAL_SURVIVOR_ROOT_COUNT,
        },
        "preserved_component_counts": {
            "run_manifests": 17,
            "job_access_records": 17,
            "artifact_manifests": 17,
            "access_log_archives": 17,
            "workflow_snapshots": 13,
            "result_artifact_zips": 15,
            "local_survivor_files": 247,
        },
        "coverage": {
            "run_manifests_preserved": True,
            "commit_shas_preserved": True,
            "workflow_bytes_preserved": True,
            "inputs_preserved": True,
            "inputs_preservation_method": (
                "exact_workflow_bytes_and_raw_run_logs; GitHub REST does not "
                "expose a structured workflow_dispatch input object"
            ),
            "access_logs_preserved": True,
            "result_summaries_preserved_as_opaque_bytes": True,
            "artifact_digests_preserved": True,
            "dates_first_observed_preserved": True,
        },
        "source_run_ids": SOURCE_RUN_IDS,
        "failed_runs_without_artifact": FAILED_RUNS_WITHOUT_ARTIFACT,
        "runs": RUN_RECORDS,
        "preserved_remote_artifacts": ARTIFACT_RECORDS,
        "custodies": {
            custody: {
                **EXPECTED_CUSTODIES[custody],
                "receipt_digest": receipt["receipt_digest"],
                "byte_identity_verified": True,
            }
            for custody, receipt in (
                ("primary", primary),
                ("mirror", mirror),
            )
        },
        "historical_post_validation_contaminated": True,
        "pristine_locked": False,
        "locked_data_opened_during_preservation": False,
        "locked_data_opened_during_verification": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "github_only_verification": True,
        "requires_local_machine": False,
        "local_paths_published": False,
        "formal_task_effects": {"PREV7-0004": "evidence_ready"},
        "formal_task_completion_claimed": False,
        "report_digest": "",
    }
    report["report_digest"] = domain_digest(
        "GTBI_V7_LOCKED_EVIDENCE_PRESERVATION_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    return report
