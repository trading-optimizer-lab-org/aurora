"""Assemble only the exact prepared-input artifacts selected for one worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assemble_runtime_fragments(
    fragment_root: Path,
    output_dir: Path,
    *,
    artifact_names: tuple[str, ...],
    prepared_input_identity_sha256: str,
    expected_artifact_manifest_sha256: str,
) -> dict[str, object]:
    """Copy a closed artifact set and reject paths, links, and conflicts."""

    if (
        not artifact_names
        or artifact_names != tuple(sorted(set(artifact_names)))
        or any(Path(name).name != name for name in artifact_names)
    ):
        raise ValueError("RUNTIME_FRAGMENT_ARTIFACT_SET_INVALID")
    identity = {
        "schema_version": "1",
        "artifacts": artifact_names,
        "prepared_input_identity_sha256": prepared_input_identity_sha256,
    }
    if canonical_sha256(identity) != expected_artifact_manifest_sha256:
        raise ValueError("RUNTIME_FRAGMENT_ARTIFACT_MANIFEST_INVALID")
    source_root = Path(fragment_root).resolve(strict=True)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("RUNTIME_FRAGMENT_OUTPUT_MUST_START_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, tuple[str, int]] = {}
    for artifact_name in artifact_names:
        artifact_root = source_root / artifact_name
        if not artifact_root.is_dir() or artifact_root.is_symlink():
            raise ValueError("RUNTIME_FRAGMENT_ARTIFACT_MISSING")
        files = sorted(
            (path for path in artifact_root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(artifact_root).as_posix(),
        )
        if not files:
            raise ValueError("RUNTIME_FRAGMENT_ARTIFACT_EMPTY")
        for source in files:
            if source.is_symlink():
                raise ValueError("RUNTIME_FRAGMENT_SYMLINK_FORBIDDEN")
            relative = source.relative_to(artifact_root)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("RUNTIME_FRAGMENT_PATH_INVALID")
            digest = _sha256(source)
            size = source.stat().st_size
            relative_text = relative.as_posix()
            existing = copied.get(relative_text)
            if existing is not None:
                if existing != (digest, size):
                    raise ValueError("RUNTIME_FRAGMENT_FILE_CONFLICT")
                continue
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.stat().st_size != size or _sha256(target) != digest:
                raise ValueError("RUNTIME_FRAGMENT_COPY_INVALID")
            copied[relative_text] = (digest, size)
    receipt_identity = {
        **identity,
        "file_count": len(copied),
        "files": tuple(
            {
                "path": path,
                "sha256": digest,
                "size_bytes": size,
            }
            for path, (digest, size) in sorted(copied.items())
        ),
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt = {
        **receipt_identity,
        "receipt_sha256": canonical_sha256(receipt_identity),
    }
    (output.parent / f"{output.name}-assembly-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fragment-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact-list-file", type=Path, required=True)
    parser.add_argument("--prepared-input-identity-sha256", required=True)
    parser.add_argument("--expected-artifact-manifest-sha256", required=True)
    args = parser.parse_args()
    artifact_names = tuple(
        sorted(
            line.strip()
            for line in args.artifact_list_file.read_text("utf-8").splitlines()
            if line.strip()
        )
    )
    receipt = assemble_runtime_fragments(
        args.fragment_root,
        args.output_dir,
        artifact_names=artifact_names,
        prepared_input_identity_sha256=args.prepared_input_identity_sha256,
        expected_artifact_manifest_sha256=(
            args.expected_artifact_manifest_sha256
        ),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
