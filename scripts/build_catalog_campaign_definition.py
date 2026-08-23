"""Print or verify one registered catalog campaign definition."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    discover_catalog_campaign_definition,
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print or check a closed registered campaign definition."
    )
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/catalog_campaign_registry_v1.json"),
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-candidate", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser


def _checked_file(path: Path, *, root: Path) -> Path:
    if path.is_symlink():
        raise ValueError("CATALOG_DEFINITION_SYMLINK_FORBIDDEN")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_DEFINITION_INPUT_OUTSIDE_REPOSITORY")
    return resolved


def main() -> int:
    args = _parser().parse_args()
    root = args.repo_root.resolve(strict=True)
    registry_path = _checked_file(
        args.registry if args.registry.is_absolute() else root / args.registry,
        root=root,
    )
    registry = load_catalog_campaign_registry(registry_path)
    entry = resolve_catalog_campaign(registry, args.campaign_key, root)
    if args.print_candidate:
        candidate = discover_catalog_campaign_definition(
            repo_root=root,
            registry_entry=entry,
        )
        sys.stdout.buffer.write(candidate.canonical_bytes + b"\n")
        return 0

    manifest_path = _checked_file(root / entry.definition_manifest_path, root=root)
    checked = parse_catalog_campaign_definition_bytes(manifest_path.read_bytes())
    verified = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=checked,
    )
    print(f"CATALOG_CAMPAIGN_DEFINITION_OK:{verified.campaign_definition_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
