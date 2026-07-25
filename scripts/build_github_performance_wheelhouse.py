"""Build or verify the immutable Aurora GitHub performance wheelhouse."""

from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_environment_module():
    module_path = (
        ROOT / "infra" / "github_performance" / "environment.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_aurora_github_environment",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load environment module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_environment = _load_environment_module()
build_wheelhouse_manifest = _environment.build_wheelhouse_manifest
current_target = _environment.current_target
load_wheelhouse_manifest = _environment.load_wheelhouse_manifest
parse_hashed_lock = _environment.parse_hashed_lock
verify_wheelhouse = _environment.verify_wheelhouse
write_dependency_lock_manifest = _environment.write_dependency_lock_manifest
write_wheelhouse_manifest = _environment.write_wheelhouse_manifest


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
    )


def _build(args: argparse.Namespace) -> int:
    lock_path = args.requirements_lock.resolve()
    wheelhouse = args.wheelhouse.resolve()
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)

    dependency_lock = parse_hashed_lock(lock_path)
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--require-hashes",
            "--dest",
            str(wheelhouse),
            "--requirement",
            str(lock_path),
        ]
    )

    with tempfile.TemporaryDirectory(prefix="aurora-wheel-build-") as temp:
        build_venv = Path(temp) / "venv"
        _run([sys.executable, "-m", "venv", str(build_venv)])
        build_python = (
            build_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        _run(
            [
                str(build_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "--require-hashes",
                "--requirement",
                str(lock_path),
            ]
        )
        build_env = dict(os.environ)
        build_env["SOURCE_DATE_EPOCH"] = str(args.source_date_epoch)
        _run(
            [
                str(build_python),
                "-m",
                "pip",
                "wheel",
                ".",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheelhouse),
            ],
            env=build_env,
        )

    python_version, runner_os, runner_arch = current_target()
    manifest = build_wheelhouse_manifest(
        wheelhouse=wheelhouse,
        dependency_lock=dependency_lock,
        python_version=python_version,
        runner_os=runner_os,
        runner_arch=runner_arch,
        code_sha=args.code_sha,
    )
    write_dependency_lock_manifest(
        wheelhouse / "dependency_lock_manifest.json",
        dependency_lock,
    )
    write_wheelhouse_manifest(
        wheelhouse / "wheelhouse_manifest.json",
        manifest,
    )
    (wheelhouse / "build_provenance.txt").write_text(
        "\n".join(
            (
                f"code_sha={args.code_sha}",
                f"source_date_epoch={args.source_date_epoch}",
                f"python_version={python_version}",
                f"runner_os={runner_os}",
                f"runner_arch={runner_arch}",
                f"builder_pip_version={importlib.metadata.version('pip')}",
                f"dependency_lock_sha256={dependency_lock.lock_sha256}",
                f"wheelhouse_sha256={manifest.wheelhouse_sha256}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    dependency_lock = parse_hashed_lock(args.requirements_lock)
    manifest = load_wheelhouse_manifest(
        args.wheelhouse / "wheelhouse_manifest.json"
    )
    python_version, runner_os, runner_arch = current_target()
    verification = verify_wheelhouse(
        wheelhouse=args.wheelhouse,
        dependency_lock=dependency_lock,
        manifest=manifest,
        python_version=python_version,
        runner_os=runner_os,
        runner_arch=runner_arch,
    )
    print(
        f"verified wheelhouse={verification.wheelhouse_sha256} "
        f"wheels={verification.wheel_count} "
        f"dependencies={verification.dependency_count}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--requirements-lock", type=Path, required=True)
    build.add_argument("--wheelhouse", type=Path, required=True)
    build.add_argument("--code-sha", required=True)
    build.add_argument("--source-date-epoch", type=int, required=True)
    build.set_defaults(handler=_build)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--requirements-lock", type=Path, required=True)
    verify.add_argument("--wheelhouse", type=Path, required=True)
    verify.set_defaults(handler=_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
