"""Download an exact GTBI V6 worker inventory without the action's 300-artifact cap."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable


DEFAULT_PREFIX = "gtbi-v6-worker-"


def load_artifact_names(path: Path, *, prefix: str = DEFAULT_PREFIX) -> list[str]:
    names = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names or len(names) != len(set(names)):
        raise ValueError("artifact name inventory must be non-empty and unique")
    for name in names:
        if (
            not name.startswith(prefix)
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or ".." in name
        ):
            raise ValueError(f"unsafe or unrelated artifact name: {name}")
    return sorted(names)


def download_one(
    *,
    repo: str,
    run_id: str,
    artifact_name: str,
    output_root: Path,
    retries: int,
) -> None:
    root = Path(output_root).resolve()
    target = (root / artifact_name).resolve()
    if target.parent != root:
        raise ValueError(f"artifact target escapes output root: {artifact_name}")
    errors: list[str] = []
    for attempt in range(1, int(retries) + 1):
        shutil.rmtree(target, ignore_errors=True)
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
        if completed.returncode == 0 and (target / "worker_summary.json").is_file():
            return
        errors.append(
            f"attempt={attempt} returncode={completed.returncode} "
            f"stderr={completed.stderr.strip()[-500:]}"
        )
        if attempt < int(retries):
            time.sleep(float(attempt * 2))
    raise RuntimeError(f"failed to download {artifact_name}: {'; '.join(errors)}")


def download_worker_artifacts(
    *,
    repo: str,
    run_id: str,
    artifact_names: Iterable[str],
    output_root: Path,
    max_workers: int = 24,
    retries: int = 3,
) -> dict[str, int | str]:
    names = list(artifact_names)
    if not names or len(names) != len(set(names)):
        raise ValueError("artifact_names must be non-empty and unique")
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
    parser.add_argument("--names-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--max-workers", type=int, default=24)
    parser.add_argument("--retries", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
