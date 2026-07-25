from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aurora.infra.github_performance.environment import (
    EnvironmentContractError,
    build_wheelhouse_manifest,
    parse_hashed_lock,
    verify_wheelhouse,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_lock(path: Path, rows: list[tuple[str, str, bytes]]) -> Path:
    lines = [
        "# Generated on ubuntu-24.04 with Python 3.12.",
        "--only-binary :all:",
    ]
    for name, version, wheel_bytes in rows:
        lines.extend(
            (
                f"{name}=={version} \\",
                f"    --hash=sha256:{_sha(wheel_bytes)}",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_wheel(
    root: Path,
    *,
    name: str,
    version: str,
    payload: bytes,
) -> Path:
    path = root / f"{name}-{version}-py3-none-any.whl"
    path.write_bytes(payload)
    return path


def test_hashed_lock_requires_exact_transitive_pins_and_hashes(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "numpy>=2\npandas==2.2.3\n",
        encoding="utf-8",
    )

    with pytest.raises(EnvironmentContractError, match="exact pin"):
        parse_hashed_lock(lock)

    lock.write_text("numpy==2.2.6\n", encoding="utf-8")
    with pytest.raises(EnvironmentContractError, match="hash"):
        parse_hashed_lock(lock)


def test_hashed_lock_manifest_is_canonical_and_complete(
    tmp_path: Path,
) -> None:
    numpy_wheel = b"numpy"
    pandas_wheel = b"pandas"
    lock = _write_lock(
        tmp_path / "requirements.lock",
        [
            ("numpy", "2.2.6", numpy_wheel),
            ("pandas", "2.2.3", pandas_wheel),
        ],
    )

    manifest = parse_hashed_lock(lock)

    assert manifest.schema_version == "1"
    assert manifest.requirement_count == 2
    assert [item.normalized_name for item in manifest.requirements] == [
        "numpy",
        "pandas",
    ]
    assert manifest.requirements[0].version == "2.2.6"
    assert manifest.requirements[0].sha256_hashes == (_sha(numpy_wheel),)
    assert len(manifest.lock_sha256) == 64


def test_wheelhouse_manifest_hashes_every_file_and_exactly_one_aurora(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    numpy_payload = b"numpy"
    aurora_payload = b"aurora"
    _write_wheel(
        wheelhouse,
        name="numpy",
        version="2.2.6",
        payload=numpy_payload,
    )
    _write_wheel(
        wheelhouse,
        name="aurora",
        version="1.5.0",
        payload=aurora_payload,
    )
    lock = _write_lock(
        tmp_path / "requirements.lock",
        [("numpy", "2.2.6", numpy_payload)],
    )

    manifest = build_wheelhouse_manifest(
        wheelhouse=wheelhouse,
        dependency_lock=parse_hashed_lock(lock),
        python_version="3.12",
        runner_os="Linux",
        runner_arch="X64",
        code_sha="a" * 40,
    )

    assert manifest.schema_version == "1"
    assert manifest.wheel_count == 2
    assert manifest.aurora_wheel_count == 1
    assert {item.sha256 for item in manifest.wheels} == {
        _sha(numpy_payload),
        _sha(aurora_payload),
    }
    assert len(manifest.wheelhouse_sha256) == 64


def test_wheelhouse_rejects_missing_extra_or_modified_wheels(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    numpy_payload = b"numpy"
    aurora_payload = b"aurora"
    numpy_path = _write_wheel(
        wheelhouse,
        name="numpy",
        version="2.2.6",
        payload=numpy_payload,
    )
    _write_wheel(
        wheelhouse,
        name="aurora",
        version="1.5.0",
        payload=aurora_payload,
    )
    lock = _write_lock(
        tmp_path / "requirements.lock",
        [("numpy", "2.2.6", numpy_payload)],
    )
    dependency_lock = parse_hashed_lock(lock)
    manifest = build_wheelhouse_manifest(
        wheelhouse=wheelhouse,
        dependency_lock=dependency_lock,
        python_version="3.12",
        runner_os="Linux",
        runner_arch="X64",
        code_sha="b" * 40,
    )

    assert verify_wheelhouse(
        wheelhouse=wheelhouse,
        dependency_lock=dependency_lock,
        manifest=manifest,
        python_version="3.12",
        runner_os="Linux",
        runner_arch="X64",
    ).valid

    numpy_path.unlink()
    with pytest.raises(EnvironmentContractError, match="missing"):
        verify_wheelhouse(
            wheelhouse=wheelhouse,
            dependency_lock=dependency_lock,
            manifest=manifest,
            python_version="3.12",
            runner_os="Linux",
            runner_arch="X64",
        )

    _write_wheel(
        wheelhouse,
        name="numpy",
        version="2.2.6",
        payload=numpy_payload,
    )
    _write_wheel(
        wheelhouse,
        name="surprise",
        version="9.9.9",
        payload=b"extra",
    )
    with pytest.raises(EnvironmentContractError, match="extra"):
        verify_wheelhouse(
            wheelhouse=wheelhouse,
            dependency_lock=dependency_lock,
            manifest=manifest,
            python_version="3.12",
            runner_os="Linux",
            runner_arch="X64",
        )


def test_wheelhouse_rejects_python_platform_or_architecture_mismatch(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    numpy_payload = b"numpy"
    _write_wheel(
        wheelhouse,
        name="numpy",
        version="2.2.6",
        payload=numpy_payload,
    )
    _write_wheel(
        wheelhouse,
        name="aurora",
        version="1.5.0",
        payload=b"aurora",
    )
    lock = _write_lock(
        tmp_path / "requirements.lock",
        [("numpy", "2.2.6", numpy_payload)],
    )
    dependency_lock = parse_hashed_lock(lock)
    manifest = build_wheelhouse_manifest(
        wheelhouse=wheelhouse,
        dependency_lock=dependency_lock,
        python_version="3.12",
        runner_os="Linux",
        runner_arch="X64",
        code_sha="c" * 40,
    )

    for kwargs in (
        {"python_version": "3.11", "runner_os": "Linux", "runner_arch": "X64"},
        {"python_version": "3.12", "runner_os": "Windows", "runner_arch": "X64"},
        {"python_version": "3.12", "runner_os": "Linux", "runner_arch": "ARM64"},
    ):
        with pytest.raises(EnvironmentContractError, match="compatibility"):
            verify_wheelhouse(
                wheelhouse=wheelhouse,
                dependency_lock=dependency_lock,
                manifest=manifest,
                **kwargs,
            )
