"""Reproducible dependency and wheelhouse contracts for GitHub runners."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


_SHA256_RE = re.compile(r"--hash=sha256:([0-9a-fA-F]{64})")
_EXACT_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[A-Za-z0-9_.+!-]+)$"
)


class EnvironmentContractError(ValueError):
    """Raised when a dependency or wheelhouse contract is not exact."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class RequirementPin:
    normalized_name: str
    version: str
    sha256_hashes: tuple[str, ...]


@dataclass(frozen=True)
class DependencyLockManifest:
    schema_version: str
    lock_sha256: str
    requirement_count: int
    requirements: tuple[RequirementPin, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "DependencyLockManifest":
        requirements = tuple(
            RequirementPin(
                normalized_name=str(item["normalized_name"]),
                version=str(item["version"]),
                sha256_hashes=tuple(item["sha256_hashes"]),
            )
            for item in payload["requirements"]
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            lock_sha256=str(payload["lock_sha256"]),
            requirement_count=int(payload["requirement_count"]),
            requirements=requirements,
        )


@dataclass(frozen=True)
class WheelRecord:
    filename: str
    normalized_name: str
    version: str
    tags: tuple[str, ...]
    sha256: str
    size_bytes: int
    is_aurora: bool


@dataclass(frozen=True)
class WheelhouseManifest:
    schema_version: str
    code_sha: str
    python_version: str
    runner_os: str
    runner_arch: str
    dependency_lock_sha256: str
    wheel_count: int
    aurora_wheel_count: int
    wheelhouse_sha256: str
    wheels: tuple[WheelRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WheelhouseManifest":
        wheels = tuple(
            WheelRecord(
                filename=str(item["filename"]),
                normalized_name=str(item["normalized_name"]),
                version=str(item["version"]),
                tags=tuple(item["tags"]),
                sha256=str(item["sha256"]),
                size_bytes=int(item["size_bytes"]),
                is_aurora=bool(item["is_aurora"]),
            )
            for item in payload["wheels"]
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            code_sha=str(payload["code_sha"]),
            python_version=str(payload["python_version"]),
            runner_os=str(payload["runner_os"]),
            runner_arch=str(payload["runner_arch"]),
            dependency_lock_sha256=str(
                payload["dependency_lock_sha256"]
            ),
            wheel_count=int(payload["wheel_count"]),
            aurora_wheel_count=int(payload["aurora_wheel_count"]),
            wheelhouse_sha256=str(payload["wheelhouse_sha256"]),
            wheels=wheels,
        )


@dataclass(frozen=True)
class WheelhouseVerification:
    schema_version: str
    valid: bool
    dependency_count: int
    wheel_count: int
    wheelhouse_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _logical_lock_rows(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rows: list[tuple[str, tuple[str, ...]]] = []
    requirement: str | None = None
    hashes: list[str] = []

    def flush() -> None:
        nonlocal requirement, hashes
        if requirement is not None:
            rows.append((requirement, tuple(sorted(set(hashes)))))
        requirement = None
        hashes = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash="):
            hashes.extend(match.lower() for match in _SHA256_RE.findall(stripped))
            continue
        if stripped.startswith("--"):
            continue
        if raw_line[:1].isspace():
            continue
        flush()
        requirement = stripped.removesuffix("\\").strip()
        hashes.extend(match.lower() for match in _SHA256_RE.findall(stripped))
        requirement = _SHA256_RE.sub("", requirement).strip()
        requirement = requirement.removesuffix("\\").strip()
    flush()
    return tuple(rows)


def parse_hashed_lock(path: Path) -> DependencyLockManifest:
    """Parse a pip-compile lock and reject any non-exact requirement."""

    path = Path(path)
    rows = _logical_lock_rows(path.read_text(encoding="utf-8"))
    pins: list[RequirementPin] = []
    seen: set[str] = set()
    for requirement, hashes in rows:
        match = _EXACT_PIN_RE.fullmatch(requirement)
        if match is None:
            raise EnvironmentContractError(
                f"dependency must use one exact pin: {requirement!r}"
            )
        name = canonicalize_name(match.group("name"))
        if name in seen:
            raise EnvironmentContractError(
                f"duplicate exact pin for dependency {name!r}"
            )
        if not hashes:
            raise EnvironmentContractError(
                f"dependency {name!r} has no sha256 hash"
            )
        seen.add(name)
        pins.append(
            RequirementPin(
                normalized_name=name,
                version=match.group("version"),
                sha256_hashes=hashes,
            )
        )
    if not pins:
        raise EnvironmentContractError("dependency lock has no exact pins")
    pins.sort(key=lambda item: item.normalized_name)
    return DependencyLockManifest(
        schema_version="1",
        lock_sha256=_sha256_file(path),
        requirement_count=len(pins),
        requirements=tuple(pins),
    )


def _wheel_records(wheelhouse: Path) -> tuple[WheelRecord, ...]:
    records: list[WheelRecord] = []
    for path in sorted(Path(wheelhouse).glob("*.whl")):
        try:
            name, version, _build, tags = parse_wheel_filename(path.name)
        except Exception as exc:
            raise EnvironmentContractError(
                f"invalid wheel filename {path.name!r}"
            ) from exc
        normalized_name = canonicalize_name(name)
        records.append(
            WheelRecord(
                filename=path.name,
                normalized_name=normalized_name,
                version=str(version),
                tags=tuple(sorted(str(tag) for tag in tags)),
                sha256=_sha256_file(path),
                size_bytes=path.stat().st_size,
                is_aurora=normalized_name == "aurora",
            )
        )
    return tuple(records)


def _wheelhouse_identity(
    *,
    dependency_lock_sha256: str,
    code_sha: str,
    python_version: str,
    runner_os: str,
    runner_arch: str,
    wheels: Sequence[WheelRecord],
) -> str:
    return _canonical_json_sha256(
        {
            "dependency_lock_sha256": dependency_lock_sha256,
            "code_sha": code_sha,
            "python_version": python_version,
            "runner_os": runner_os,
            "runner_arch": runner_arch,
            "wheels": [
                {
                    "filename": item.filename,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in wheels
            ],
        }
    )


def _validate_exact_coverage(
    *,
    dependency_lock: DependencyLockManifest,
    wheels: Sequence[WheelRecord],
) -> None:
    locked = {
        item.normalized_name: item for item in dependency_lock.requirements
    }
    by_name: dict[str, list[WheelRecord]] = {}
    for wheel in wheels:
        by_name.setdefault(wheel.normalized_name, []).append(wheel)
    missing = sorted(set(locked).difference(by_name))
    if missing:
        raise EnvironmentContractError(
            "wheelhouse has missing locked wheels: " + ", ".join(missing)
        )
    extra = sorted(set(by_name).difference(set(locked).union({"aurora"})))
    if extra:
        raise EnvironmentContractError(
            "wheelhouse has extra wheels: " + ", ".join(extra)
        )
    for name, pin in locked.items():
        candidates = by_name[name]
        if len(candidates) != 1:
            raise EnvironmentContractError(
                f"locked dependency {name!r} has {len(candidates)} wheels"
            )
        wheel = candidates[0]
        if wheel.version != pin.version:
            raise EnvironmentContractError(
                f"locked dependency {name!r} version mismatch"
            )
        if wheel.sha256 not in pin.sha256_hashes:
            raise EnvironmentContractError(
                f"locked dependency {name!r} wheel hash mismatch"
            )
    aurora_count = len(by_name.get("aurora", ()))
    if aurora_count != 1:
        raise EnvironmentContractError(
            f"wheelhouse must contain exactly one Aurora wheel, got {aurora_count}"
        )


def build_wheelhouse_manifest(
    *,
    wheelhouse: Path,
    dependency_lock: DependencyLockManifest,
    python_version: str,
    runner_os: str,
    runner_arch: str,
    code_sha: str,
) -> WheelhouseManifest:
    """Hash and validate one complete immutable wheelhouse."""

    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise EnvironmentContractError("code_sha must be an exact Git SHA")
    wheels = _wheel_records(wheelhouse)
    _validate_exact_coverage(
        dependency_lock=dependency_lock,
        wheels=wheels,
    )
    aurora_count = sum(item.is_aurora for item in wheels)
    identity = _wheelhouse_identity(
        dependency_lock_sha256=dependency_lock.lock_sha256,
        code_sha=code_sha,
        python_version=python_version,
        runner_os=runner_os,
        runner_arch=runner_arch,
        wheels=wheels,
    )
    return WheelhouseManifest(
        schema_version="1",
        code_sha=code_sha,
        python_version=python_version,
        runner_os=runner_os,
        runner_arch=runner_arch,
        dependency_lock_sha256=dependency_lock.lock_sha256,
        wheel_count=len(wheels),
        aurora_wheel_count=aurora_count,
        wheelhouse_sha256=identity,
        wheels=wheels,
    )


def verify_wheelhouse(
    *,
    wheelhouse: Path,
    dependency_lock: DependencyLockManifest,
    manifest: WheelhouseManifest,
    python_version: str,
    runner_os: str,
    runner_arch: str,
) -> WheelhouseVerification:
    """Reject any byte, dependency, or target drift in a wheelhouse."""

    expected_target = (
        manifest.python_version,
        manifest.runner_os,
        manifest.runner_arch,
    )
    observed_target = (python_version, runner_os, runner_arch)
    if observed_target != expected_target:
        raise EnvironmentContractError(
            "wheelhouse compatibility target mismatch: "
            f"expected={expected_target!r} observed={observed_target!r}"
        )
    if manifest.dependency_lock_sha256 != dependency_lock.lock_sha256:
        raise EnvironmentContractError(
            "wheelhouse dependency lock hash mismatch"
        )

    expected_files = {item.filename for item in manifest.wheels}
    actual_records = _wheel_records(wheelhouse)
    actual_files = {item.filename for item in actual_records}
    missing = sorted(expected_files.difference(actual_files))
    if missing:
        raise EnvironmentContractError(
            "wheelhouse has missing manifest files: " + ", ".join(missing)
        )
    extra = sorted(actual_files.difference(expected_files))
    if extra:
        raise EnvironmentContractError(
            "wheelhouse has extra manifest files: " + ", ".join(extra)
        )

    actual_by_name = {item.filename: item for item in actual_records}
    for expected in manifest.wheels:
        observed = actual_by_name[expected.filename]
        if observed != expected:
            raise EnvironmentContractError(
                f"wheel {expected.filename!r} differs from manifest"
            )

    _validate_exact_coverage(
        dependency_lock=dependency_lock,
        wheels=actual_records,
    )
    compatible_tags = {str(tag) for tag in sys_tags()}
    incompatible = [
        item.filename
        for item in actual_records
        if not compatible_tags.intersection(item.tags)
    ]
    if incompatible:
        raise EnvironmentContractError(
            "wheelhouse compatibility tags do not match runner: "
            + ", ".join(incompatible)
        )

    identity = _wheelhouse_identity(
        dependency_lock_sha256=dependency_lock.lock_sha256,
        code_sha=manifest.code_sha,
        python_version=python_version,
        runner_os=runner_os,
        runner_arch=runner_arch,
        wheels=actual_records,
    )
    if identity != manifest.wheelhouse_sha256:
        raise EnvironmentContractError(
            "wheelhouse identity differs from manifest"
        )
    return WheelhouseVerification(
        schema_version="1",
        valid=True,
        dependency_count=dependency_lock.requirement_count,
        wheel_count=len(actual_records),
        wheelhouse_sha256=identity,
    )


def write_dependency_lock_manifest(
    path: Path,
    manifest: DependencyLockManifest,
) -> Path:
    return _write_json(path, manifest.to_dict())


def write_wheelhouse_manifest(
    path: Path,
    manifest: WheelhouseManifest,
) -> Path:
    return _write_json(path, manifest.to_dict())


def load_dependency_lock_manifest(path: Path) -> DependencyLockManifest:
    return DependencyLockManifest.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def load_wheelhouse_manifest(path: Path) -> WheelhouseManifest:
    return WheelhouseManifest.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def current_target() -> tuple[str, str, str]:
    return (
        ".".join(platform.python_version_tuple()[:2]),
        platform.system(),
        "X64" if platform.machine().lower() in {"x86_64", "amd64"} else platform.machine(),
    )
