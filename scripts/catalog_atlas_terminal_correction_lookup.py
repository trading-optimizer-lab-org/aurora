"""Resolve the one authority-pinned Atlas terminal correction for replay."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Callable, Mapping, Protocol

from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceipt, parse_catalog_terminal_receipt
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    FastGateOwnerEvidence, _nonfinite, _object, bind_owner_terminal_receipt,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogStableInventory


class _Reader(Protocol):
    repository: str

    def stable_paginated(self, path: str, *, root: str) -> CatalogStableInventory: ...
    def get_json(self, path: str) -> tuple[object, object]: ...


def resolve_atlas_terminal_correction(*, client: _Reader, owner: FastGateOwnerEvidence,
                                      issue_number: int, original: CatalogTerminalReceipt,
                                      expected_sha256: str,
                                      download_archive: Callable[[int], bytes]) -> CatalogTerminalReceipt:
    """Only issue 378's proven-bad receipt may be superseded in a replay."""
    if (issue_number != 378 or owner.run_id != 36032882147
        or owner.decision.request_sha256 != "4fe5767ac61c2b8ac92adce450bd0d726801f033c5e7e3f29f8d40b59d281834"
        or original.receipt_sha256 != "b8918eee4510d094153756c02baa387c61d5623f91335d5f34707d9e5493ac7f"
        or original.reason_code != "ATLAS_TERMINAL_CATALOG_HASH_INVALID"):
        raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_CONFLICT")
    return _load_atlas_terminal_correction(
        client=client, owner=owner, expected_sha256=expected_sha256,
        download_archive=download_archive,
    )


def _load_atlas_terminal_correction(*, client: _Reader, owner: FastGateOwnerEvidence,
                                    expected_sha256: str,
                                    download_archive: Callable[[int], bytes]) -> CatalogTerminalReceipt:
    code = "CATALOG_FAST_ATLAS_TERMINAL_CORRECTION_INVALID"
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError(code)
    inventory = client.stable_paginated(
        f"/repos/{client.repository}/actions/artifacts?name=catalog-terminal-correction-378",
        root="artifacts",
    )
    if inventory.stable is not True or inventory.collection.complete is not True:
        raise ValueError(code)
    matches: list[CatalogTerminalReceipt] = []
    for artifact in inventory.collection.rows:
        try:
            source = artifact["workflow_run"]
            run_id = source["id"]
            if (client.repository != "trading-optimizer-lab-org/aurora"
                or artifact["name"] != "catalog-terminal-correction-378"
                or artifact["expired"] is not False
                or type(run_id) is not int or run_id < 1
                or source["head_branch"] != "main"
                or source["repository_id"] != owner.run["repository"]["id"]
                or source["head_repository_id"] != owner.run["repository"]["id"]
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
                or type(artifact["size_in_bytes"]) is not int
                or not 0 < artifact["size_in_bytes"] <= 2 * 1024 * 1024):
                continue
            run, _ = client.get_json(f"/repos/{client.repository}/actions/runs/{run_id}")
            if (not isinstance(run, Mapping) or run.get("id") != run_id
                or run.get("head_sha") != source["head_sha"]
                or run.get("head_branch") != "main"
                or run.get("path") != ".github/workflows/catalog-fast-authority-maintenance.yml"
                or run.get("event") != "workflow_dispatch"
                or (run.get("status"), run.get("conclusion")) != ("completed", "success")
                or run.get("repository", {}).get("id") != owner.run["repository"]["id"]):
                continue
            jobs = client.stable_paginated(
                f"/repos/{client.repository}/actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs",
                root="jobs",
            )
            if jobs.stable is not True or jobs.collection.complete is not True:
                continue
            writers = [job for job in jobs.collection.rows if job.get("name") == "bootstrap"]
            if (len(writers) != 1 or writers[0].get("conclusion") != "success"
                or writers[0].get("status") != "completed"
                or writers[0].get("run_id") != run_id
                or writers[0].get("run_attempt") != run["run_attempt"]
                or writers[0].get("head_sha") != run["head_sha"]):
                continue
            steps = writers[0].get("steps", ())
            labels = ("Reverify all original Atlas results", "Publish independently verified Atlas terminal",
                      "Write current authority edition", "Publish current authority edition",
                      "Verify initial authority through its production reader")
            selected = [[step for step in steps if step.get("name") == label] for label in labels]
            if any(len(items) != 1 or items[0].get("conclusion") != "success" for items in selected):
                continue
            if [items[0]["number"] for items in selected] != sorted(items[0]["number"] for items in selected):
                continue
            raw = download_archive(artifact["id"])
            if not raw or len(raw) != artifact["size_in_bytes"] or hashlib.sha256(raw).hexdigest() != artifact["digest"][7:]:
                continue
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                if (len(members) != 1 or members[0].filename != "catalog-terminal-receipt-v1.json"
                    or members[0].is_dir() or members[0].flag_bits & 1
                    or ((members[0].external_attr >> 16) & 0o170000) not in {0, 0o100000}
                    or not 0 < members[0].file_size <= 8192):
                    continue
                corrected = parse_catalog_terminal_receipt(json.loads(
                    archive.read(members[0]), object_pairs_hook=_object, parse_constant=_nonfinite,
                ))
            if (corrected.receipt_sha256 != expected_sha256 or corrected.state != "SUCCESS"
                or corrected.reason_code != "CATALOG_RUN_SUCCESS"
                or corrected.request_sha256 != owner.decision.request_sha256
                or corrected.engine_run_id != owner.run_id
                or corrected.observed_recipe_count != 209906
                or corrected.expected_recipe_count != 209906
                or corrected.result_science_sha256 != "18e614ffd8ef079fe7f6488db922d8bee33f539d07f37dc2de4bc1309c12df42"):
                continue
            bind_owner_terminal_receipt(owner=owner, receipt=corrected)
            matches.append(corrected)
        except (KeyError, TypeError, ValueError, AttributeError, OSError, zipfile.BadZipFile):
            continue
    if len(matches) != 1:
        raise ValueError(code)
    return matches[0]
