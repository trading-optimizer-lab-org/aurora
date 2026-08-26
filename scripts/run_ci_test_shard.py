"""Run one deterministic, size-balanced shard of the ordinary pytest suite."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


EXCLUDED = {"tests/test_config.py", "tests/test_property.py"}


def discover_tests(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("test_*.py"))
        if path.as_posix() not in EXCLUDED
    ]


def balanced_shards(paths: list[Path], count: int) -> list[list[Path]]:
    if count < 1:
        raise ValueError("shard count must be positive")
    shards: list[list[Path]] = [[] for _ in range(count)]
    weights = [0] * count
    ordered = sorted(paths, key=lambda path: (-path.stat().st_size, path.as_posix()))
    for path in ordered:
        index = min(range(count), key=lambda item: (weights[item], item))
        shards[index].append(path)
        weights[index] += path.stat().st_size
    return [sorted(shard) for shard in shards]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    args = parser.parse_args(argv)
    tests = balanced_shards(discover_tests(Path("tests")), args.shard_count)
    if args.shard_index < 0 or args.shard_index >= len(tests):
        parser.error("shard index is outside the configured shard count")
    selected = tests[args.shard_index]
    if not selected:
        parser.error("selected shard is empty")
    command = [
        sys.executable,
        "-m",
        "pytest",
        *(path.as_posix() for path in selected),
        "-m",
        "not slow and not integration",
        "--tb=short",
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
