"""Exercise the reducer's deferred imports outside pytest's import path."""
import os
from pathlib import Path
import subprocess
import sys


def test_reducer_file_entry_reaches_recovery_validation_without_repo_on_path(tmp_path):
    root = Path(__file__).resolve().parents[1]
    probe = r'''
import aurora
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

root = Path(sys.argv[1]).resolve()
assert Path(aurora.__file__).resolve().parent == root
sys.path = [entry for entry in sys.path if entry and Path(entry).resolve() != root]
namespace = runpy.run_path(str(root / "scripts/reduce_sp500_optimized_catalog_run.py"))
try:
    namespace["_load_reduction_only_source"](
        SimpleNamespace(sealed_plan=None, resume_root=[]),
        work_manifest=None, science_sha256="0" * 64,
        catalog_manifest_sha256="1" * 64, expected_ids=[],
    )
except ValueError as exc:
    assert str(exc) == "CATALOG_REDUCTION_RECOVERY_INPUT_INVALID", str(exc)
else:
    raise AssertionError("Invalid inputs were accepted")
'''
    result = subprocess.run(
        [sys.executable, "-c", probe, str(root)], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
