"""Verify the exact catalog production dependency boundary without installing."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Sequence


_LOCKED_DISTRIBUTION = re.compile(r"^([A-Za-z0-9_.-]+)==[^\s\\]+(?:\s|\\|$)")


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _locked_distributions(lock_text: str) -> frozenset[str]:
    result: set[str] = set()
    current: str | None = None
    current_has_hash = False
    for line in lock_text.splitlines():
        match = _LOCKED_DISTRIBUTION.match(line)
        if match is not None:
            if current is not None and not current_has_hash:
                raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_HASH_MISSING:{current}")
            current = _normalize_distribution(match.group(1))
            current_has_hash = "--hash=sha256:" in line
            result.add(current)
        elif current is not None and "--hash=sha256:" in line:
            current_has_hash = True
    if current is not None and not current_has_hash:
        raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_HASH_MISSING:{current}")
    if not result:
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_EMPTY")
    return frozenset(result)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_production_runtime(
    *,
    lock_path: Path,
    import_names: Sequence[str],
    required_distributions: Sequence[str],
    output_path: Path,
) -> dict[str, object]:
    """Reject an incomplete lock or import closure before a run can be admitted."""

    lock = Path(lock_path).resolve(strict=True)
    if not lock.is_file():
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_INVALID")
    lock_bytes = lock.read_bytes()
    try:
        lock_text = lock_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_INVALID") from exc
    locked = _locked_distributions(lock_text)
    required = tuple(_normalize_distribution(value) for value in required_distributions)
    if not required or len(required) != len(set(required)):
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_SET_INVALID")
    for distribution in required:
        if distribution not in locked:
            raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_MISSING:{distribution}")

    imports = tuple(str(value) for value in import_names)
    if not imports or len(imports) != len(set(imports)):
        raise ValueError("CATALOG_PRODUCTION_IMPORT_SET_INVALID")
    for module_name in imports:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise ValueError(f"CATALOG_PRODUCTION_IMPORT_FAILED:{module_name}") from exc

    identity: dict[str, object] = {
        "schema_version": "1",
        "status": "PREPARED",
        "dependency_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "locked_distributions": sorted(locked),
        "required_distributions": list(required),
        "verified_imports": list(imports),
        "production_dependency_smoke_passed": True,
        "network_install_performed": False,
    }
    receipt = {**identity, "receipt_sha256": _canonical_sha256(identity)}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--import", dest="imports", action="append", required=True)
    parser.add_argument(
        "--require-distribution",
        dest="required_distributions",
        action="append",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    verify_production_runtime(
        lock_path=args.lock,
        import_names=tuple(args.imports),
        required_distributions=tuple(args.required_distributions),
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
