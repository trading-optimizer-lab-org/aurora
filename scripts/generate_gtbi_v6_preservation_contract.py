"""Generate the fixed V6 result preservation manifest and its schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest  # noqa: E402

DOMAIN = "GTBI_V6_PRESERVATION_MANIFEST_V1"
FIELDS = (
    "schema_version",
    "source_repository",
    "source_run_id",
    "source_artifact_id",
    "source_artifact_name",
    "source_size_bytes",
    "source_archive_digest",
    "source_expires_at_utc",
    "maximum_archive_bytes",
    "maximum_member_count",
    "maximum_total_uncompressed_bytes",
    "maximum_compression_ratio",
    "part_size_bytes",
    "preservation_manifest_digest",
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def generate(root: Path) -> tuple[dict, dict]:
    manifest = {
        "schema_version": "v6_preservation_manifest_v1",
        "source_repository": "trading-optimizer-lab-org/aurora",
        "source_run_id": 29162930823,
        "source_artifact_id": 8251391531,
        "source_artifact_name": (
            "global-technical-buy-indicator-long-hold-fast-strict-v6-results"
        ),
        "source_size_bytes": 1962204087,
        "source_archive_digest": (
            "sha256:870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
        ),
        "source_expires_at_utc": "2026-08-10T18:16:37Z",
        "maximum_archive_bytes": 2000000000,
        "maximum_member_count": 500000,
        "maximum_total_uncompressed_bytes": 50000000000,
        "maximum_compression_ratio": 200,
        "part_size_bytes": 1992294400,
        "preservation_manifest_digest": "",
    }
    manifest["preservation_manifest_digest"] = domain_digest(
        DOMAIN,
        manifest,
        omit_top_level_fields=("preservation_manifest_digest",),
    )
    integer_fields = {
        "source_run_id",
        "source_artifact_id",
        "source_size_bytes",
        "maximum_archive_bytes",
        "maximum_member_count",
        "maximum_total_uncompressed_bytes",
        "maximum_compression_ratio",
        "part_size_bytes",
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aurora.invalid/schemas/v6_preservation_manifest_v1",
        "title": "v6_preservation_manifest_v1",
        "type": "object",
        "additionalProperties": False,
        "required": list(FIELDS),
        "properties": {
            field: (
                {"type": "integer", "minimum": 1}
                if field in integer_fields
                else {
                    "type": "string",
                    "minLength": 1,
                }
            )
            for field in FIELDS
        },
    }
    schema["properties"]["schema_version"]["const"] = (
        "v6_preservation_manifest_v1"
    )
    schema["properties"]["source_repository"]["const"] = (
        "trading-optimizer-lab-org/aurora"
    )
    schema["properties"]["preservation_manifest_digest"]["pattern"] = (
        "^sha256:[0-9a-f]{64}$"
    )
    _write(
        root
        / "config/gtbi/schemas/v7/operational/"
        "v6_preservation_manifest_v1.schema.json",
        schema,
    )
    _write(
        root / "config/gtbi/manifests/v6_fast_strict_preservation_manifest.json",
        manifest,
    )
    return manifest, schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    manifest, _ = generate(args.repository_root.resolve())
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
