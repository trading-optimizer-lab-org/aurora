"""Create one unsigned catalog request intent from a broker-owned ticket."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a canonical unsigned catalog-run intent draft."
    )
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--launch-ticket", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/catalog_campaign_registry_v1.json"),
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=Path("docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict_json(path: Path) -> object:
    if path.is_symlink():
        raise ValueError("CATALOG_REQUEST_INPUT_SYMLINK_FORBIDDEN")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def _repository_file(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    if candidate.is_symlink():
        raise ValueError("CATALOG_REQUEST_INPUT_SYMLINK_FORBIDDEN")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_REQUEST_REPOSITORY_INPUT_INVALID")
    return resolved


def main() -> int:
    args = _parser().parse_args()
    root = Path.cwd().resolve(strict=True)
    output = args.output.resolve(strict=False)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("CATALOG_REQUEST_OUTPUT_ALREADY_EXISTS")

    registry_path = _repository_file(root, args.registry)
    prompt_path = _repository_file(root, args.prompt)
    registry = load_catalog_campaign_registry(registry_path)
    entry = resolve_catalog_campaign(registry, args.campaign_key, root)
    manifest_path = _repository_file(root, Path(entry.definition_manifest_path))
    manifest = parse_catalog_campaign_definition_bytes(manifest_path.read_bytes())
    verified_manifest = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=manifest,
    )

    ticket_path = args.launch_ticket.resolve(strict=True)
    if args.launch_ticket.is_symlink() or not ticket_path.is_file():
        raise ValueError("CATALOG_LAUNCH_TICKET_INVALID")
    ticket = CatalogLaunchTicketV1.model_validate(_strict_json(ticket_path))
    prompt_sha256 = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if ticket.campaign_key != entry.campaign_key:
        raise ValueError("CATALOG_LAUNCH_TICKET_CAMPAIGN_MISMATCH")
    if ticket.campaign_definition_sha256 != (
        verified_manifest.campaign_definition_sha256
    ):
        raise ValueError("CATALOG_LAUNCH_TICKET_DEFINITION_MISMATCH")
    if ticket.prompt_sha256 != prompt_sha256:
        raise ValueError("CATALOG_LAUNCH_TICKET_PROMPT_MISMATCH")

    draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=ticket.request_id,
        campaign_key=ticket.campaign_key,
        launch_generation=ticket.launch_generation,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=(ticket.previous_terminal_request_sha256),
        campaign_definition_sha256=ticket.campaign_definition_sha256,
        prompt_sha256=ticket.prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    draft = CatalogRunIntentDraftV1.model_validate_json(canonical_model_bytes(draft))
    envelope = {
        "draft": draft.model_dump(mode="json"),
        "submission_key_sha256": draft.submission_key_sha256,
    }
    encoded = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
