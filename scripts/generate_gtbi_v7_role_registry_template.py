"""Generate the owner-controlled GTBI V7 role registry."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.roles import (  # noqa: E402
    build_owner_controlled_role_registry,
    validate_role_registry,
)

DEFAULT_COLLABORATORS = ROOT / "docs/project_inventory/collaborators.csv"
DEFAULT_AUDIT_METADATA = ROOT / "docs/project_inventory/audit_metadata.json"
DEFAULT_SCHEMA = (
    ROOT / "config/gtbi/schemas/readiness/role_registry_v1.schema.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "config/gtbi/fixtures/v7/governance/role_registry_v1.owner_controlled.json"
)


def generate(
    *,
    collaborators_path: Path = DEFAULT_COLLABORATORS,
    audit_metadata_path: Path = DEFAULT_AUDIT_METADATA,
    schema_path: Path = DEFAULT_SCHEMA,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict:
    rows = list(
        csv.DictReader(collaborators_path.read_text(encoding="utf-8").splitlines())
    )
    admins = [row for row in rows if row.get("role_name") == "admin"]
    if len(admins) != 1:
        raise ValueError("owner-controlled registry requires exactly one owner")

    metadata = json.loads(audit_metadata_path.read_text(encoding="utf-8"))
    owner = admins[0]
    registry = build_owner_controlled_role_registry(
        repository=metadata["repository"],
        owner_github_actor_id=int(owner["id"]),
        owner_github_login=owner["login"],
        observed_at_utc=metadata["audited_at_utc"],
    )
    validate_role_registry(registry, schema_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return registry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collaborators", type=Path, default=DEFAULT_COLLABORATORS)
    parser.add_argument("--audit-metadata", type=Path, default=DEFAULT_AUDIT_METADATA)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    registry = generate(
        collaborators_path=args.collaborators,
        audit_metadata_path=args.audit_metadata,
        schema_path=args.schema,
        output_path=args.output,
    )
    vacant = sum(
        item["status"] == "vacant" for item in registry["assignments"]
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "registry_status": registry["registry_status"],
                "vacant_assignments": vacant,
                "role_registry_digest": registry["role_registry_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
