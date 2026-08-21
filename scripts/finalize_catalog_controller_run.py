#!/usr/bin/env python3
"""Verify bound terminal evidence and render the only catalog final decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    FINALIZER_INPUT_NAMES,
    CatalogFinalizerEnvelopeV1,
    CatalogTerminalDecisionV1,
    finalize_catalog_run,
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _parse_json_bytes(data: bytes, *, code: str) -> dict[str, object]:
    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except Exception as exc:
        raise ValueError(f"{code}: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError(f"{code}: root must be an object")
    return payload


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file(path: Path, *, code: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{code}: expected one regular file")
    return path.read_bytes()


def _input_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "authority_issue": args.authority_issue,
        "authority_comments": args.authority_comments,
        "authority_mirrors": args.authority_mirrors,
        "authority_timeline": args.authority_timeline,
        "authority_anchor": args.authority_anchor,
        "request_issue": args.request_issue,
        "request_timeline": args.request_timeline,
        "request_receipts": args.request_receipts,
        "tamper_incidents": args.tamper_incidents,
        "github_controls_before_reserve": args.github_controls_before_reserve,
        "github_controls_before_terminal": args.github_controls_before_terminal,
    }


def _verify_external_inputs(
    *,
    envelope: CatalogFinalizerEnvelopeV1,
    paths: dict[str, Path],
) -> None:
    if set(paths) != set(FINALIZER_INPUT_NAMES):
        raise ValueError("CATALOG_FINALIZER_INPUT_SET_INVALID")
    for name in FINALIZER_INPUT_NAMES:
        data = _read_regular_file(
            paths[name],
            code=f"CATALOG_FINALIZER_INPUT_INVALID:{name}",
        )
        if _sha256(data) != envelope.input_sha256s[name]:
            raise ValueError(f"CATALOG_FINALIZER_INPUT_HASH_MISMATCH:{name}")
        _parse_json_bytes(data, code=f"CATALOG_FINALIZER_INPUT_JSON_INVALID:{name}")


def _verify_final_evidence_directory(
    *,
    envelope: CatalogFinalizerEnvelopeV1,
    directory: Path,
) -> dict[str, str]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("CATALOG_FINAL_EVIDENCE_DIRECTORY_INVALID")
    slots = envelope.final_evidence.evidence_slots
    expected = {
        slot.artifact_or_receipt_id
        for slot in slots.values()
        if slot.status == "present"
    }
    if None in expected:
        raise ValueError("CATALOG_FINAL_EVIDENCE_ID_INVALID")
    entries = tuple(directory.iterdir())
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ValueError("CATALOG_FINAL_EVIDENCE_FILE_UNEXPECTED")
    actual = {entry.name for entry in entries}
    unexpected = actual - expected
    if unexpected:
        raise ValueError(
            "CATALOG_FINAL_EVIDENCE_FILE_UNEXPECTED: "
            + ",".join(sorted(unexpected))
        )
    missing = expected - actual
    if missing:
        raise ValueError(
            "CATALOG_FINAL_EVIDENCE_FILE_MISSING: "
            + ",".join(sorted(missing))
        )
    hashes: dict[str, str] = {}
    slots_by_filename = {
        slot.artifact_or_receipt_id: slot
        for slot in slots.values()
        if slot.status == "present"
    }
    for filename in sorted(actual):
        path = directory / filename
        data = _read_regular_file(path, code="CATALOG_FINAL_EVIDENCE_FILE_INVALID")
        observed = _sha256(data)
        expected_hash = slots_by_filename[filename].sha256
        if observed != expected_hash:
            raise ValueError(
                f"CATALOG_FINAL_EVIDENCE_HASH_MISMATCH:{filename}"
            )
        _parse_json_bytes(data, code="CATALOG_FINAL_EVIDENCE_JSON_INVALID")
        hashes[filename] = observed
    return hashes


def _content_hashed_payload(
    payload: dict[str, object],
    *,
    hash_field: str,
) -> dict[str, object]:
    result = dict(payload)
    result[hash_field] = _sha256(_canonical_bytes(payload))
    return result


def _authority_comment(decision: CatalogTerminalDecisionV1) -> str:
    record = {
        "schema_version": "1",
        "state": decision.state.value.lower(),
        "reason_code": decision.reason_code,
        "authority_id": str(decision.authority_id),
        "request_sha256": decision.request_sha256,
        "campaign_id": decision.campaign_id,
        "science_sha256": decision.science_sha256,
        "execution_plan_sha256": decision.execution_plan_sha256,
        "protected_commit_sha": decision.protected_commit_sha,
        "evidence_sha256": decision.terminal_decision_sha256,
    }
    return (
        "<!-- AURORA_CATALOG_TERMINAL_DECISION_V1 -->\n"
        "```json\n"
        + _canonical_bytes(record).decode("utf-8")
        + "\n```\n"
        "<!-- /AURORA_CATALOG_TERMINAL_DECISION_V1 -->\n"
    )


def _write_outputs(
    *,
    output_dir: Path,
    decision: CatalogTerminalDecisionV1,
    source_evidence_hashes: dict[str, str],
    external_input_hashes: MappingString,
) -> None:
    output_dir.mkdir(parents=False, exist_ok=False)
    generated_hashes: dict[str, str] = {}

    def write_bytes(name: str, content: bytes) -> None:
        (output_dir / name).write_bytes(content)
        generated_hashes[name] = _sha256(content)

    write_bytes(
        "catalog_terminal_decision.json",
        _canonical_bytes(decision) + b"\n",
    )
    write_bytes("catalog_run_summary.md", decision.human_summary.encode("utf-8"))
    if decision.authority_append_allowed:
        write_bytes(
            "catalog_terminal_authority_comment.md",
            _authority_comment(decision).encode("utf-8"),
        )
    if decision.request_comment_allowed:
        write_bytes(
            "catalog_request_result_comment.md",
            decision.human_summary.encode("utf-8"),
        )
    if decision.standalone_incident_artifact_required:
        incident = _content_hashed_payload(
            {
                "schema_version": "1",
                "state": decision.state.value,
                "reason_code": decision.reason_code,
                "authority_id": str(decision.authority_id),
                "request_sha256": decision.request_sha256,
                "terminal_decision_sha256": decision.terminal_decision_sha256,
                "authority_append_allowed": False,
            },
            hash_field="incident_sha256",
        )
        write_bytes(
            "catalog_standalone_incident.json",
            _canonical_bytes(incident) + b"\n",
        )
    manifest = _content_hashed_payload(
        {
            "schema_version": "1",
            "terminal_decision_sha256": decision.terminal_decision_sha256,
            "source_evidence_sha256s": source_evidence_hashes,
            "external_input_sha256s": dict(sorted(external_input_hashes.items())),
            "generated_file_sha256s": dict(sorted(generated_hashes.items())),
        },
        hash_field="manifest_sha256",
    )
    write_bytes(
        "catalog_final_evidence_manifest.json",
        _canonical_bytes(manifest) + b"\n",
    )


MappingString = dict[str, str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the fixed catalog evidence set and render one truthful "
            "terminal decision. This command never posts to GitHub."
        )
    )
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--authority-issue", required=True, type=Path)
    parser.add_argument("--authority-comments", required=True, type=Path)
    parser.add_argument("--authority-mirrors", required=True, type=Path)
    parser.add_argument("--authority-timeline", required=True, type=Path)
    parser.add_argument("--authority-anchor", required=True, type=Path)
    parser.add_argument("--request-issue", required=True, type=Path)
    parser.add_argument("--request-timeline", required=True, type=Path)
    parser.add_argument("--request-receipts", required=True, type=Path)
    parser.add_argument("--tamper-incidents", required=True, type=Path)
    parser.add_argument("--final-evidence-directory", required=True, type=Path)
    parser.add_argument(
        "--github-controls-before-reserve",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--github-controls-before-terminal",
        required=True,
        type=Path,
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.output_dir.exists() or args.output_dir.is_symlink():
            raise ValueError("CATALOG_FINAL_OUTPUT_EXISTS")
        decision_data = _read_regular_file(
            args.decision,
            code="CATALOG_FINAL_DECISION_INPUT_INVALID",
        )
        envelope = CatalogFinalizerEnvelopeV1.model_validate(
            _parse_json_bytes(
                decision_data,
                code="CATALOG_FINAL_DECISION_INPUT_JSON_INVALID",
            )
        )
        paths = _input_paths(args)
        _verify_external_inputs(envelope=envelope, paths=paths)
        source_hashes = _verify_final_evidence_directory(
            envelope=envelope,
            directory=args.final_evidence_directory,
        )
        decision = finalize_catalog_run(final_evidence=envelope.final_evidence)
        _write_outputs(
            output_dir=args.output_dir,
            decision=decision,
            source_evidence_hashes=source_hashes,
            external_input_hashes=dict(envelope.input_sha256s),
        )
        print(
            json.dumps(
                {
                    "state": decision.state.value,
                    "reason_code": decision.reason_code,
                    "terminal_decision_sha256": decision.terminal_decision_sha256,
                    "output_dir": str(args.output_dir),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
