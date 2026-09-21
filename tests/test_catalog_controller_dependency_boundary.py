"""Controller entrypoints must import without the scientific Arrow runtime."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    ("scripts.catalog_fast_gate_handoff", "scripts/catalog_fast_gate_handoff.py"),
    (
        "aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery",
        "infra/sp500_megarun/catalog_unreserved_checkpoint_recovery.py",
    ),
    ("scripts.admit_catalog_fast_request", "scripts/admit_catalog_fast_request.py"),
    ("scripts.verify_catalog_fast_authority", "scripts/verify_catalog_fast_authority.py"),
    ("scripts.publish_catalog_fast_authority", "scripts/publish_catalog_fast_authority.py"),
    ("scripts.catalog_cloud_intake", "scripts/catalog_cloud_intake.py"),
    ("scripts.publish_catalog_cloud_authority", "scripts/publish_catalog_cloud_authority.py"),
)


@pytest.mark.parametrize(("module_name", "relative_path"), ENTRYPOINTS)
def test_controller_entrypoint_imports_without_pyarrow(
    module_name: str, relative_path: str,
) -> None:
    expected_file = ROOT / relative_path
    assert expected_file.is_file(), f"Controller entrypoint missing: {expected_file}"
    code = """
import importlib
import importlib.abc
import json
from pathlib import Path
import sys
from types import ModuleType

repo = Path(sys.argv[1]).resolve(strict=True)
module_name, relative_path = sys.argv[2:]
sys.path.insert(0, str(repo))
# Do not let an editable installation select another shared checkout.
for name, directory in (
    ('aurora', repo),
    ('aurora.infra', repo / 'infra'),
    ('aurora.infra.sp500_megarun', repo / 'infra' / 'sp500_megarun'),
    ('scripts', repo / 'scripts'),
):
    package = ModuleType(name)
    package.__path__ = [str(directory)]
    sys.modules[name] = package

class BlockPyArrow(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.attempted = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'pyarrow' or fullname.startswith('pyarrow.'):
            self.attempted.append(fullname)
            raise ModuleNotFoundError('controller boundary blocked pyarrow', name=fullname)
        return None

assert not any(name == 'pyarrow' or name.startswith('pyarrow.') for name in sys.modules)
blocker = BlockPyArrow()
sys.meta_path.insert(0, blocker)
try:
    importlib.import_module('pyarrow')
except ModuleNotFoundError as exc:
    assert exc.name == 'pyarrow' and blocker.attempted == ['pyarrow']
else:
    raise AssertionError('pyarrow blocker was not exercised')
blocker.attempted.clear()

module = importlib.import_module(module_name)
assert Path(module.__file__).resolve() == (repo / relative_path).resolve()
# An optional import that swallowed ModuleNotFoundError is still a dependency leak.
assert not blocker.attempted, f'pyarrow import attempted: {blocker.attempted}'
for name, loaded in tuple(sys.modules.items()):
    if name.startswith(('aurora.', 'scripts.')) and getattr(loaded, '__file__', None):
        assert Path(loaded.__file__).resolve().is_relative_to(repo), (name, loaded.__file__)
print(json.dumps({'module': module_name, 'path': str(Path(module.__file__).resolve())}))
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, str(ROOT), module_name, relative_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, (
        f"{module_name}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    evidence = json.loads(completed.stdout)
    assert evidence["module"] == module_name
    assert Path(evidence["path"]) == expected_file.resolve()
