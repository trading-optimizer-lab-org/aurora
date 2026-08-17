"""Verify that runtime HEAD differs from frozen science only in operational files."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import subprocess

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVISION_MODULE = REPOSITORY_ROOT / "infra/sp500_megarun/dehb_continuous_revision.py"
_SPEC = importlib.util.spec_from_file_location("dehb_continuous_revision", REVISION_MODULE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("CONTINUOUS_REVISION_GUARD_IMPORT_FAILED")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
unexpected_scientific_changes = _MODULE.unexpected_scientific_changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scientific-commit", required=True)
    args = parser.parse_args()
    commit = str(args.scientific_commit).lower()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("CONTINUOUS_SCIENTIFIC_COMMIT_INVALID")
    subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], check=True)
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{commit}..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    unexpected = unexpected_scientific_changes(changed)
    if unexpected:
        raise RuntimeError(
            "CONTINUOUS_SCIENTIFIC_REVISION_DRIFT:" + ",".join(unexpected)
        )
    print(
        f"scientific revision frozen at {commit}; "
        f"operational changes verified={len(changed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
