"""Evaluate one bounded pre-audit catalog routing command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRoutingCommandV1,
    route_catalog_command,
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_ROUTING_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_ROUTING_NONFINITE_JSON:{value}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route one verified request before privileged live audit."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.input.is_symlink() or not args.input.is_file():
        raise SystemExit("CATALOG_ROUTING_INPUT_INVALID")
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("CATALOG_ROUTING_OUTPUT_INVALID")
    payload = json.loads(
        args.input.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )
    command = CatalogRoutingCommandV1.model_validate(payload)
    decision = route_catalog_command(command)
    args.output.write_bytes(canonical_model_bytes(decision) + b"\n")
    if args.github_output is not None:
        if args.github_output.is_symlink():
            raise SystemExit("CATALOG_ROUTING_GITHUB_OUTPUT_INVALID")
        values = {
            "needs_live_audit": str(decision.needs_live_audit).lower(),
            "outcome": decision.outcome.value,
            "reason_code": decision.reason_code,
            "route_sha256": decision.route_sha256,
            "authority_id": str(decision.authority_id or ""),
        }
        with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
