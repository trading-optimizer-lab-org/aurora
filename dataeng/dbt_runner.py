"""dbt subprocess wrapper.

Invokes the ``dbt`` CLI via ``subprocess.run``. ``mock=True`` skips the actual
process and synthesizes a successful run record so unit tests don't need a dbt
installation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DBTConfig:
    """Static config for :class:`DBTRunner`.

    Attributes:
        project_dir: dbt project directory (where ``dbt_project.yml`` lives).
        profiles_dir: dbt profiles directory.
        target: dbt profile target name.
        select: dbt model selector (``+model_name`` etc.).
        timeout_s: subprocess timeout in seconds.
    """
    project_dir: str = "."
    profiles_dir: str = "."
    target: str = "dev"
    select: str = ""
    timeout_s: float = 600.0


@dataclass
class DBTRunResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class DBTRunner:
    """Subprocess wrapper around ``dbt run`` and ``dbt test``."""

    def __init__(self, config: Optional[DBTConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or DBTConfig()
        self.mock = bool(mock)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def run(self) -> DBTRunResult:
        return self._invoke("run")

    def test(self) -> DBTRunResult:
        return self._invoke("test")

    def build_command(self, action: str) -> tuple[str, ...]:
        cmd: list[str] = ["dbt", action,
                          "--project-dir", self.config.project_dir,
                          "--profiles-dir", self.config.profiles_dir,
                          "--target", self.config.target]
        if self.config.select:
            cmd.extend(["--select", self.config.select])
        return tuple(cmd)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _invoke(self, action: str) -> DBTRunResult:
        cmd = self.build_command(action)
        if self.mock:
            return DBTRunResult(
                command=cmd,
                returncode=0,
                stdout=f"[mock] dbt {action} ok",
                stderr="",
                duration_s=0.001,
            )
        return self._invoke_subprocess(cmd)  # pragma: no cover

    def _invoke_subprocess(self, cmd: tuple[str, ...]) -> DBTRunResult:  # pragma: no cover
        if shutil.which("dbt") is None:
            raise RuntimeError("dbt CLI not on PATH")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                list(cmd),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "timeout")
            return DBTRunResult(
                command=cmd, returncode=124,
                stdout=stdout, stderr=stderr,
                duration_s=time.monotonic() - t0,
            )
        return DBTRunResult(
            command=cmd, returncode=proc.returncode,
            stdout=proc.stdout, stderr=proc.stderr,
            duration_s=time.monotonic() - t0,
        )
