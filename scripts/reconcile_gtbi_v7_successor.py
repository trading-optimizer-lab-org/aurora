from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PROJECT_ROOT.parent
for candidate in (PROJECT_PARENT, PROJECT_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from aurora.infra.gtbi_v7_readiness.successor_completion import (
        SuccessorCompletionError,
        build_completed_clean,
        build_preterminal_receipt,
        build_security_approval,
    )
except ModuleNotFoundError:
    from infra.gtbi_v7_readiness.successor_completion import (
        SuccessorCompletionError,
        build_completed_clean,
        build_preterminal_receipt,
        build_security_approval,
    )


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--reviewed-commit", default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output_dir or root / "docs/readiness/gtbi-v7-successor").resolve()
    if args.prepare == args.finalize:
        parser.error("select exactly one of --prepare or --finalize")

    if args.prepare:
        security = build_security_approval(root)
        _write(output / "security_approval_receipt.json", security)
        preterminal = build_preterminal_receipt(root)
        _write(output / "preterminal_reconciliation.json", preterminal)
        print(json.dumps(preterminal, indent=2, sort_keys=True))
        return 0 if preterminal["status"] == "ready_for_terminal_reconciliation" else 1

    try:
        completed = build_completed_clean(
            root,
            reviewed_commit=args.reviewed_commit or _git_head(root),
        )
    except SuccessorCompletionError as exc:
        print(json.dumps({"terminal_output": "BLOCKED", "reason": str(exc)}, indent=2))
        return 1
    _write(output / "completed_clean.json", completed)
    print(json.dumps(completed, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
