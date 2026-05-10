"""Wheel smoke test for Aurora releases (R188).

Runs end-to-end:

1. Build the wheel with ``python -m build`` from the repo root.
2. Create a throwaway venv with ``python -m venv``.
3. Install the freshly built wheel into that venv.
4. Run ``python -c "import aurora; print(aurora.__version__)"`` inside the venv.
5. Run ``python -c "from aurora.cli.forge import main; main(['--version'])"``
   inside the venv.

Returns 0 on full success. On any failure, prints the failing step + captured
stderr/stdout and returns a non-zero exit code.

This script is intentionally NOT wired into pytest. A full wheel build is
too slow for the test loop. Run it manually before cutting a release::

    python tools/release_smoke.py

Or, equivalently::

    "C:/Python314/python.exe" tools/release_smoke.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _fail(step: str, code: int, stdout: str, stderr: str) -> int:
    print(f"[release_smoke] FAIL: {step} (exit {code})", file=sys.stderr)
    if stdout:
        print(f"[release_smoke] stdout:\n{stdout}", file=sys.stderr)
    if stderr:
        print(f"[release_smoke] stderr:\n{stderr}", file=sys.stderr)
    return 1


def _venv_python(venv_dir: Path) -> Path:
    """Return the Python executable inside ``venv_dir`` for this platform."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _latest_wheel() -> Path | None:
    """Pick the most recently built aurora wheel under ``dist/``."""
    if not DIST_DIR.exists():
        return None
    wheels = sorted(
        DIST_DIR.glob("aurora-*.whl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return wheels[0] if wheels else None


def main() -> int:
    print("[release_smoke] Step 1: building wheel...")
    code, out, err = _run(
        [sys.executable, "-m", "build", "--wheel"],
        cwd=REPO_ROOT,
    )
    if code != 0:
        return _fail("build wheel", code, out, err)

    wheel = _latest_wheel()
    if wheel is None:
        return _fail(
            "locate wheel",
            1,
            out,
            "No aurora-*.whl found in dist/ after build.",
        )
    print(f"[release_smoke] built wheel: {wheel.name}")

    with tempfile.TemporaryDirectory(prefix="aurora_smoke_") as tmpdir:
        venv_dir = Path(tmpdir) / "venv"
        print(f"[release_smoke] Step 2: creating venv at {venv_dir}...")
        code, out, err = _run([sys.executable, "-m", "venv", str(venv_dir)])
        if code != 0:
            return _fail("create venv", code, out, err)

        venv_py = _venv_python(venv_dir)
        if not venv_py.exists():
            return _fail(
                "locate venv python",
                1,
                "",
                f"Expected python at {venv_py}",
            )

        print("[release_smoke] Step 3: installing wheel into venv...")
        code, out, err = _run([str(venv_py), "-m", "pip", "install", str(wheel)])
        if code != 0:
            return _fail("install wheel", code, out, err)

        print("[release_smoke] Step 4: import aurora + print version...")
        code, out, err = _run(
            [
                str(venv_py),
                "-c",
                "import aurora; print(aurora.__version__)",
            ]
        )
        if code != 0:
            return _fail("import aurora", code, out, err)
        version = out.strip()
        if not version:
            return _fail(
                "import aurora",
                1,
                out,
                "aurora.__version__ printed no value.",
            )
        print(f"[release_smoke] aurora.__version__ = {version}")

        print("[release_smoke] Step 5: aurora.cli.forge --version smoke...")
        code, out, err = _run(
            [
                str(venv_py),
                "-c",
                "from aurora.cli.forge import main; main(['--version'])",
            ]
        )
        if code != 0:
            return _fail("cli --version", code, out, err)
        print(f"[release_smoke] CLI --version output: {out.strip()}")

    print("[release_smoke] OK -- wheel smoke passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
