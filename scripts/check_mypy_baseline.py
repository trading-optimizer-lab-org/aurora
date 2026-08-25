"""Reject new mypy errors while preserving visible, frozen legacy debt."""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

ERROR_RE = re.compile(
    r"^(?:.*?Z )?(.*?)(?::(\d+)(?::\d+)?)?: error: (.*?)\s+\[([^\]]+)\]$"
)
ERROR_LINE_RE = re.compile(r"^(?:.*?Z )?.*?: error:")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MYPY_CONFIG_NAMES = ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg")
Fingerprint = tuple[str, str, str]
ErrorCounter = Counter[Fingerprint]


class MypyInfrastructureError(RuntimeError):
    """The mypy process could not produce a trustworthy result."""


def _normalise_path(value: str) -> str:
    """Use one separator and remove syntactic path noise."""
    normalised = value.strip().replace("\\", "/")
    return posixpath.normpath(normalised)


def normalize_error_path(
    path: str,
    root: str | Path | None = None,
) -> str:
    """Return an error path relative to its checkout root when possible."""
    normalised_path = _normalise_path(path)
    if root is None:
        return normalised_path

    normalised_root = _normalise_path(os.fspath(root))
    if normalised_root in {"", "."}:
        return normalised_path

    windows_root = bool(re.match(r"^[A-Za-z]:/", normalised_root))
    windows_root = windows_root or normalised_root.startswith("//")
    compare_path = normalised_path.casefold() if windows_root else normalised_path
    compare_root = normalised_root.casefold() if windows_root else normalised_root
    if compare_path == compare_root:
        return "."

    prefix = compare_root.rstrip("/") + "/"
    if compare_path.startswith(prefix):
        return normalised_path[len(prefix) :]
    return normalised_path


def parse_mypy_errors(
    output: str,
    *,
    root: str | Path | None = None,
) -> ErrorCounter:
    """Return path/code/message fingerprints without unstable line numbers."""
    errors: ErrorCounter = Counter()
    for line in output.splitlines():
        match = ERROR_RE.match(line)
        if match is None:
            continue
        path, _line_number, message, code = match.groups()
        errors[(normalize_error_path(path, root), code, message.strip())] += 1
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


def compare_report_outputs(
    base_output: str,
    head_output: str,
    *,
    base_root: str | Path | None = None,
    head_root: str | Path | None = None,
) -> tuple[ErrorCounter, ErrorCounter]:
    """Compare normalized base and HEAD report multisets."""
    base_errors = parse_mypy_errors(base_output, root=base_root)
    head_errors = parse_mypy_errors(head_output, root=head_root)
    return compare_errors(head_errors, base_errors)


def validate_base_sha(value: str | None) -> str:
    """Validate and canonicalize a Git commit SHA used as the base."""
    if value is None or SHA_RE.fullmatch(value) is None or not value.strip("0"):
        raise ValueError(
            "base SHA must be a non-zero 40 hexadecimal character value"
        )
    return value.lower()


def _write_report(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")


def run_mypy(
    root: Path,
    *,
    config_file: Path | None,
    report: Path | None = None,
    python_executable: str | None = None,
) -> str:
    """Run mypy in one tree and reject every non-result exit code."""
    command = [
        python_executable or sys.executable,
        "-m",
        "mypy",
        ".",
        "--no-color-output",
        "--show-error-codes",
        "--no-error-summary",
        "--no-incremental",
    ]
    if config_file is not None:
        command.extend(["--config-file", str(config_file)])

    environment = os.environ.copy()
    # Make local imports resolve from the tree under test, never from the
    # other tree through an inherited checkout path.
    environment["PYTHONPATH"] = str(root)
    completed = subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        env=environment,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if report is not None:
        _write_report(report, output)
    if completed.returncode not in (0, 1):
        detail = output.strip()
        suffix = f": {detail}" if detail else ""
        raise MypyInfrastructureError(
            f"mypy failed with exit code {completed.returncode}{suffix}"
        )
    if completed.returncode == 1:
        error_lines = [
            line for line in output.splitlines() if ERROR_LINE_RE.match(line)
        ]
        unparsed_error_lines = [
            line for line in error_lines if ERROR_RE.match(line) is None
        ]
        if unparsed_error_lines:
            sample = " | ".join(unparsed_error_lines[:3])
            raise MypyInfrastructureError(
                "unparsed mypy error diagnostic(s) in exit-code-1 output: "
                f"{sample}"
            )
        if not error_lines:
            raise MypyInfrastructureError(
                "mypy returned exit code 1 without an error diagnostic"
            )
    return output


def _find_mypy_config(root: Path) -> Path | None:
    for name in MYPY_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _base_config(base_root: Path, temporary_root: Path) -> Path:
    config = _find_mypy_config(base_root)
    if config is not None:
        return config
    config = temporary_root / "mypy-empty.ini"
    config.write_text("[mypy]\n", encoding="utf-8")
    return config


def _extract_base_tree(
    repository_root: Path,
    base_sha: str,
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination.parent / "base-tree.tar"
    command = ["git", "archive", "--format=tar", base_sha]
    with archive_path.open("wb") as archive:
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            cwd=repository_root,
            stdout=archive,
            stderr=subprocess.PIPE,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise MypyInfrastructureError(
            f"could not archive base SHA {base_sha}{suffix}"
        )

    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise MypyInfrastructureError(
                        f"base archive contains an unsafe path: {member.name}"
                    )
            archive.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        raise MypyInfrastructureError(
            f"could not extract base SHA {base_sha}: {exc}"
        ) from exc


def _counter_rows(errors: ErrorCounter) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "code": code,
            "message": message,
            "count": count,
        }
        for (path, code, message), count in sorted(errors.items())
    ]


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
    parser.add_argument(
        "--base-report",
        type=Path,
        default=Path("mypy_base_report.txt"),
    )
    parser.add_argument("--base-sha")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
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
        output = run_mypy(Path.cwd(), config_file=None, report=args.report)
    if args.check_report is not None:
        _write_report(args.report, output)
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


def _differential(args: argparse.Namespace) -> int:
    base_sha = validate_base_sha(args.base_sha)
    repository_root = args.repo_root.resolve()
    head_root = repository_root

    with tempfile.TemporaryDirectory(prefix="mypy-differential-") as temporary:
        temporary_root = Path(temporary)
        base_root = temporary_root / "base"
        _extract_base_tree(repository_root, base_sha, base_root)
        config_file = _base_config(base_root, temporary_root)

        base_output = run_mypy(
            base_root,
            config_file=config_file,
            report=args.base_report,
        )
        head_output = run_mypy(
            head_root,
            config_file=config_file,
            report=args.report,
        )

        new_errors, resolved_errors = compare_report_outputs(
            base_output,
            head_output,
            base_root=base_root,
            head_root=head_root,
        )
        base_errors = parse_mypy_errors(base_output, root=base_root)
        head_errors = parse_mypy_errors(head_output, root=head_root)
        summary = {
            "schema_version": "2",
            "mode": "differential",
            "valid": not new_errors,
            "base_sha": base_sha,
            "base_error_count": sum(base_errors.values()),
            "head_error_count": sum(head_errors.values()),
            "new_error_count": sum(new_errors.values()),
            "resolved_error_count": sum(resolved_errors.values()),
            "new_errors": _counter_rows(new_errors),
            "resolved_errors": _counter_rows(resolved_errors),
        }
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 1 if new_errors else 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.record_from_report is not None:
            return _record(args)
        if args.base_sha is not None:
            return _differential(args)
        return _check(args)
    except (MypyInfrastructureError, OSError, ValueError) as exc:
        print(f"mypy baseline gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
