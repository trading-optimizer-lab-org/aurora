"""Create a verified end-to-end runtime audit from GitHub Actions metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aurora.infra.sp500_megarun.catalog_actions_audit import (
    build_actions_runtime_audit,
)


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text("utf-8"))


def _flatten_jobs(payload: Any) -> list[dict[str, object]]:
    pages = payload if isinstance(payload, list) else [payload]
    jobs: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("jobs"), list):
            raise ValueError("CATALOG_ACTIONS_JOBS_PAYLOAD_INVALID")
        jobs.extend(dict(job) for job in page["jobs"])
    return jobs


def _flatten_artifacts(payload: Any) -> list[dict[str, object]]:
    pages = payload if isinstance(payload, list) else [payload]
    artifacts: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("artifacts"), list):
            raise ValueError("CATALOG_ACTIONS_ARTIFACTS_PAYLOAD_INVALID")
        artifacts.extend(dict(item) for item in page["artifacts"])
    return artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--thermal-state",
        choices=("cold", "runtime_warm", "component_warm", "fully_hot"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_actions_runtime_audit(
        run=_read(args.run),
        jobs=_flatten_jobs(_read(args.jobs)),
        artifacts=_flatten_artifacts(_read(args.artifacts)),
        receipt=_read(args.receipt),
        thermal_state=args.thermal_state,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
