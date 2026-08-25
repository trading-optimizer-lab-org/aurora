from __future__ import annotations

import json
import subprocess
import tarfile
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import BinaryIO, Literal, cast

import pytest

import scripts.check_mypy_baseline as baseline


def test_extract_base_tree_uses_tar_data_filter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_filters: list[object] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output = cast(BinaryIO, kwargs["stdout"])
        with tarfile.open(fileobj=output, mode="w"):
            pass
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    original_extractall = tarfile.TarFile.extractall

    def guarded_extractall(
        archive: tarfile.TarFile,
        path: str | Path = ".",
        members: Iterable[tarfile.TarInfo] | None = None,
        *,
        numeric_owner: bool = False,
        filter: Literal["fully_trusted", "tar", "data"]
        | Callable[[tarfile.TarInfo, str], tarfile.TarInfo | None]
        | None = None,
    ) -> None:
        observed_filters.append(filter)
        original_extractall(
            archive,
            path,
            members=members,
            numeric_owner=numeric_owner,
            filter=filter,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(tarfile.TarFile, "extractall", guarded_extractall)

    baseline._extract_base_tree(tmp_path, "a" * 40, tmp_path / "base")

    assert observed_filters == ["data"]


def test_parse_mypy_errors_ignores_line_numbers() -> None:
    output = "\n".join(
        [
            "core/example.py:10: error: Bad value  [assignment]",
            "core/example.py:99: error: Bad value  [assignment]",
            "Found 2 errors in 1 file",
        ]
    )

    assert baseline.parse_mypy_errors(output) == Counter(
        {("core/example.py", "assignment", "Bad value"): 2}
    )


def test_parse_mypy_errors_accepts_file_error_without_position() -> None:
    output = "core/example.py: error: Bad module value [assignment]\n"

    assert baseline.parse_mypy_errors(output) == Counter(
        {("core/example.py", "assignment", "Bad module value"): 1}
    )


def test_parse_mypy_errors_normalizes_windows_and_linux_roots() -> None:
    output = "\n".join(
        [
            r"C:\build\base\core\example.py:10: error: Bad value  [assignment]",
            "/tmp/head/core/other.py:20: error: New value  [arg-type]",
        ]
    )

    assert baseline.parse_mypy_errors(output, root=r"C:\build\base") == Counter(
        {("core/example.py", "assignment", "Bad value"): 1,
         ("/tmp/head/core/other.py", "arg-type", "New value"): 1}
    )


def test_differential_delta_is_empty_when_reports_match() -> None:
    base = "C:\\tmp\\base\\core\\example.py:10: error: Bad value  [assignment]\n"
    head = "/work/head/core/example.py:99: error: Bad value  [assignment]\n"

    new_errors, resolved_errors = baseline.compare_report_outputs(
        base,
        head,
        base_root=r"C:\\tmp\\base",
        head_root="/work/head",
    )

    assert new_errors == Counter()
    assert resolved_errors == Counter()


def test_differential_delta_reports_new_and_resolved_errors() -> None:
    base = "old.py:10: error: Old debt  [arg-type]\n"
    head = "new.py:20: error: New regression  [assignment]\n"

    new_errors, resolved_errors = baseline.compare_report_outputs(base, head)

    assert new_errors == Counter(
        {("new.py", "assignment", "New regression"): 1}
    )
    assert resolved_errors == Counter(
        {("old.py", "arg-type", "Old debt"): 1}
    )


def test_differential_delta_detects_file_error_without_position() -> None:
    head = "new.py: error: New module regression [assignment]\n"

    new_errors, resolved_errors = baseline.compare_report_outputs("", head)

    assert new_errors == Counter(
        {("new.py", "assignment", "New module regression"): 1}
    )
    assert resolved_errors == Counter()


def test_differential_delta_preserves_error_multiplicity() -> None:
    base = "\n".join(
        [
            "core/example.py:10: error: Bad value  [assignment]",
            "core/example.py:11: error: Bad value  [assignment]",
        ]
    )
    head = "core/example.py:99: error: Bad value  [assignment]\n"

    new_errors, resolved_errors = baseline.compare_report_outputs(base, head)

    assert new_errors == Counter()
    assert resolved_errors == Counter(
        {("core/example.py", "assignment", "Bad value"): 1}
    )


def test_differential_delta_handles_paths_present_in_only_one_tree() -> None:
    base = "removed.py:10: error: Old debt  [arg-type]\n"
    head = "added.py:20: error: New regression  [assignment]\n"

    new_errors, resolved_errors = baseline.compare_report_outputs(base, head)

    assert ("added.py", "assignment", "New regression") in new_errors
    assert ("removed.py", "arg-type", "Old debt") in resolved_errors


@pytest.mark.parametrize(
    "sha",
    [None, "", "f" * 39, "g" * 40, "0" * 40],
)
def test_validate_base_sha_rejects_invalid_or_absent_values(sha: str | None) -> None:
    with pytest.raises(ValueError, match="40 hexadecimal"):
        baseline.validate_base_sha(sha)


def test_validate_base_sha_accepts_hex_case_insensitively() -> None:
    assert baseline.validate_base_sha("A" * 40) == "a" * 40


def test_run_mypy_rejects_infrastructure_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=2,
            stdout="mypy internal failure\n",
            stderr="configuration failure\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="exit code 2"):
        baseline.run_mypy(tmp_path, config_file=None)


def test_run_mypy_accepts_mypy_error_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="example.py: error: Bad value [assignment]\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert baseline.run_mypy(tmp_path, config_file=None).startswith("example.py")


def test_run_mypy_rejects_unparsed_error_diagnostic_on_exit_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=(
                "parsed.py: error: Known error [assignment]\n"
                "example.py: error: Diagnostic without error code\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="unparsed mypy error diagnostic"):
        baseline.run_mypy(tmp_path, config_file=None)


def test_main_rejects_invalid_differential_sha(capsys: pytest.CaptureFixture[str]) -> None:
    assert baseline.main(["--base-sha", "not-a-sha"]) == 2
    assert "40 hexadecimal" in capsys.readouterr().err


def test_compare_mypy_errors_rejects_only_new_fingerprints() -> None:
    allowed = Counter({("old.py", "arg-type", "Old debt"): 2})
    current = Counter(
        {
            ("old.py", "arg-type", "Old debt"): 1,
            ("new.py", "assignment", "New regression"): 1,
        }
    )

    new_errors, resolved_errors = baseline.compare_errors(current, allowed)

    assert new_errors == Counter(
        {("new.py", "assignment", "New regression"): 1}
    )
    assert resolved_errors == Counter(
        {("old.py", "arg-type", "Old debt"): 1}
    )


def test_baseline_round_trip_and_duplicate_rejection(tmp_path: Path) -> None:
    errors = Counter({("old.py", "arg-type", "Old debt"): 2})
    payload = baseline.baseline_payload(
        errors,
        run_id=123,
        commit_sha="a" * 40,
    )
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    loaded_payload, loaded_errors = baseline.load_baseline(path)
    assert loaded_payload["source"]["error_count"] == 2
    assert loaded_errors == errors

    payload["errors"].append(dict(payload["errors"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        baseline.load_baseline(path)
