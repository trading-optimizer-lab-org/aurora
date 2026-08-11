from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.artifact_recovery import (
    HttpRangeReader,
    inspect_zip_members,
    read_zip_members,
    validate_recovered_market_security_master,
)
from aurora.research.openap_181.recovered_yfinance_market import (
    RECOVERED_YFINANCE_SOURCE_RUN_ID,
    validate_recovered_yfinance_price_shard,
    validate_recovered_yfinance_source,
    validate_yfinance_source_manifest,
)
from aurora.research.openap_181.recovered_current_features import (
    RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
    RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS,
    validate_recovered_current_feature_members,
)


API_ROOT = "https://api.github.com"
AUDITED_MARKET_RUN_ID = 31_388_342_037
AUDITED_ARTIFACT_NAME = "openap-yfinance-sec-current-score-results"
ARTIFACT_PATTERN = "openap-yfinance-*"
AUDITED_MEMBERS = (
    "security_master.parquet",
    "execution_summary.json",
    "output_manifest.csv",
    "source_manifest.csv",
    "yfinance_source_manifest.csv",
)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Aurora-OpenAP-Recovered-YFinance/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _read_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _artifact_download_url(repository: str, artifact_id: int, token: str) -> str:
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers=_headers(token),
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in {302, 303, 307} or not exc.headers.get("Location"):
            raise
        return str(exc.headers["Location"])
    raise RuntimeError("GitHub artifact endpoint did not return a download redirect")


def _range_fetcher(url: str, total_size: int):
    def fetch(start: int, end: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Aurora-OpenAP-Recovered-YFinance/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status != 206:
                raise RuntimeError(f"range request returned HTTP {response.status}")
            if response.headers.get("Content-Range") != (
                f"bytes {start}-{end}/{total_size}"
            ):
                raise RuntimeError("range response Content-Range mismatch")
            return response.read()

    return fetch


def _run_payloads(repository: str, run_id: int, token: str) -> tuple[Any, list[Any], list[Any]]:
    run_url = f"{API_ROOT}/repos/{repository}/actions/runs/{run_id}"
    run = _read_json(run_url, token)
    jobs = _read_json(f"{run_url}/jobs?per_page=100", token).get("jobs", [])
    artifacts = _read_json(f"{run_url}/artifacts?per_page=100", token).get(
        "artifacts", []
    )
    return run, jobs, artifacts


def _select_artifact(artifacts: list[Any], artifact_name: str) -> dict[str, Any]:
    matches = [artifact for artifact in artifacts if artifact.get("name") == artifact_name]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one source artifact {artifact_name}, found {len(matches)}"
        )
    return dict(matches[0])


def _reader(repository: str, artifact: dict[str, Any], token: str) -> HttpRangeReader:
    artifact_size = int(artifact.get("size_in_bytes", 0))
    if artifact_size <= 0:
        raise RuntimeError("artifact has an invalid compressed size")
    signed_url = _artifact_download_url(repository, int(artifact["id"]), token)
    return HttpRangeReader(
        artifact_size,
        _range_fetcher(signed_url, artifact_size),
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument(
        "--source-run-id",
        type=int,
        default=RECOVERED_YFINANCE_SOURCE_RUN_ID,
    )
    parser.add_argument(
        "--audited-market-run-id",
        type=int,
        default=AUDITED_MARKET_RUN_ID,
    )
    parser.add_argument(
        "--maximum-shard-compressed-bytes",
        type=int,
        default=32 * 1024 * 1024,
    )
    parser.add_argument(
        "--maximum-total-compressed-bytes",
        type=int,
        default=768 * 1024 * 1024,
    )
    parser.add_argument(
        "--maximum-derived-member-compressed-bytes",
        type=int,
        default=64 * 1024 * 1024,
    )
    parser.add_argument(
        "--maximum-derived-member-uncompressed-bytes",
        type=int,
        default=256 * 1024 * 1024,
    )
    parser.add_argument(
        "--maximum-derived-total-compressed-bytes",
        type=int,
        default=128 * 1024 * 1024,
    )
    parser.add_argument(
        "--maximum-derived-total-uncompressed-bytes",
        type=int,
        default=512 * 1024 * 1024,
    )
    parser.add_argument(
        "--sec-identity-evidence",
        type=Path,
        default=None,
        help="Optional official SEC identity manifest from a corroborating current batch",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP selective recovery of existing YFinance price artifacts"
    )
    if args.source_run_id != RECOVERED_YFINANCE_SOURCE_RUN_ID:
        raise ValueError("source run must match the pinned 48-shard acquisition")
    if args.audited_market_run_id != AUDITED_MARKET_RUN_ID:
        raise ValueError("audited market run must match the pinned merge evidence")
    if (
        args.maximum_shard_compressed_bytes <= 0
        or args.maximum_total_compressed_bytes <= 0
        or args.maximum_derived_member_compressed_bytes <= 0
        or args.maximum_derived_member_uncompressed_bytes <= 0
        or args.maximum_derived_total_compressed_bytes <= 0
        or args.maximum_derived_total_uncompressed_bytes <= 0
    ):
        raise ValueError("recovery byte limits must be positive")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for artifact recovery")

    audited_run, audited_jobs, audited_artifacts = _run_payloads(
        args.repository,
        args.audited_market_run_id,
        token,
    )
    audited_artifact = _select_artifact(audited_artifacts, AUDITED_ARTIFACT_NAME)
    audited_reader = _reader(args.repository, audited_artifact, token)
    audited_inspection = inspect_zip_members(audited_reader, AUDITED_MEMBERS)
    audited_declared_bytes = sum(
        int(row["compress_size"]) for row in audited_inspection.values()
    )
    if audited_declared_bytes > args.maximum_shard_compressed_bytes:
        raise RuntimeError("audited metadata recovery exceeds the per-artifact limit")
    audited_members = read_zip_members(audited_reader, AUDITED_MEMBERS)
    official_identity_evidence = None
    if args.sec_identity_evidence is not None:
        try:
            official_identity_evidence = json.loads(
                args.sec_identity_evidence.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("official SEC identity evidence is invalid JSON") from exc
        if not isinstance(official_identity_evidence, dict):
            raise RuntimeError("official SEC identity evidence must be a JSON object")

    audited_evidence = validate_recovered_market_security_master(
        audited_run,
        audited_jobs,
        audited_artifact,
        audited_members,
        official_identity_evidence=official_identity_evidence,
    )
    source_manifest = validate_yfinance_source_manifest(
        audited_members["yfinance_source_manifest.csv"]
    )
    derived_inspection = inspect_zip_members(
        audited_reader,
        RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS,
    )
    derived_compressed_bytes = sum(
        int(row["compress_size"]) for row in derived_inspection.values()
    )
    derived_uncompressed_bytes = sum(
        int(row["file_size"]) for row in derived_inspection.values()
    )
    if any(
        int(row["compress_size"])
        > args.maximum_derived_member_compressed_bytes
        for row in derived_inspection.values()
    ):
        raise RuntimeError("a derived member exceeds its compressed-byte limit")
    if any(
        int(row["file_size"])
        > args.maximum_derived_member_uncompressed_bytes
        for row in derived_inspection.values()
    ):
        raise RuntimeError("a derived member exceeds its uncompressed-byte limit")
    if derived_compressed_bytes > args.maximum_derived_total_compressed_bytes:
        raise RuntimeError("derived recovery exceeds its compressed-byte limit")
    if derived_uncompressed_bytes > args.maximum_derived_total_uncompressed_bytes:
        raise RuntimeError("derived recovery exceeds its uncompressed-byte limit")
    derived_members = read_zip_members(
        audited_reader,
        RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS,
    )
    current_feature_bundle = validate_recovered_current_feature_members(
        {**audited_members, **derived_members}
    )

    source_run, source_jobs, source_artifacts = _run_payloads(
        args.repository,
        args.source_run_id,
        token,
    )
    source_evidence = validate_recovered_yfinance_source(
        source_run,
        source_jobs,
        source_artifacts,
    )

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    shard_root = output / "restricted_internal_raw" / "price_shards"
    derived_root = output / "restricted_internal_derived"
    shard_root.mkdir(parents=True, exist_ok=True)
    derived_root.mkdir(parents=True, exist_ok=True)
    recovered_derived_rows: list[dict[str, Any]] = []
    for member_name in RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS:
        target = derived_root / member_name
        target.write_bytes(derived_members[member_name])
        recovered_derived_rows.append(
            {
                "member_name": member_name,
                "restricted_relative_path": target.relative_to(output).as_posix(),
                "materialized_bytes": target.stat().st_size,
                "materialized_sha256": _sha256_file(target),
                "declared_compressed_bytes": int(
                    derived_inspection[member_name]["compress_size"]
                ),
                "declared_uncompressed_bytes": int(
                    derived_inspection[member_name]["file_size"]
                ),
            }
        )
    recovered_rows: list[dict[str, Any]] = []
    total_declared_bytes = audited_declared_bytes + derived_compressed_bytes
    total_fetched_bytes = audited_reader.bytes_fetched
    total_range_requests = audited_reader.range_requests
    for artifact in source_evidence["artifacts"]:
        chunk_index = int(artifact["chunk_index"])
        member_name = f"prices_{chunk_index:03d}.parquet"
        artifact_reader = _reader(args.repository, artifact, token)
        inspection = inspect_zip_members(artifact_reader, (member_name,))
        declared_bytes = int(inspection[member_name]["compress_size"])
        if declared_bytes > args.maximum_shard_compressed_bytes:
            raise RuntimeError(
                f"price shard {chunk_index} exceeds the per-shard compressed-byte limit"
            )
        total_declared_bytes += declared_bytes
        if total_declared_bytes > args.maximum_total_compressed_bytes:
            raise RuntimeError("price recovery exceeds the total compressed-byte limit")
        payload = read_zip_members(artifact_reader, (member_name,))[member_name]
        manifest_row = source_manifest.loc[
            source_manifest["chunk_index"].eq(chunk_index)
        ].iloc[0]
        _frame, evidence = validate_recovered_yfinance_price_shard(
            artifact,
            payload,
            manifest_row,
        )
        target = shard_root / member_name
        target.write_bytes(payload)
        evidence.update(
            {
                "restricted_relative_path": target.relative_to(output).as_posix(),
                "materialized_sha256": _sha256_file(target),
                "declared_compressed_bytes": declared_bytes,
                "range_requests": artifact_reader.range_requests,
                "bytes_fetched": artifact_reader.bytes_fetched,
                "full_artifact_downloaded": False,
            }
        )
        recovered_rows.append(evidence)
        total_fetched_bytes += artifact_reader.bytes_fetched
        total_range_requests += artifact_reader.range_requests

    materialized_members = {
        "security_master.parquet": "security_master.parquet",
        "source_manifest.csv": "source_manifest.csv",
        "yfinance_source_manifest.csv": "yfinance_source_manifest.csv",
        "execution_summary.json": "source_execution_summary.json",
        "output_manifest.csv": "source_output_manifest.csv",
    }
    for member_name, target_name in materialized_members.items():
        (output / target_name).write_bytes(audited_members[member_name])
    recovery = {
        "contract_version": 1,
        **source_evidence,
        "source_run_url": (
            f"https://github.com/{args.repository}/actions/runs/{args.source_run_id}"
        ),
        "audited_market_run_id": args.audited_market_run_id,
        "audited_market_run_url": (
            "https://github.com/"
            f"{args.repository}/actions/runs/{args.audited_market_run_id}"
        ),
        "audited_market_evidence": audited_evidence,
        "audited_artifact_id": int(audited_artifact["id"]),
        "audited_artifact_size_bytes": int(audited_artifact["size_in_bytes"]),
        "audited_member_inspection": audited_inspection,
        "yfinance_source_manifest_sha256": sha256(
            audited_members["yfinance_source_manifest.csv"]
        ).hexdigest(),
        "security_master_sha256": sha256(
            audited_members["security_master.parquet"]
        ).hexdigest(),
        "source_manifest_sha256": sha256(
            audited_members["source_manifest.csv"]
        ).hexdigest(),
        "source_output_manifest_sha256": sha256(
            audited_members["output_manifest.csv"]
        ).hexdigest(),
        "recovered_current_feature_contract_version": (
            RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION
        ),
        "recovered_current_feature_evidence": dict(
            current_feature_bundle.evidence
        ),
        "recovered_current_feature_members": recovered_derived_rows,
        "recovered_current_feature_member_count": len(recovered_derived_rows),
        "recovered_current_feature_target_count": len(
            current_feature_bundle.evidence["target_signals"]
        ),
        "derived_member_inspection": derived_inspection,
        "derived_declared_compressed_bytes": derived_compressed_bytes,
        "derived_declared_uncompressed_bytes": derived_uncompressed_bytes,
        "maximum_derived_member_compressed_bytes": (
            args.maximum_derived_member_compressed_bytes
        ),
        "maximum_derived_member_uncompressed_bytes": (
            args.maximum_derived_member_uncompressed_bytes
        ),
        "maximum_derived_total_compressed_bytes": (
            args.maximum_derived_total_compressed_bytes
        ),
        "maximum_derived_total_uncompressed_bytes": (
            args.maximum_derived_total_uncompressed_bytes
        ),
        "recovered_price_shards": recovered_rows,
        "recovered_price_shard_count": len(recovered_rows),
        "price_rows": sum(int(row["price_rows"]) for row in recovered_rows),
        "maximum_shard_compressed_bytes": args.maximum_shard_compressed_bytes,
        "maximum_total_compressed_bytes": args.maximum_total_compressed_bytes,
        "declared_compressed_bytes": total_declared_bytes,
        "range_requests": total_range_requests,
        "bytes_fetched": total_fetched_bytes,
        "artifact_name_pattern": ARTIFACT_PATTERN,
        "full_artifacts_downloaded": False,
        "fresh_provider_request_made": False,
        "raw_market_data_internal_use_only": True,
        "raw_market_data_redistribution_allowed": False,
        "current_signal_computed": False,
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "recovered_at": datetime.now(UTC).isoformat(),
    }
    if len(recovered_rows) != 48:
        raise RuntimeError("recovery did not materialize exactly 48 price shards")
    if len(recovered_derived_rows) != len(RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS):
        raise RuntimeError("recovery did not materialize every current feature member")
    manifest_path = output / "recovered_yfinance_price_manifest.json"
    manifest_path.write_text(
        json.dumps(recovery, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(recovery, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
