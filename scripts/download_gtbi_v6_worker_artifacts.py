"""Download an exact GTBI V6 worker inventory without the action's 300-artifact cap."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable


DEFAULT_PREFIX = "gtbi-v6-worker-"


def _validate_artifact_name(name: str, *, prefix: str) -> None:
    if (
        not name.startswith(prefix)
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or ".." in name
    ):
        raise ValueError(f"unsafe or unrelated artifact name: {name}")


def load_artifact_names(path: Path, *, prefix: str = DEFAULT_PREFIX) -> list[str]:
    names = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names or len(names) != len(set(names)):
        raise ValueError("artifact name inventory must be non-empty and unique")
    for name in names:
        _validate_artifact_name(name, prefix=prefix)
    return sorted(names)


def load_artifact_inventory(path: Path, *, prefix: str = DEFAULT_PREFIX) -> dict[str, int]:
    inventory: dict[str, int] = {}
    seen_ids: set[int] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 2:
            raise ValueError(f"invalid artifact inventory row {line_number}")
        try:
            artifact_id = int(fields[0])
        except ValueError as error:
            raise ValueError(f"invalid artifact ID at row {line_number}") from error
        name = fields[1].strip()
        _validate_artifact_name(name, prefix=prefix)
        if artifact_id <= 0 or artifact_id in seen_ids or name in inventory:
            raise ValueError("artifact inventory IDs and names must be positive and unique")
        seen_ids.add(artifact_id)
        inventory[name] = artifact_id
    if not inventory:
        raise ValueError("artifact inventory must be non-empty")
    return dict(sorted(inventory.items()))


def download_one(
    *,
    repo: str,
    run_id: str,
    artifact_name: str,
    output_root: Path,
    retries: int,
    artifact_id: int | None = None,
) -> None:
    root = Path(output_root).resolve()
    target = (root / artifact_name).resolve()
    if target.parent != root:
        raise ValueError(f"artifact target escapes output root: {artifact_name}")
    errors: list[str] = []
    for attempt in range(1, int(retries) + 1):
        shutil.rmtree(target, ignore_errors=True)
        archive = root / f".artifact-{artifact_id or artifact_name}.zip"
        archive.unlink(missing_ok=True)
        if artifact_id is None:
            completed = subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    str(repo),
                    "--name",
                    artifact_name,
                    "--dir",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            stderr = str(completed.stderr or "")
        else:
            with archive.open("wb") as output:
                completed = subprocess.run(
                    [
                        "gh",
                        "api",
                        f"repos/{repo}/actions/artifacts/{int(artifact_id)}/zip",
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=900,
                    check=False,
                )
            stderr = bytes(completed.stderr or b"").decode("utf-8", errors="replace")
            if completed.returncode == 0:
                try:
                    with zipfile.ZipFile(archive) as zipped:
                        members = zipped.infolist()
                        if not members:
                            raise ValueError("artifact ZIP is empty")
                        target.mkdir(parents=True, exist_ok=True)
                        for member in members:
                            resolved = (target / member.filename).resolve()
                            if target != resolved and target not in resolved.parents:
                                raise ValueError("artifact ZIP contains an unsafe path")
                        zipped.extractall(target)
                except (OSError, ValueError, zipfile.BadZipFile) as error:
                    stderr = f"{stderr} invalid archive: {error}"
                    completed = subprocess.CompletedProcess(completed.args, 1, stderr=stderr)
            archive.unlink(missing_ok=True)
        if completed.returncode == 0 and (target / "worker_summary.json").is_file():
            return
        errors.append(
            f"attempt={attempt} returncode={completed.returncode} "
            f"stderr={stderr.strip()[-500:]}"
        )
        if attempt < int(retries):
            delay = min(180, 30 * (2 ** (attempt - 1))) if "secondary rate limit" in stderr.lower() else attempt * 5
            time.sleep(float(delay))
    raise RuntimeError(f"failed to download {artifact_name}: {'; '.join(errors)}")


def download_worker_artifacts(
    *,
    repo: str,
    run_id: str,
    artifact_names: Iterable[str],
    output_root: Path,
    max_workers: int = 24,
    retries: int = 3,
    artifact_ids: dict[str, int] | None = None,
) -> dict[str, int | str]:
    names = list(artifact_names)
    if not names or len(names) != len(set(names)):
        raise ValueError("artifact_names must be non-empty and unique")
    if artifact_ids is not None and set(artifact_ids) != set(names):
        raise ValueError("artifact_ids must cover exactly artifact_names")
    root = Path(output_root)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"output root is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    worker_count = max(1, min(int(max_workers), 32, len(names)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gtbi-artifact") as executor:
        futures = [
            executor.submit(
                download_one,
                repo=repo,
                run_id=str(run_id),
                artifact_name=name,
                output_root=root,
                retries=int(retries),
                artifact_id=None if artifact_ids is None else int(artifact_ids[name]),
            )
            for name in names
        ]
        for future in futures:
            future.result()
    missing = [name for name in names if not (root / name / "worker_summary.json").is_file()]
    if missing:
        raise RuntimeError(f"download completed with missing worker artifacts: {missing}")
    return {
        "repo": str(repo),
        "run_id": str(run_id),
        "requested_count": len(names),
        "downloaded_count": len(names),
        "parallel_downloads": worker_count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--names-file", type=Path)
    source.add_argument("--inventory-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--max-workers", type=int, default=24)
    parser.add_argument("--retries", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact_ids = None
    if args.inventory_file is not None:
        artifact_ids = load_artifact_inventory(args.inventory_file, prefix=args.prefix)
        names = list(artifact_ids)
    else:
        names = load_artifact_names(args.names_file, prefix=args.prefix)
    if args.expected_count is not None and len(names) != int(args.expected_count):
        raise SystemExit(
            f"artifact inventory count {len(names)} differs from expected {args.expected_count}"
        )
    result = download_worker_artifacts(
        repo=args.repo,
        run_id=args.run_id,
        artifact_names=names,
        output_root=args.output_dir,
        max_workers=args.max_workers,
        retries=args.retries,
        artifact_ids=artifact_ids,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
