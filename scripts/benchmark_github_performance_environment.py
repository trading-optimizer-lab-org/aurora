"""Benchmark locked network setup against the exact offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_benchmark_module():
    module_path = (
        ROOT
        / "infra"
        / "github_performance"
        / "environment_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_aurora_environment_benchmark",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _installed_identity(
    python: Path,
    *,
    env: dict[str, str],
    lock_sha256: str,
    aurora_wheel_sha256: str,
) -> tuple[str, str]:
    command = [
        str(python),
        "-c",
        (
            "import importlib.metadata,json,platform;"
            "packages=sorted("
            "(dist.metadata['Name'].lower(),dist.version) "
            "for dist in importlib.metadata.distributions());"
            "print(json.dumps({"
            "'implementation':platform.python_implementation(),"
            "'python_version':platform.python_version(),"
            "'packages':packages},"
            "sort_keys=True,separators=(',',':')))"
        ),
    ]
    completed = _run(command, env=env, capture=True)
    installed = json.loads(completed.stdout)
    packages_sha256 = _canonical_sha256(installed["packages"])
    environment_sha256 = _canonical_sha256(
        {
            "implementation": installed["implementation"],
            "python_version": installed["python_version"],
            "packages_sha256": packages_sha256,
            "dependency_lock_sha256": lock_sha256,
            "aurora_wheel_sha256": aurora_wheel_sha256,
        }
    )
    _run(
        [
            str(python),
            "-c",
            "import aurora,numpy,pandas,pyarrow;print(aurora.__version__)",
        ],
        env=env,
    )
    return environment_sha256, packages_sha256


def _install_sample(
    *,
    benchmark,
    mode: str,
    temperature: str,
    repetition: int,
    root: Path,
    lock: Path,
    wheelhouse: Path,
    aurora_wheel: Path,
    pip_cache: Path,
    lock_sha256: str,
    aurora_wheel_sha256: str,
) -> Any:
    sample_root = root / f"{mode}-{temperature}-{repetition}"
    if sample_root.exists():
        shutil.rmtree(sample_root)
    env = dict(os.environ)
    env.update(
        {
            "PIP_CACHE_DIR": str(pip_cache),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONHASHSEED": "0",
        }
    )
    started = time.perf_counter()
    _run([sys.executable, "-m", "venv", str(sample_root)], env=env)
    python = _venv_python(sample_root)
    install = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--require-hashes",
    ]
    if mode == "wheelhouse":
        install.extend(
            [
                "--no-index",
                "--no-deps",
                "--find-links",
                str(wheelhouse),
            ]
        )
    elif mode == "locked_network":
        install.append("--only-binary=:all:")
    else:
        raise ValueError(f"unsupported setup mode: {mode}")
    install.extend(["--requirement", str(lock)])
    _run(install, env=env)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            "--no-compile",
            str(aurora_wheel),
        ],
        env=env,
    )
    environment_sha256, packages_sha256 = _installed_identity(
        python,
        env=env,
        lock_sha256=lock_sha256,
        aurora_wheel_sha256=aurora_wheel_sha256,
    )
    seconds = time.perf_counter() - started
    shutil.rmtree(sample_root)
    return benchmark.EnvironmentSetupSample(
        mode=mode,
        temperature=temperature,
        repetition=repetition,
        seconds=seconds,
        environment_sha256=environment_sha256,
        installed_packages_sha256=packages_sha256,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements-lock", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--warm-repetitions", type=int, default=3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.warm_repetitions < 2:
        raise ValueError("warm-repetitions must be at least 2")
    lock = args.requirements_lock.resolve()
    wheelhouse = args.wheelhouse.resolve()
    aurora_wheels = sorted(wheelhouse.glob("aurora-*.whl"))
    if len(aurora_wheels) != 1:
        raise RuntimeError(
            "wheelhouse must contain exactly one Aurora wheel"
        )
    aurora_wheel = aurora_wheels[0]
    benchmark = _load_benchmark_module()
    baseline: list[Any] = []
    optimized: list[Any] = []
    with tempfile.TemporaryDirectory(
        prefix="aurora-environment-benchmark-"
    ) as temporary:
        root = Path(temporary)
        pip_cache = root / "pip-cache"
        baseline.append(
            _install_sample(
                benchmark=benchmark,
                mode="locked_network",
                temperature="cold",
                repetition=0,
                root=root,
                lock=lock,
                wheelhouse=wheelhouse,
                aurora_wheel=aurora_wheel,
                pip_cache=pip_cache,
                lock_sha256=_sha256_file(lock),
                aurora_wheel_sha256=_sha256_file(aurora_wheel),
            )
        )
        optimized.append(
            _install_sample(
                benchmark=benchmark,
                mode="wheelhouse",
                temperature="cold",
                repetition=0,
                root=root,
                lock=lock,
                wheelhouse=wheelhouse,
                aurora_wheel=aurora_wheel,
                pip_cache=pip_cache,
                lock_sha256=_sha256_file(lock),
                aurora_wheel_sha256=_sha256_file(aurora_wheel),
            )
        )
        for repetition in range(1, args.warm_repetitions + 1):
            order: tuple[tuple[str, list[Any]], ...] = (
                ("wheelhouse", optimized),
                ("locked_network", baseline),
            )
            if repetition % 2 == 0:
                order = tuple(reversed(order))
            for mode, destination in order:
                destination.append(
                    _install_sample(
                        benchmark=benchmark,
                        mode=mode,
                        temperature="warm",
                        repetition=repetition,
                        root=root,
                        lock=lock,
                        wheelhouse=wheelhouse,
                        aurora_wheel=aurora_wheel,
                        pip_cache=pip_cache,
                        lock_sha256=_sha256_file(lock),
                        aurora_wheel_sha256=_sha256_file(aurora_wheel),
                    )
                )
    report = benchmark.evaluate_environment_setup_samples(
        baseline,
        optimized,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            report.as_dict(),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report.status,
                "dependency_environment_reproducible": (
                    report.dependency_environment_reproducible
                ),
                "fast_path_selected": report.fast_path_selected,
                "cold_speedup": report.cold_speedup,
                "warm_speedup": report.warm_speedup,
                "output": str(args.output),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
