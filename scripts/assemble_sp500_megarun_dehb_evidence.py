"""Assemble latest complete worker artifacts across bounded retry runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from aurora.core.execution_policy import require_github_only_execution


def assemble_worker_evidence(
    source_dirs: list[Path],
    *,
    output_dir: Path,
) -> dict:
    output = output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("EVIDENCE_OUTPUT_MUST_START_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    selected: dict[str, dict[str, str]] = {}
    for source_order, source in enumerate(source_dirs):
        root = source.resolve()
        if not root.is_dir():
            raise ValueError(f"EVIDENCE_SOURCE_MISSING:{root}")
        for artifact in sorted(root.rglob("sp500-dehb-worker-J*")):
            if not artifact.is_dir():
                continue
            result_path = artifact / "worker_result.json"
            if not result_path.is_file():
                continue
            try:
                result = json.loads(result_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"WORKER_RESULT_INVALID:{artifact.name}") from exc
            job_id = str(result.get("job_id", ""))
            if artifact.name != f"sp500-dehb-worker-{job_id}":
                raise ValueError(f"WORKER_ARTIFACT_NAME_MISMATCH:{artifact.name}")
            target = output / artifact.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(artifact, target)
            selected[job_id] = {
                "source_order": str(source_order),
                "source_path": str(root),
            }
    receipt = {
        "schema_version": 1,
        "complete_worker_count": len(selected),
        "jobs": dict(sorted(selected.items())),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "assembly_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_ASSEMBLE_EVIDENCE")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = assemble_worker_evidence(
        args.source_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
