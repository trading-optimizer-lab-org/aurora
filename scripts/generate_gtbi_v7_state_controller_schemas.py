"""Generate canonical JSON Schemas for the readiness state controller."""

from __future__ import annotations

from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.readiness_state_controller.schemas import schema_documents

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "config/gtbi/schemas/readiness"


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for filename, document in schema_documents().items():
        (DESTINATION / filename).write_bytes(
            canonical_bytes(document) + b"\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
