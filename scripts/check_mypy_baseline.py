"""Reject new mypy errors while preserving visible, frozen legacy debt."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ERROR_RE = re.compile(
    r"^(?:.*?Z )?(.*?):(\d+)(?::\d+)?: error: (.*?)  \[([^\]]+)\]$"
)


def parse_mypy_errors(output: str) -> Counter[tuple[str, str, str]]:
    """Return path/code/message fingerprints without unstable line numbers."""
    errors: Counter[tuple[str, str, str]] = Counter()
    for line in output.splitlines():
        match = ERROR_RE.match(line)
        if match is None:
            continue
        path, _line_number, message, code = match.groups()
        errors[(path.replace("\\", "/"), code, message)] += 1
    return errors


def load_baseline(path: Path) -> tuple[dict[str, Any], Counter[tuple[str, str, str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise ValueError("mypy baseline schema is unsupported")
    rows = payload.get("errors")
    if not isinstance(rows, list):
        raise ValueError("mypy baseline errors are missing")
    errors: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("mypy baseline row is invalid")
        path_value = row.get("path")
        code = row.get("code")
        message = row.get("message")
        count = row.get("count")
        if (
            not isinstance(path_value, str)
            or not path_value
            or not isinstance(code, str)
            or not code
            or not isinstance(message, str)
            or not message
            or not isinstance(count, int)
            or count < 1
        ):
            raise ValueError("mypy baseline row is invalid")
        key = (path_value.replace("\\", "/"), code, message)
        if key in errors:
            raise ValueError("duplicate mypy baseline fingerprint")
        errors[key] = count
    return payload, errors


def baseline_payload(
    errors: Counter[tuple[str, str, str]],
    *,
    run_id: int,
    commit_sha: str,
) -> dict[str, Any]:
    files = {path for path, _code, _message in errors}
    return {
        "schema_version": "1",
        "policy": (
            "legacy errors are visible and tolerated only by exact "
            "path/code/message multiplicity; any new error fails CI"
        ),
        "source": {
            "github_run_id": run_id,
            "commit_sha": commit_sha,
            "error_count": sum(errors.values()),
            "file_count": len(files),
        },
        "errors": [
            {
                "path": path,
                "code": code,
                "message": message,
                "count": count,
            }
            for (path, code, message), count in sorted(errors.items())
        ],
    }


def compare_errors(
    current: Counter[tuple[str, str, str]],
    allowed: Counter[tuple[str, str, str]],
) -> tuple[
    Counter[tuple[str, str, str]],
    Counter[tuple[str, str, str]],
]:
    return current - allowed, allowed - current


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("config/mypy_error_baseline.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("mypy_report.txt"),
    )
    parser.add_argument("--record-from-report", type=Path)
    parser.add_argument("--check-report", type=Path)
    parser.add_argument("--source-run-id", type=int)
    parser.add_argument("--source-commit-sha")
    return parser


def _record(args: argparse.Namespace) -> int:
    if args.source_run_id is None or args.source_commit_sha is None:
        raise ValueError(
            "recording requires --source-run-id and --source-commit-sha"
        )
    errors = parse_mypy_errors(
        args.record_from_report.read_text(encoding="utf-8")
    )
    if not errors:
        raise ValueError("recording report contains no mypy errors")
    payload = baseline_payload(
        errors,
        run_id=args.source_run_id,
        commit_sha=args.source_commit_sha,
    )
    args.baseline.parent.mkdir(parents=True, exist_ok=True)
    args.baseline.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["source"], sort_keys=True))
    return 0


def _check(args: argparse.Namespace) -> int:
    baseline_payload_value, allowed = load_baseline(args.baseline)
    if args.check_report is not None:
        output = args.check_report.read_text(encoding="utf-8")
    else:
        command = [
            sys.executable,
            "-m",
            "mypy",
            ".",
            "--no-color-output",
            "--show-error-codes",
            "--no-error-summary",
        ]
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = completed.stdout + completed.stderr
    args.report.write_text(output, encoding="utf-8")
    current = parse_mypy_errors(output)
    new_errors, resolved_errors = compare_errors(current, allowed)
    summary = {
        "schema_version": "1",
        "valid": not new_errors,
        "baseline_source": baseline_payload_value["source"],
        "baseline_error_count": sum(allowed.values()),
        "current_error_count": sum(current.values()),
        "new_error_count": sum(new_errors.values()),
        "resolved_error_count": sum(resolved_errors.values()),
        "current_file_count": len(
            {path for path, _code, _message in current}
        ),
        "new_errors": [
            {
                "path": path,
                "code": code,
                "message": message,
                "count": count,
            }
            for (path, code, message), count in sorted(new_errors.items())
        ],
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 1 if new_errors else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.record_from_report is not None:
        return _record(args)
    return _check(args)


if __name__ == "__main__":
    raise SystemExit(main())
