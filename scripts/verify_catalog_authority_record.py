#!/usr/bin/env python3
"""Verify one authority record only after its mirror and comment read back."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_authority_writer import (  # noqa: E402
    CatalogAuthorityTransitionCandidateV1,
    verify_catalog_authority_commit,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (  # noqa: E402
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_routing import (  # noqa: E402
    CatalogRoutingCommandV1,
)


_SAFE_OUTPUT = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the exact authority record from one fresh dual-ledger snapshot."
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--routing-command", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


def _strict_json(path: Path, *, runner_temp: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_AUTHORITY_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    if path.is_symlink():
        raise ValueError("CATALOG_AUTHORITY_INPUT_INVALID")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(runner_temp):
        raise ValueError("CATALOG_AUTHORITY_INPUT_INVALID")
    return json.loads(
        resolved.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_AUTHORITY_JSON_NONFINITE:{value}")
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
        if not runner_temp_raw:
            raise ValueError("CATALOG_AUTHORITY_WRITER_ENVIRONMENT_INVALID")
        runner_temp = Path(runner_temp_raw).resolve(strict=True)
        output = args.output.resolve(strict=False)
        if (
            args.output.exists()
            or args.output.is_symlink()
            or not output.is_relative_to(runner_temp)
        ):
            raise ValueError("CATALOG_AUTHORITY_OUTPUT_INVALID")
        candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
            _strict_json(args.candidate, runner_temp=runner_temp)
        )
        command = CatalogRoutingCommandV1.model_validate(
            _strict_json(args.routing_command, runner_temp=runner_temp)
        )
        receipt = verify_catalog_authority_commit(
            candidate=candidate,
            fresh_ledger=command.ledger,
        )
        args.output.write_bytes(canonical_model_bytes(receipt) + b"\n")
        values = {
            "authority_committed": "true",
            "record_sha256": receipt.record.record_sha256,
            "authority_state": receipt.expected_state.value,
            "candidate_sha256": receipt.candidate_sha256,
        }
        if any(not _SAFE_OUTPUT.fullmatch(value) for value in values.values()):
            raise ValueError("CATALOG_AUTHORITY_GITHUB_OUTPUT_INVALID")
        if args.github_output is not None:
            if args.github_output.is_symlink():
                raise ValueError("CATALOG_AUTHORITY_GITHUB_OUTPUT_INVALID")
            with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                for key, value in values.items():
                    stream.write(f"{key}={value}\n")
        print(json.dumps(values, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
