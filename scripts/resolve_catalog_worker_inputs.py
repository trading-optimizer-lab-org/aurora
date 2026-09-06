"""Resolve immutable, registry-bound inputs for the catalog recipe worker."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
    resolve_catalog_for_reduction,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_selected_results import (
    resolve_registered_selected_result_keys,
)


_OUTPUT_FIELDS = (
    "campaign_contract_path",
    "catalog_dir",
    "selected_config_path",
)


def resolve_worker_inputs(
    *,
    repo_root: Path,
    resolved_contract: Path,
    run_plan: Path,
    admission_token: str,
) -> dict[str, str]:
    """Validate the sealed plan and return paths from its registered campaign."""

    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("CATALOG_WORKER_REPOSITORY_INVALID")

    plan = verify_catalog_plan_token(
        Path(run_plan),
        admission_token_sha256=admission_token,
    )
    try:
        contract = RunOptimizationContractV1.model_validate_json(
            Path(resolved_contract).read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_WORKER_CONTRACT_INVALID") from exc

    if contract.contract_sha256 != plan.contract_sha256:
        raise ValueError("CATALOG_WORKER_CONTRACT_PLAN_MISMATCH")

    science_sha256 = canonical_sha256(contract.science)
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    matches = tuple(
        entry
        for entry in registry.campaigns
        if entry.active and entry.scientific_contract_sha256 == science_sha256
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_WORKER_CAMPAIGN_UNRESOLVED")

    entry = resolve_catalog_campaign(registry, matches[0].campaign_key, root)
    catalog_path = resolve_catalog_for_reduction(
        repo_root=root,
        scientific_contract_sha256=science_sha256,
        catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
    )
    # Keep the production selected-result guard as the authority for the
    # catalog, full campaign definition, and selected configuration binding.
    resolve_registered_selected_result_keys(
        repo_root=root,
        scientific_contract_sha256=science_sha256,
        catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
        catalog_path=catalog_path,
    )

    return {field: getattr(entry, field) for field in _OUTPUT_FIELDS}


def _validate_github_output(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("CATALOG_WORKER_OUTPUT_INVALID")


def _append_github_outputs(path: Path, outputs: dict[str, str]) -> None:
    """Append all validated outputs in one write, retaining existing bytes."""

    _validate_github_output(path)
    prefix = ""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as stream:
            if not stream.read()[-1:] == b"\n":
                prefix = "\n"
    payload = prefix + "".join(
        f"{field}={outputs[field]}\n" for field in _OUTPUT_FIELDS
    )
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_github_output(args.github_output)
        outputs = resolve_worker_inputs(
            repo_root=args.repo_root,
            resolved_contract=args.resolved_contract,
            run_plan=args.run_plan,
            admission_token=args.admission_token,
        )
        _append_github_outputs(args.github_output, outputs)
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
