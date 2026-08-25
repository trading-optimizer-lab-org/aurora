"""Read-only weekly preservation for closed catalog artifacts.

The GitHub workflow that calls this module has read-only repository
permissions.  This module performs GET requests only, refuses incomplete or
changing inventories, verifies every selected object against a repository-
frozen contract, and emits bounded bytes for ``upload-artifact`` to publish.
It never computes scientific content and never mutates GitHub state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile


UTC = timezone.utc


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_FORBIDDEN_BOUNDARY_MARKERS = (
    "validation",
    "locked",
    "2021_",
    "2021-",
    "2022_",
    "2022-",
    "2023_",
    "2023-",
    "2024_",
    "2024-",
    "2025_",
    "2025-",
    "2026_",
    "2026-",
)


class KeeperError(RuntimeError):
    """Fail-closed maintenance error with a stable public reason code."""


class _ArtifactRedirectHandler(HTTPRedirectHandler):
    """Follow GitHub's signed artifact URL without leaking its API token."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            for header in tuple(redirected.headers):
                if header.casefold() in {
                    "authorization",
                    "x-github-api-version",
                    "accept",
                }:
                    redirected.headers.pop(header, None)
        return redirected


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KeeperError(f"KEEPER_DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise KeeperError(f"KEEPER_NONFINITE_JSON:{value}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except KeeperError:
        raise
    except Exception as exc:
        raise KeeperError(f"KEEPER_JSON_INVALID:{path.name}") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise KeeperError(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KeeperError(code)
    return value


def _parse_time(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise KeeperError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KeeperError(code) from exc
    if parsed.tzinfo is None:
        raise KeeperError(code)
    return parsed.astimezone(UTC)


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise KeeperError("KEEPER_PATH_INVALID")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise KeeperError("KEEPER_PATH_INVALID")
    if pure.as_posix() != value:
        raise KeeperError("KEEPER_PATH_NONCANONICAL")
    return value


def _validate_controls_receipt(
    payload: object,
    *,
    repository: str,
    protected_commit_sha: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise KeeperError("KEEPER_CONTROLS_RECEIPT_INVALID")
    receipt = dict(payload)
    claimed = _sha(receipt.get("receipt_sha256"), "KEEPER_CONTROLS_HASH_INVALID")
    hash_payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if _canonical_sha256(hash_payload) != claimed:
        raise KeeperError("KEEPER_CONTROLS_HASH_MISMATCH")
    if (
        receipt.get("schema_version") != "1"
        or receipt.get("status") != "ready"
        or receipt.get("repository") != repository
        or receipt.get("audit_use_context") != "keeper_maintenance"
        or receipt.get("observer_context") != "github_auditor"
        or receipt.get("observed_default_branch_sha") != protected_commit_sha
        or receipt.get("failed_controls") != []
    ):
        raise KeeperError("KEEPER_CONTROLS_NOT_READY")
    budgets = receipt.get("actions_zero_spend_budgets")
    if not isinstance(budgets, list) or len(budgets) != 3:
        raise KeeperError("KEEPER_ZERO_SPEND_BUDGETS_INVALID")
    for row in budgets:
        if (
            not isinstance(row, dict)
            or row.get("budget_amount") != 0
            or row.get("prevent_further_usage") is not True
        ):
            raise KeeperError("KEEPER_ZERO_SPEND_BUDGETS_INVALID")
    if (
        receipt.get("repository_cache_storage_limit_gb") != 10
        or not isinstance(receipt.get("enterprise_cache_retention_days"), int)
        or receipt.get("enterprise_cache_retention_days", 0) < 90
        or not isinstance(receipt.get("organization_cache_retention_days"), int)
        or receipt.get("organization_cache_retention_days", 0) < 90
        or not isinstance(receipt.get("repository_cache_retention_days"), int)
        or receipt.get("repository_cache_retention_days", 0) < 90
    ):
        raise KeeperError("KEEPER_CACHE_CONTROLS_INVALID")
    return receipt


class GitHubReadOnlyClient:
    """Small GET-only client with strict same-origin pagination."""

    def __init__(self, repository: str, token: str) -> None:
        if not _REPOSITORY.fullmatch(repository):
            raise KeeperError("KEEPER_REPOSITORY_INVALID")
        if not token:
            raise KeeperError("KEEPER_GITHUB_TOKEN_MISSING")
        self.repository = repository
        self._token = token
        self.api_root = "https://api.github.com"
        self.observed_at: datetime | None = None

    def _request(self, url: str) -> tuple[bytes, Any, str]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise KeeperError("KEEPER_API_ORIGIN_INVALID")
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "aurora-catalog-artifact-keeper-v1",
            },
        )
        with urlopen(request, timeout=60) as response:
            date_header = response.headers.get("Date")
            if date_header:
                observed = parsedate_to_datetime(date_header).astimezone(UTC)
                if self.observed_at is None or observed > self.observed_at:
                    self.observed_at = observed
            return response.read(), response.headers, response.geturl()

    def get_json(self, path_or_url: str) -> tuple[Any, Any]:
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else f"{self.api_root}{path_or_url}"
        )
        body, headers, final_url = self._request(url)
        if urlparse(final_url).netloc != "api.github.com":
            raise KeeperError("KEEPER_API_REDIRECT_INVALID")
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
        except Exception as exc:
            raise KeeperError("KEEPER_API_JSON_INVALID") from exc
        return payload, headers

    def paginated(self, path: str, item_key: str) -> tuple[dict[str, Any], ...]:
        separator = "&" if "?" in path else "?"
        next_url = f"{self.api_root}{path}{separator}per_page=100"
        seen_urls: set[str] = set()
        seen_ids: set[object] = set()
        rows: list[dict[str, Any]] = []
        while next_url:
            if next_url in seen_urls:
                raise KeeperError("KEEPER_PAGINATION_LOOP")
            seen_urls.add(next_url)
            parsed = urlparse(next_url)
            query = parse_qs(parsed.query)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "api.github.com"
                or query.get("per_page") != ["100"]
            ):
                raise KeeperError("KEEPER_PAGINATION_ORIGIN_OR_SIZE_INVALID")
            payload, headers = self.get_json(next_url)
            if not isinstance(payload, dict) or not isinstance(payload.get(item_key), list):
                raise KeeperError("KEEPER_PAGINATION_PAYLOAD_INVALID")
            for row in payload[item_key]:
                if not isinstance(row, dict) or row.get("id") in seen_ids:
                    raise KeeperError("KEEPER_PAGINATION_DUPLICATE_ID")
                seen_ids.add(row.get("id"))
                rows.append(dict(row))
            next_url = ""
            link = headers.get("Link", "")
            for part in str(link).split(","):
                if 'rel="next"' not in part:
                    continue
                candidate = part.split(";", 1)[0].strip()
                if not (candidate.startswith("<") and candidate.endswith(">")):
                    raise KeeperError("KEEPER_PAGINATION_LINK_INVALID")
                next_url = urljoin(self.api_root, candidate[1:-1])
                break
        return tuple(rows)

    def stable_paginated(
        self, path: str, item_key: str
    ) -> tuple[dict[str, Any], ...]:
        before = self.paginated(path, item_key)
        after = self.paginated(path, item_key)
        if _canonical_sha256(before) != _canonical_sha256(after):
            raise KeeperError("KEEPER_INVENTORY_UNSTABLE")
        return before

    def download_artifact(self, artifact_id: int, destination: Path, cap: int) -> str:
        url = (
            f"{self.api_root}/repos/{self.repository}/actions/artifacts/"
            f"{artifact_id}/zip"
        )
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "aurora-catalog-artifact-keeper-v1",
            },
        )
        digest = hashlib.sha256()
        written = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        opener = build_opener(_ArtifactRedirectHandler())
        with opener.open(request, timeout=120) as response, destination.open("xb") as stream:
            final = urlparse(response.geturl())
            if (
                final.scheme != "https"
                or not final.hostname
                or not (
                    final.hostname == "api.github.com"
                    or final.hostname.endswith(".blob.core.windows.net")
                    or final.hostname.endswith(".actions.githubusercontent.com")
                    or final.hostname.endswith(".githubusercontent.com")
                )
            ):
                raise KeeperError("KEEPER_ARTIFACT_REDIRECT_ORIGIN_INVALID")
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > cap:
                    raise KeeperError("KEEPER_DOWNLOAD_BYTE_CAP_EXCEEDED")
                digest.update(chunk)
                stream.write(chunk)
        return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path, uncompressed_cap: int) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if not members or len(members) > 4096:
            raise KeeperError("KEEPER_ARCHIVE_FILE_COUNT_INVALID")
        total = 0
        names: set[str] = set()
        for member in members:
            name = _safe_relative(member.filename.rstrip("/"))
            if name in names:
                raise KeeperError("KEEPER_ARCHIVE_DUPLICATE_PATH")
            names.add(name)
            total += member.file_size
            if total > uncompressed_cap:
                raise KeeperError("KEEPER_ARCHIVE_UNCOMPRESSED_CAP_EXCEEDED")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise KeeperError("KEEPER_ARCHIVE_SYMLINK_FORBIDDEN")
            target = (destination / PurePosixPath(name)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise KeeperError("KEEPER_ARCHIVE_PATH_ESCAPE")
        bundle.extractall(destination)


def _verify_runtime_input_manifest(root: Path, contract: dict[str, Any]) -> str:
    manifest_path = root / _safe_relative(contract.get("content_manifest_path"))
    if _file_sha256(manifest_path) != _sha(
        contract.get("content_manifest_sha256"),
        "KEEPER_SOURCE_MANIFEST_HASH_INVALID",
    ):
        raise KeeperError("KEEPER_SOURCE_MANIFEST_HASH_MISMATCH")
    manifest = _read_json(manifest_path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("validation_opened") is not False
        or manifest.get("locked_opened") is not False
        or not isinstance(manifest.get("files"), list)
    ):
        raise KeeperError("KEEPER_SOURCE_BOUNDARY_INVALID")
    rows: list[dict[str, Any]] = []
    expected_paths: set[str] = {manifest_path.relative_to(root).as_posix()}
    for raw in manifest["files"]:
        if not isinstance(raw, dict):
            raise KeeperError("KEEPER_SOURCE_FILE_LIST_INVALID")
        relative = _safe_relative(raw.get("path"))
        target = root / PurePosixPath(relative)
        if (
            relative in expected_paths
            or not target.is_file()
            or target.stat().st_size != raw.get("bytes")
            or _file_sha256(target) != _sha(raw.get("sha256"), "KEEPER_SOURCE_HASH_INVALID")
        ):
            raise KeeperError("KEEPER_SOURCE_CONTENT_MISMATCH")
        expected_paths.add(relative)
        rows.append({"path": relative, "bytes": raw["bytes"], "sha256": raw["sha256"]})
    observed_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if observed_paths != expected_paths:
        raise KeeperError("KEEPER_SOURCE_FILE_LIST_MISMATCH")
    aggregate = hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        aggregate != manifest.get("aggregate_sha256")
        or aggregate
        != _sha(
            contract.get("content_aggregate_sha256"),
            "KEEPER_SOURCE_AGGREGATE_INVALID",
        )
    ):
        raise KeeperError("KEEPER_SOURCE_AGGREGATE_MISMATCH")
    return aggregate


def _verify_closed_file_list(root: Path, contract: dict[str, Any]) -> str:
    raw_files = contract.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise KeeperError("KEEPER_SOURCE_FILE_LIST_INVALID")
    expected: dict[str, tuple[int, str]] = {}
    for row in raw_files:
        if not isinstance(row, dict):
            raise KeeperError("KEEPER_SOURCE_FILE_LIST_INVALID")
        relative = _safe_relative(row.get("path"))
        if relative in expected:
            raise KeeperError("KEEPER_SOURCE_FILE_LIST_DUPLICATE")
        expected[relative] = (
            _positive_int(row.get("bytes"), "KEEPER_SOURCE_FILE_SIZE_INVALID"),
            _sha(row.get("sha256"), "KEEPER_SOURCE_HASH_INVALID"),
        )
    observed = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }
    if set(observed) != set(expected):
        raise KeeperError("KEEPER_SOURCE_FILE_LIST_MISMATCH")
    inventory: list[dict[str, object]] = []
    for relative in sorted(expected):
        size, digest = expected[relative]
        path = observed[relative]
        if path.stat().st_size != size or _file_sha256(path) != digest:
            raise KeeperError("KEEPER_SOURCE_CONTENT_MISMATCH")
        inventory.append({"path": relative, "bytes": size, "sha256": digest})
    return _canonical_sha256(inventory)


def _validate_contract(
    payload: object,
    *,
    repository: str,
    registry: object,
) -> tuple[dict[str, Any], ...]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "1"
        or payload.get("repository") != repository
        or not isinstance(payload.get("artifacts"), list)
    ):
        raise KeeperError("KEEPER_SOURCE_CONTRACT_INVALID")
    if not isinstance(registry, dict) or not isinstance(registry.get("campaigns"), list):
        raise KeeperError("KEEPER_REGISTRY_INVALID")
    active = [row for row in registry["campaigns"] if isinstance(row, dict) and row.get("active")]
    required_contracts: dict[str, int] = {}
    for campaign in active:
        names = campaign.get("source_artifact_contracts")
        if not isinstance(names, list):
            raise KeeperError("KEEPER_REGISTRY_SOURCE_CONTRACT_INVALID")
        for name in names:
            if name in required_contracts:
                raise KeeperError("KEEPER_SOURCE_CONTRACT_CONFLICT")
            if name == "runtime_input_pack_v1":
                required_contracts[str(name)] = _positive_int(
                    campaign.get("runtime_input_run_id"), "KEEPER_RUNTIME_RUN_ID_INVALID"
                )
            elif name == "reference_oracle_v1":
                required_contracts[str(name)] = _positive_int(
                    campaign.get("reference_run_id"), "KEEPER_REFERENCE_RUN_ID_INVALID"
                )
            else:
                raise KeeperError("KEEPER_SOURCE_CONTRACT_UNSUPPORTED")
    rows: dict[str, dict[str, Any]] = {}
    for raw in payload["artifacts"]:
        if not isinstance(raw, dict):
            raise KeeperError("KEEPER_SOURCE_CONTRACT_INVALID")
        row = dict(raw)
        name = row.get("contract_name")
        artifact_name = str(row.get("artifact_name", "")).casefold()
        if (
            not isinstance(name, str)
            or name in rows
            or row.get("classification") not in {"training_input", "training_reference"}
            or row.get("validation_opened") is not False
            or row.get("locked_opened") is not False
            or any(marker in artifact_name for marker in _FORBIDDEN_BOUNDARY_MARKERS)
        ):
            raise KeeperError("KEEPER_SOURCE_BOUNDARY_INVALID")
        if _positive_int(row.get("run_id"), "KEEPER_SOURCE_RUN_ID_INVALID") != required_contracts.get(name):
            raise KeeperError("KEEPER_SOURCE_RUN_BINDING_MISMATCH")
        _positive_int(row.get("artifact_id"), "KEEPER_SOURCE_ARTIFACT_ID_INVALID")
        _positive_int(row.get("artifact_size_in_bytes"), "KEEPER_SOURCE_SIZE_INVALID")
        digest = str(row.get("artifact_digest", ""))
        if not digest.startswith("sha256:"):
            raise KeeperError("KEEPER_SOURCE_ARTIFACT_DIGEST_INVALID")
        _sha(digest.removeprefix("sha256:"), "KEEPER_SOURCE_ARTIFACT_DIGEST_INVALID")
        if not re.fullmatch(r"[0-9a-f]{40}", str(row.get("head_sha", ""))):
            raise KeeperError("KEEPER_SOURCE_HEAD_SHA_INVALID")
        rows[name] = row
    if set(rows) != set(required_contracts):
        raise KeeperError("KEEPER_SOURCE_CONTRACT_COVERAGE_INVALID")
    return tuple(rows[name] for name in sorted(rows))


def _artifact_metadata(
    rows: tuple[dict[str, Any], ...], contract: dict[str, Any]
) -> dict[str, Any]:
    matches = [row for row in rows if row.get("id") == contract["artifact_id"]]
    if len(matches) != 1:
        raise KeeperError("KEEPER_SOURCE_ARTIFACT_UNAVAILABLE")
    row = matches[0]
    workflow_run = row.get("workflow_run")
    if (
        row.get("name") != contract["artifact_name"]
        or row.get("size_in_bytes") != contract["artifact_size_in_bytes"]
        or row.get("digest") != contract["artifact_digest"]
        or row.get("expired") is not False
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != contract["run_id"]
        or workflow_run.get("head_sha") != contract["head_sha"]
    ):
        raise KeeperError("KEEPER_SOURCE_ARTIFACT_BINDING_MISMATCH")
    _parse_time(row.get("expires_at"), "KEEPER_SOURCE_EXPIRY_INVALID")
    return row


def _tree_manifest(root: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


def _inventory(args: argparse.Namespace) -> int:
    repository = args.repository
    if not _REPOSITORY.fullmatch(repository) or not re.fullmatch(
        r"[0-9a-f]{40}", args.protected_commit_sha
    ):
        raise KeeperError("KEEPER_IDENTITY_INVALID")
    maximum_download_bytes = _positive_int(
        args.maximum_download_bytes, "KEEPER_DOWNLOAD_CAP_INVALID"
    )
    maximum_artifact_copies = _positive_int(
        args.maximum_artifact_copies, "KEEPER_COPY_CAP_INVALID"
    )
    maximum_cache_restores = _positive_int(
        args.maximum_cache_restores, "KEEPER_CACHE_CAP_INVALID"
    )
    if (
        maximum_download_bytes > 1_073_741_824
        or maximum_artifact_copies > 8
        or maximum_cache_restores > 16
    ):
        raise KeeperError("KEEPER_FIXED_CAP_EXCEEDED")

    controls = _validate_controls_receipt(
        _read_json(args.controls_receipt),
        repository=repository,
        protected_commit_sha=args.protected_commit_sha,
    )
    registry_payload = _read_json(args.registry)
    source_contract_payload = _read_json(args.source_contract)
    source_contracts = _validate_contract(
        source_contract_payload,
        repository=repository,
        registry=registry_payload,
    )

    client = GitHubReadOnlyClient(repository, os.environ.get("GH_TOKEN", ""))
    source_inventory: list[dict[str, Any]] = []
    run_rows: dict[int, tuple[dict[str, Any], ...]] = {}
    for contract in source_contracts:
        run_id = int(contract["run_id"])
        if run_id not in run_rows:
            run_rows[run_id] = client.stable_paginated(
                f"/repos/{repository}/actions/runs/{run_id}/artifacts",
                "artifacts",
            )
        source_inventory.append(_artifact_metadata(run_rows[run_id], contract))

    caches = client.stable_paginated(
        f"/repos/{repository}/actions/caches", "actions_caches"
    )
    cache_ids = [row.get("id") for row in caches]
    if len(cache_ids) != len(set(cache_ids)):
        raise KeeperError("KEEPER_CACHE_DUPLICATE_ID")

    observed_at = client.observed_at
    if observed_at is None:
        raise KeeperError("KEEPER_GITHUB_TIME_UNAVAILABLE")
    artifact_headroom = controls.get("free_artifact_storage_headroom")
    cache_headroom = controls.get("free_cache_storage_headroom")
    headroom_known = (
        isinstance(artifact_headroom, int)
        and not isinstance(artifact_headroom, bool)
        and isinstance(cache_headroom, int)
        and not isinstance(cache_headroom, bool)
    )
    download_budget = min(
        maximum_download_bytes,
        int(cast(int, artifact_headroom) * 0.8) if headroom_known else 0,
    )

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    selected_bytes = 0
    threshold = observed_at + timedelta(days=21)
    for contract, metadata in zip(source_contracts, source_inventory, strict=True):
        expires_at = _parse_time(metadata["expires_at"], "KEEPER_SOURCE_EXPIRY_INVALID")
        if expires_at >= threshold:
            continue
        size = int(metadata["size_in_bytes"])
        if (
            not headroom_known
            or len(selected) >= maximum_artifact_copies
            or selected_bytes + size > download_budget
        ):
            continue
        selected.append((contract, metadata))
        selected_bytes += size

    output = args.output.resolve()
    if output.exists():
        if any(output.iterdir()):
            raise KeeperError("KEEPER_OUTPUT_MUST_START_EMPTY")
    else:
        output.mkdir(parents=True)
    mirrors: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="aurora-catalog-keeper-") as temp_raw:
        temp = Path(temp_raw)
        for contract, metadata in selected:
            artifact_id = int(contract["artifact_id"])
            archive = temp / f"{artifact_id}.zip"
            archive_sha256 = client.download_artifact(
                artifact_id,
                archive,
                min(maximum_download_bytes, int(metadata["size_in_bytes"]) + 4_194_304),
            )
            expected_archive_sha256 = str(contract["artifact_digest"]).removeprefix(
                "sha256:"
            )
            if archive_sha256 != expected_archive_sha256:
                raise KeeperError("KEEPER_SOURCE_ARCHIVE_DIGEST_MISMATCH")
            extracted = temp / f"extracted-{artifact_id}"
            _safe_extract(archive, extracted, maximum_download_bytes * 8)
            mode = contract.get("verification_mode")
            if mode == "runtime_input_manifest_v1":
                content_root = _verify_runtime_input_manifest(extracted, contract)
            elif mode == "closed_file_list_v1":
                content_root = _verify_closed_file_list(extracted, contract)
            else:
                raise KeeperError("KEEPER_SOURCE_VERIFICATION_MODE_INVALID")
            destination = output / "mirrors" / str(artifact_id) / "artifact.zip"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive, destination)
            mirrors.append(
                {
                    "contract_name": contract["contract_name"],
                    "original_run_id": contract["run_id"],
                    "original_artifact_id": artifact_id,
                    "original_artifact_name": contract["artifact_name"],
                    "original_artifact_digest": contract["artifact_digest"],
                    "original_expires_at": metadata["expires_at"],
                    "mirror_path": destination.relative_to(output).as_posix(),
                    "mirror_bytes": destination.stat().st_size,
                    "mirror_sha256": archive_sha256,
                    "verified_content_root_sha256": content_root,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            )

    source_contract_copy = output / "catalog_keeper_source_artifacts_v1.json"
    source_contract_copy.write_bytes(args.source_contract.read_bytes())
    receipt_payload: dict[str, Any] = {
        "schema_version": "catalog_artifact_keeper_receipt_v1",
        "status": "ready",
        "repository": repository,
        "protected_commit_sha": args.protected_commit_sha,
        "controls_receipt_sha256": controls["receipt_sha256"],
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "source_contract_sha256": _file_sha256(source_contract_copy),
        "stable_source_run_ids": sorted(run_rows),
        "source_artifact_ids": sorted(int(row["id"]) for row in source_inventory),
        "source_artifacts_expiring_within_21_days": sorted(
            int(row["id"])
            for row in source_inventory
            if _parse_time(row["expires_at"], "KEEPER_SOURCE_EXPIRY_INVALID")
            < threshold
        ),
        "mirrors": mirrors,
        "cache_inventory_sha256": _canonical_sha256(caches),
        "cache_inventory_count": len(caches),
        "cache_restore_plan": [],
        "cache_restore_reason": "no_verified_active_store_receipt",
        "headroom_known": headroom_known,
        "maximum_download_bytes": maximum_download_bytes,
        "maximum_artifact_copies": maximum_artifact_copies,
        "maximum_cache_restores": maximum_cache_restores,
        "selected_download_bytes": selected_bytes,
        "validation_opened": False,
        "locked_opened": False,
    }
    uncovered = set(receipt_payload["source_artifacts_expiring_within_21_days"]) - {
        row["original_artifact_id"] for row in mirrors
    }
    if uncovered:
        receipt_payload["status"] = "blocked"
        receipt_payload["failure_code"] = "KEEPER_SOURCE_RETENTION_HEADROOM_INSUFFICIENT"
        receipt_payload["uncovered_source_artifact_ids"] = sorted(uncovered)
    receipt_sha256 = _canonical_sha256(receipt_payload)
    receipt = {**receipt_payload, "receipt_sha256": receipt_sha256}
    _write_json(output / "catalog_artifact_keeper_receipt_v1.json", receipt)
    manifest = _tree_manifest(output)
    _write_json(
        output / "catalog_artifact_keeper_output_manifest_v1.json",
        {
            "schema_version": "catalog_artifact_keeper_output_manifest_v1",
            "files": manifest,
            "aggregate_sha256": _canonical_sha256(manifest),
        },
    )
    return 0


def _normalize_readback_root(expected: Path, observed: Path) -> Path:
    if (observed / "catalog_artifact_keeper_receipt_v1.json").is_file():
        return observed
    candidates = [
        path.parent
        for path in observed.rglob("catalog_artifact_keeper_receipt_v1.json")
    ]
    if len(candidates) != 1:
        raise KeeperError("KEEPER_READBACK_ROOT_AMBIGUOUS")
    relative_files = {
        path.relative_to(candidates[0]).as_posix()
        for path in candidates[0].rglob("*")
        if path.is_file()
    }
    expected_files = {
        path.relative_to(expected).as_posix()
        for path in expected.rglob("*")
        if path.is_file()
    }
    if relative_files != expected_files:
        raise KeeperError("KEEPER_READBACK_FILE_LIST_MISMATCH")
    return candidates[0]


def _verify_readback(args: argparse.Namespace) -> int:
    expected = args.expected.resolve(strict=True)
    observed = _normalize_readback_root(expected, args.observed.resolve(strict=True))
    expected_manifest = _tree_manifest(expected)
    observed_manifest = _tree_manifest(observed)
    if expected_manifest != observed_manifest:
        raise KeeperError("KEEPER_READBACK_CONTENT_MISMATCH")
    receipt = _read_json(observed / "catalog_artifact_keeper_receipt_v1.json")
    if not isinstance(receipt, dict):
        raise KeeperError("KEEPER_READBACK_RECEIPT_INVALID")
    claimed = _sha(receipt.get("receipt_sha256"), "KEEPER_READBACK_RECEIPT_INVALID")
    if _canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"}) != claimed:
        raise KeeperError("KEEPER_READBACK_RECEIPT_HASH_MISMATCH")
    if receipt.get("status") != "ready":
        raise KeeperError(str(receipt.get("failure_code", "KEEPER_MAINTENANCE_BLOCKED")))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--repository", required=True)
    inventory.add_argument("--protected-commit-sha", required=True)
    inventory.add_argument("--registry", type=Path, required=True)
    inventory.add_argument("--source-contract", type=Path, required=True)
    inventory.add_argument("--controls-receipt", type=Path, required=True)
    inventory.add_argument("--maximum-download-bytes", type=int, required=True)
    inventory.add_argument("--maximum-artifact-copies", type=int, required=True)
    inventory.add_argument("--maximum-cache-restores", type=int, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.set_defaults(func=_inventory)
    verify = subparsers.add_parser("verify-readback")
    verify.add_argument("--expected", type=Path, required=True)
    verify.add_argument("--observed", type=Path, required=True)
    verify.set_defaults(func=_verify_readback)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.func(args))
    except KeeperError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    raise SystemExit(main())
