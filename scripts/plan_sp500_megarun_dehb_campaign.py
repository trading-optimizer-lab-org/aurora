from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    build_campaign_manifest,
    load_and_validate_campaign_contract,
    validate_campaign_bindings,
)
from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_shard_matrices


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_prior_decision(
    path: Path,
    *,
    campaign_sha256: str,
    wave: int,
) -> tuple[dict[str, int], frozenset[str]]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("PRIOR_CONTROLLER_DECISION_NOT_MAPPING")
    if (
        value.get("campaign_contract_sha256") != campaign_sha256
        or value.get("action") != "dispatch_next_wave"
        or int(value.get("next_wave", -1)) != wave
        or value.get("validation_opened") is not False
        or value.get("locked_opened") is not False
    ):
        raise ValueError("PRIOR_CONTROLLER_DECISION_INVALID")
    raw_ordinals = value.get("next_island_restart_ordinals")
    raw_resume = value.get("resume_island_ids")
    if not isinstance(raw_ordinals, dict) or not isinstance(raw_resume, list):
        raise ValueError("PRIOR_CONTROLLER_RUNTIME_STATE_INVALID")
    return (
        {
            str(island_id): int(ordinal)
            for island_id, ordinal in raw_ordinals.items()
        },
        frozenset(str(island_id) for island_id in raw_resume),
    )


def _write_github_outputs(path: Path, values: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
            handle.write(f"{key}={encoded}\n")


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_CAMPAIGN_PLAN")
    parser = argparse.ArgumentParser(description="Freeze three 120-job DEHB shard matrices.")
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO_ROOT / "config" / "sp500_megarun_dehb_campaign_v1.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wave", type=int, required=True)
    parser.add_argument("--restart-ordinal", type=int, required=True)
    parser.add_argument("--prior-decision", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    contract = load_and_validate_campaign_contract(args.contract)
    bindings = validate_campaign_bindings(contract, repo_root=REPO_ROOT)
    manifest = build_campaign_manifest(contract)
    island_restart_ordinals = None
    resume_island_ids = None
    if args.prior_decision is not None:
        island_restart_ordinals, resume_island_ids = _load_prior_decision(
            args.prior_decision,
            campaign_sha256=contract.sha256,
            wave=args.wave,
        )
    matrices = build_shard_matrices(
        contract,
        wave=args.wave,
        restart_ordinal=args.restart_ordinal,
        island_restart_ordinals=island_restart_ordinals,
        resume_island_ids=resume_island_ids,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "campaign_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "campaign_binding_receipt.json").write_text(
        json.dumps(bindings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for shard in "ABC":
        (output_dir / f"matrix_{shard}.json").write_text(
            json.dumps(matrices[shard], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    github_output = args.github_output
    if github_output is None and os.environ.get("GITHUB_OUTPUT"):
        github_output = Path(os.environ["GITHUB_OUTPUT"])
    if github_output is not None:
        _write_github_outputs(
            github_output,
            {
                "matrix_a": matrices["A"],
                "matrix_b": matrices["B"],
                "matrix_c": matrices["C"],
                "campaign_contract_sha256": contract.sha256,
                "campaign_manifest_sha256": manifest["manifest_sha256"],
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
