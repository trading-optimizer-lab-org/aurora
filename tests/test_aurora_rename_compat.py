"""Regression tests for the Aurora rename compatibility shim."""
from __future__ import annotations

import subprocess
import sys


def test_aurora_submodule_import_aliases_aurora():
    code = (
        "import warnings;"
        "warnings.simplefilter('ignore', DeprecationWarning);"
        "import aurora.cli.forge as a;"
        "import aurora.cli.forge as q;"
        "print(a.main is q.main)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "True"


def test_legacy_aurora_module_help_still_runs():
    result = subprocess.run(
        [sys.executable, "-m", "aurora.cli.forge", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Aurora CLI" in result.stdout
