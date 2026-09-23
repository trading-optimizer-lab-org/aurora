#!/usr/bin/env python3
"""Select active catalog campaigns for automatic preparation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select catalog preparation targets.")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--campaign-key", default="")
    parser.add_argument("--github-output", required=True, type=Path)
    return parser


def select_targets(
    *,
    repo_root: Path,
    campaign_key: str,
    github_output: Path,
) -> tuple[str, ...]:
    root = repo_root.resolve(strict=True)
    if repo_root.is_symlink() or not root.is_dir() or github_output.is_symlink():
        raise ValueError("CATALOG_PREPARATION_TARGET_PATH_INVALID")
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    active_rows = tuple(
        sorted(
            (item for item in registry.campaigns if item.active),
            key=lambda item: item.campaign_key,
        )
    )
    active = tuple(item.campaign_key for item in active_rows)
    if campaign_key:
        if campaign_key not in active:
            raise ValueError("CATALOG_PREPARATION_TARGET_NOT_ACTIVE")
        active_rows = tuple(item for item in active_rows if item.campaign_key == campaign_key)
        active = (campaign_key,)
    if not active:
        raise ValueError("CATALOG_PREPARATION_TARGETS_EMPTY")
    optimized_matrix = json.dumps(
        {"include": [
            {"campaign_key": item.campaign_key}
            for item in active_rows if item.engine_id == "optimized_catalog_v1"
        ]},
        sort_keys=True,
        separators=(",", ":"),
    )
    atlas_matrix = json.dumps(
        {"include": [
            {"campaign_key": item.campaign_key}
            for item in active_rows if item.engine_id == "atlas_static_v1"
        ]},
        sort_keys=True,
        separators=(",", ":"),
    )
    unknown = {item.engine_id for item in active_rows} - {
        "optimized_catalog_v1", "atlas_static_v1"
    }
    if unknown:
        raise ValueError("CATALOG_PREPARATION_ENGINE_UNSUPPORTED")
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"matrix={optimized_matrix}\n")
        stream.write(f"atlas_matrix={atlas_matrix}\n")
        stream.write(f"optimized_count={sum(item.engine_id == 'optimized_catalog_v1' for item in active_rows)}\n")
        stream.write(f"atlas_count={sum(item.engine_id == 'atlas_static_v1' for item in active_rows)}\n")
        stream.write(f"target_count={len(active)}\n")
    return active


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        select_targets(
            repo_root=args.repo_root,
            campaign_key=args.campaign_key,
            github_output=args.github_output,
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
