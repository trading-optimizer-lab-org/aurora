#!/usr/bin/env python3
"""Prepare a mirror-first terminal request receipt and atomic close payload."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

from aurora.infra.sp500_megarun.catalog_authority_writer import (
    CatalogAuthorityTransitionCandidateV1,
)
from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    CatalogTerminalDecisionV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
    build_terminal_request_receipt,
    next_request_receipt_sequence,
)


_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_MAX_JSON_BYTES = 1024 * 1024
_MAX_SUMMARY_BYTES = 256 * 1024


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_REQUEST_RECEIPT_JSON_DUPLICATE")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_REQUEST_RECEIPT_JSON_NONFINITE:{value}")


def _json(path: Path, *, runner_temp: Path) -> object:
    if path.is_symlink():
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID") from None
    if (
        not resolved.is_file()
        or not resolved.is_relative_to(runner_temp)
        or resolved.stat().st_size > _MAX_JSON_BYTES
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    try:
        return json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("CATALOG_REQUEST_RECEIPT_JSON_INVALID") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare one terminal request receipt without writing GitHub."
    )
    parser.add_argument("--terminal-decision", required=True, type=Path)
    parser.add_argument("--authority-candidate", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--request-receipts", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def _delivery_sequence(
    path: Path,
    *,
    runner_temp: Path,
    issue_number: int,
    request_sha256: str,
) -> int:
    document = _json(path, runner_temp=runner_temp)
    if not isinstance(document, dict) or any(
        document.get(flag) is not True
        for flag in ("complete", "stable", "sequence_valid")
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    rows = document.get("receipts")
    trusted_hashes = document.get("trusted_receipt_sha256s")
    if not isinstance(rows, list) or not isinstance(trusted_hashes, list):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    trusted = set(trusted_hashes)
    receipts: list[CatalogRequestReceiptV1] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("receipt") is None:
            continue
        receipt = CatalogRequestReceiptV1.model_validate(row["receipt"])
        if receipt.receipt_sha256 in trusted:
            receipts.append(receipt)
    sequence = next_request_receipt_sequence(
        receipts,
        issue_number=issue_number,
        request_sha256=request_sha256,
    )
    if document.get("next_delivery_sequence") != sequence:
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    return sequence


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
        if not runner_temp_raw:
            raise ValueError("CATALOG_REQUEST_RECEIPT_ENVIRONMENT_INVALID")
        runner_temp = Path(runner_temp_raw).resolve(strict=True)
        resolved_output = args.output_dir.resolve(strict=False)
        if (
            args.output_dir.exists()
            or args.output_dir.is_symlink()
            or not resolved_output.is_relative_to(runner_temp)
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_OUTPUT_INVALID")
        if args.summary.is_symlink():
            raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
        summary_path = args.summary.resolve(strict=True)
        if (
            not summary_path.is_file()
            or not summary_path.is_relative_to(runner_temp)
            or summary_path.stat().st_size > _MAX_SUMMARY_BYTES
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
        summary = summary_path.read_text(encoding="utf-8")
        decision = CatalogTerminalDecisionV1.model_validate(
            _json(args.terminal_decision, runner_temp=runner_temp)
        )
        candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
            _json(args.authority_candidate, runner_temp=runner_temp)
        )
        receipt = build_terminal_request_receipt(
            decision=decision,
            authority_candidate=candidate,
            summary=summary,
            delivery_sequence=_delivery_sequence(
                args.request_receipts,
                runner_temp=runner_temp,
                issue_number=candidate.record.request_issue_number,
                request_sha256=candidate.record.request_sha256,
            ),
        )
        args.output_dir.mkdir(parents=False, exist_ok=False)
        (args.output_dir / "request-receipt.json").write_bytes(
            canonical_model_bytes(receipt) + b"\n"
        )
        (args.output_dir / "comment.md").write_text(
            receipt.comment_body(summary), encoding="utf-8", newline="\n"
        )
        (args.output_dir / "terminal-issue-patch.json").write_text(
            json.dumps(
                {
                    "labels": ["catalog-run-terminal-v1"],
                    "state": "closed",
                    "state_reason": "completed",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        values = {
            "artifact_name": receipt.artifact_name,
            "receipt_sha256": receipt.receipt_sha256,
            "issue_number": str(receipt.issue_number),
        }
        if args.github_output is not None:
            if args.github_output.is_symlink():
                raise ValueError("CATALOG_REQUEST_RECEIPT_GITHUB_OUTPUT_INVALID")
            github_output = args.github_output.resolve(strict=True)
            if (
                not github_output.is_file()
                or not github_output.is_relative_to(runner_temp)
                or any(not _SAFE.fullmatch(value) for value in values.values())
            ):
                raise ValueError("CATALOG_REQUEST_RECEIPT_GITHUB_OUTPUT_INVALID")
            with args.github_output.open(
                "a", encoding="utf-8", newline="\n"
            ) as stream:
                for key, value in values.items():
                    stream.write(f"{key}={value}\n")
        print(json.dumps(values, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
